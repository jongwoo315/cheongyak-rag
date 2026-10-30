"""#80 실패 징후 1~6을 재고 리포트 `docs/80-axis-verdict.md`·`runs/80/last_run.json`을 쓴다.

python -m cheongyak_rag.generate.verdict_report --report [--budget-usd 3]

`runs/79/last_run.json`의 표본 공고 6건 × `runs/80/profiles/`의 프로필 3종에
`verdict.judge`를 돌린다. 판정은 guard 전(인용 대조까지 마친 LLM 판정)과 후(최종 판정)를
나란히 센다.
구간 이름(통과·다시 잰다·미완)과 경계는 plan §실패 징후의 것이다. 꺼진 축 판정과 없는 인용 라벨은
측정 코드가 SQL로 따로 다시 센다(`independent_on`·`label_exists` — `verdict.py`의 대조
함수를 부르지 않는다). 징후 1은 guard 표(`REQUIRED_FIELDS`)를 읽지 않고 이유 문장에서
`REASON_WORDS`를 센다. PR #13 값은 `runs/80/pr13_baseline.json`에서 읽는다.
"""

import argparse
import dataclasses
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag import profile as prof
from cheongyak_rag.config import settings
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate.answer import GenCache, HardApiError, check_model, make_client
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.ingest.notice_report import _bullets, _table
from cheongyak_rag.retrieval import axes, index_db
from cheongyak_rag.retrieval.axes_report import independent_on
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import now, write

ROOT = Path(__file__).resolve().parents[3]
OUT_MD = ROOT / "docs/80-axis-verdict.md"
OUT_JSON = ROOT / "runs/80/last_run.json"
PROFILES_DIR = ROOT / "runs/80/profiles"
SAMPLES_JSON = ROOT / "runs/79/last_run.json"
BASELINE_JSON = ROOT / "runs/80/pr13_baseline.json"
PROFILE_NAMES = ("full", "partial", "empty")

BUDGET_USD = 3.0
DECISIVE = ("ELIGIBLE", "INELIGIBLE", "CONDITIONAL")  # 정보 부족·근거 없음이 아닌 판정
# 징후 1 — #77 프로필에 없는 값을 가리키는 말. guard 표와 따로 둔다(통과 기준 5)
REASON_WORDS = ("예치금", "납입", "거주", "소득", "자산", "당첨")
# 징후 6 — 값이 없는 것을 근거로 드는 이유
NO_VALUE_RE = re.compile(r"정보가 없|사유가 없|별도.{0,15}없")
GUARD_FIELD_AXES = ("homeless", "householder")  # 필요한 칸이 #77에 있다
PROFILE_BACKED_AXIS = "homeless"  # 징후 3 — 공고 6건 × 1축
DECISIVE_PASS, DECISIVE_RETRY = 5, 3  # 징후 3 — 6개 중
FIRST_USD_MAX = 3.0  # 징후 5
FIRST_CALLS_RETRY = 3  # 징후 5 — 첫 실행 호출이 1~3이면 다시 잰다, 4 이상이면 미완
SECOND_CALLS_RETRY = 3
MISSING_RETRY = 2  # 징후 4 — 판정 없음이 이 개수까지면 다시 잰다
SHOW = 10
TRANSIENT = ("RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError")


# ── 구간 ─────────────────────────────────────────────────────────────────


def zone_run(
    *, missing: int, out_of_enum: int, off_called: int, no_cite: int, bad_label: int,
    cell_errors: int, transient: bool,
) -> str:  # fmt: skip
    """징후 4 — 나머지가 0이고 판정 없음이 1~2개이며 전부 일시 오류면 다시 잰다."""
    if out_of_enum or off_called or no_cite or bad_label or cell_errors:
        return "미완"
    if missing == 0:
        return "통과"
    return "다시 잰다" if missing <= MISSING_RETRY and transient else "미완"


def zone_jw(a: int, b: int, cell_errors: int) -> str:
    """징후 1 — A(프로필에 없는 값을 이유로 든 최종 ELIGIBLE)가 0이고 B(최종 ELIGIBLE 총수)가
    1 이상이면 통과, A 0 · B 0이면 다시 잰다(잴 판정이 없어 기준이 공허하게 참이다).

    A 1 이상은 미완이다. 셀 전체가 실패한 것은 못 잰 것이라 미완이다.
    """
    if a or cell_errors:
        return "미완"
    return "통과" if b else "다시 잰다"


def zone_loss(n: int) -> str:
    """징후 2 — guard가 칸이 다 있는 축의 판정을 바꿨으면 표나 칸 읽기 코드가 틀린 것이다."""
    return "통과" if n == 0 else "미완"


def zone_decisive(n: int) -> str:
    """징후 3 — `homeless` 축 6개 중."""
    return "통과" if n >= DECISIVE_PASS else "다시 잰다" if n >= DECISIVE_RETRY else "미완"


def zone_cost(
    first_calls: int, first_usd: float, second_calls: int | None, stopped: bool,
    dist_same: bool = True,
) -> str:  # fmt: skip
    """징후 5 — 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 PR #13과 칸마다 같다."""
    if stopped or first_usd > FIRST_USD_MAX or first_calls > FIRST_CALLS_RETRY or not dist_same:
        return "미완"
    if first_calls > 0:
        return "다시 잰다"
    if second_calls is None:
        return "미측정"
    if second_calls == 0:
        return "통과"
    return "다시 잰다" if second_calls <= SECOND_CALLS_RETRY else "미완"


# ── 읽기 ─────────────────────────────────────────────────────────────────


def label_exists(engine: Engine, mst: str | None, label: str) -> bool:
    """`chunks`에서 라벨 하나를 직접 센다. 조문은 공고의 MST 행만, FAQ는 `faq` 행."""
    with engine.connect() as conn:
        return (
            conn.execute(
                sa.text(
                    "SELECT count(*) FROM chunks WHERE label = :l"
                    " AND ((source = 'law' AND law_mst = :m) OR source = 'faq')"
                ),
                {"l": label, "m": mst},
            ).scalar_one()
            > 0
        )


def load_profiles(profiles_dir: Path) -> dict[str, prof.Profile]:
    return {n: vd.load_profile(str(profiles_dir / f"{n}.json")) for n in PROFILE_NAMES}


def sample_notices(path: Path) -> list[str]:
    """#79 리포트의 표본 공고 — 켜진 축 목록이 서로 다른 공고마다 하나."""
    return list(dict.fromkeys(s["notice"] for s in json.loads(path.read_text("utf-8"))["samples"]))


def load_baseline(path: Path) -> dict:
    """PR #13 측정값. 없거나 못 읽으면 예외 — baseline 없이 재면 같은 응답을 읽었는지 모른다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = (
        "source", "system_sha", "total", "distribution", "eligible_final", "eligible_final_words",
        "eligible_pre", "eligible_pre_words", "guarded", "forced", "no_value",
        "decisive_homeless", "decisive_homeless_n", "account_full",
    )  # fmt: skip
    for key in keys:  # render가 쓰는 키 전부
        data[key]  # noqa: B018 — 없는 키는 KeyError로 준비 실패가 된다
    return data


def reason_words(v: dict) -> list[str]:
    """이유 문장에 나오는 `REASON_WORDS`. guard 표를 읽지 않고 문장만 본다."""
    return [w for w in REASON_WORDS if w in (v["reason"] or "")]


def pre_guard(v: dict) -> str | None:
    """인용 대조까지 마친 LLM 판정. guard가 바꾼 판정은 원래 ELIGIBLE이었다."""
    return v["original_verdict"] if v["guarded"] else v["verdict"]


def distribution(cells: list[dict], *, pre: bool) -> dict:
    """프로필 → 축 → 판정값 → 개수. `pre`면 guard 전."""
    out: dict = {}
    for c, v in _verdict_rows(cells):
        verdict = (pre_guard(v) if pre else v["verdict"]) or "판정 없음"
        n = out.setdefault(c["profile"], {}).setdefault(v["axis"], Counter())
        n[verdict] += 1
    return {
        p: {a: dict(sorted(n.items())) for a, n in sorted(axs.items())} for p, axs in out.items()
    }


def system_sha() -> str:
    return hashlib.sha256(vd.SYSTEM.encode("utf-8")).hexdigest()[:8]


# ── 측정 ─────────────────────────────────────────────────────────────────


def measure(
    engine: Engine, embedder, client, cache, model: str, notices: list[str],
    profiles: dict[str, prof.Profile], *, budget_usd: float,
) -> dict:  # fmt: skip
    """공고 × 프로필을 돌려 판정을 모은다. 예산을 넘기거나 인증 오류면 거기서 멈춘다."""
    sql_on = independent_on(engine)
    search_cache: axes.Cache = {}
    cells, cell_errors, spent, stop = [], [], 0.0, None
    for hmn in notices:
        for pname, profile in profiles.items():
            t0 = time.perf_counter()
            try:
                notice, plans, verdicts = vd.judge(
                    engine, embedder, client, model, hmn, profile, cache=cache,
                    search_cache=search_cache,
                )  # fmt: skip
                spent += sum(v.usd for v in verdicts if not v.cached)
                labelled = [_with_labels(engine, notice.facts.law_mst, v) for v in verdicts]
            except HardApiError as e:
                stop = ("hard", f"{hmn} × {pname}: {e}")
                break
            except Exception as e:  # noqa: BLE001 — 셀 하나의 실패로 보고서 전체를 잃지 않는다
                cell_errors.append(
                    {"notice": hmn, "profile": pname, "error": f"{type(e).__name__}: {e}"}
                )
                continue
            seconds = time.perf_counter() - t0
            on_sql = sql_on.get((notice.house_manage_no, notice.pblanc_no), [])
            cells.append(
                {
                    "notice": hmn,
                    "name": notice.name,
                    "profile": pname,
                    "as_of": notice.as_of.isoformat(),
                    "mst": notice.facts.law_mst,
                    "on": [p.id for p in plans if p.on],
                    "on_sql": on_sql,
                    "plans": [p.line for p in plans],
                    "seconds": seconds,
                    "verdicts": labelled,
                }
            )
            if spent > budget_usd:
                stop = ("budget", f"{hmn} × {pname}: 비용 상한 ${budget_usd} 초과 (${spent:.4f})")
                break
        if stop:
            break
    return {"cells": cells, "cell_errors": cell_errors, "stop": stop}


def _with_labels(engine: Engine, mst: str | None, v: vd.Verdict) -> dict:
    """판정 한 개의 dict. `missing_labels`는 측정 코드가 SQL로 다시 센 없는 라벨이다."""
    d = dataclasses.asdict(v)
    d["missing_labels"] = [c for c in v.citations if not label_exists(engine, mst, c)]
    return d


def _verdict_rows(cells: list[dict]):
    for c in cells:
        for v in c["verdicts"]:
            yield c, v


def _transient_only(errors: list[str]) -> bool:
    return bool(errors) and all(any(t in e for t in TRANSIENT) for e in errors)


def symptoms(m: dict, baseline: dict | None = None) -> dict:
    """징후 1~6의 값과 구간. `m`은 `measure`의 결과, `baseline`은 PR #13 측정값이다."""
    rows = list(_verdict_rows(m["cells"]))
    total = len(rows)
    missing = [(c, v) for c, v in rows if v["verdict"] is None]
    out_enum = [
        (c, v) for c, v in rows if v["verdict"] is not None and v["verdict"] not in vd.VERDICTS
    ]
    off_called = [(c, v) for c, v in rows if v["axis"] not in c["on_sql"]]
    no_cite = [
        (c, v) for c, v in rows
        if v["verdict"] not in (None, "UNVERIFIABLE") and not v["citations"]
    ]  # fmt: skip
    bad_label = [(c, v) for c, v in rows if v["missing_labels"]]
    n_bad_labels = sum(len(v["missing_labels"]) for _, v in rows)
    z4 = zone_run(
        missing=len(missing), out_of_enum=len(out_enum), off_called=len(off_called),
        no_cite=len(no_cite), bad_label=len(bad_label), cell_errors=len(m["cell_errors"]),
        transient=_transient_only([v["error"] for _, v in missing]),
    )  # fmt: skip

    # 징후 1 — 세 프로필 전부의 최종 ELIGIBLE(B) 중 이유에 프로필에 없는 값이 나오는 것(A)
    eligible = [(c, v) for c, v in rows if v["verdict"] == "ELIGIBLE"]
    unbacked = [(c, v) for c, v in eligible if reason_words(v)]
    pre_eligible = [(c, v) for c, v in rows if pre_guard(v) == "ELIGIBLE"]
    unbacked_pre = [(c, v) for c, v in pre_eligible if reason_words(v)]
    # 징후 2 — 칸이 다 있는 두 축에서 guard가 바꾼 판정
    loss = [
        (c, v) for c, v in rows
        if c["profile"] == "full" and v["axis"] in GUARD_FIELD_AXES and v["guarded"]
    ]  # fmt: skip
    # 징후 3 — 판정을 내리긴 하는가
    backed = [
        (c, v) for c, v in rows if c["profile"] == "full" and v["axis"] == PROFILE_BACKED_AXIS
    ]
    decisive = [(c, v) for c, v in backed if v["verdict"] in DECISIVE]
    account_full = Counter(
        v["verdict"] or "판정 없음"
        for c, v in rows
        if c["profile"] == "full" and v["axis"] == "account"
    )
    # 징후 5 · 6
    guarded = [(c, v) for c, v in rows if v["guarded"]]
    forced = [(c, v) for c, v in rows if v["forced"]]
    no_context = [(c, v) for c, v in rows if v["no_context"]]
    invalid = sum(len(v["invalid_citations"]) for _, v in rows)
    no_value = [(c, v) for c, v in eligible if NO_VALUE_RE.search(v["reason"] or "")]
    dist_pre = distribution(m["cells"], pre=True)
    measured = bool(total) and not m["stop"]  # 멈춘 실행은 안 돈 셀을 못 쟀다
    return {
        "total": total,
        "missing": missing,
        "out_of_enum": out_enum,
        "off_called": off_called,
        "no_cite": no_cite,
        "bad_label": bad_label,
        "n_bad_labels": n_bad_labels,
        "eligible": eligible,
        "unbacked": unbacked,
        "pre_eligible_n": len(pre_eligible),
        "unbacked_pre": len(unbacked_pre),
        "no_value": no_value,
        "loss": loss,
        "backed_n": len(backed),
        "decisive": decisive,
        "account_full": dict(sorted(account_full.items())),
        "guarded": guarded,
        "forced": forced,
        "no_context": no_context,
        "invalid_labels": invalid,
        "dist_same": None if baseline is None else dist_pre == baseline["distribution"],
        "zones": {
            "jw": zone_jw(len(unbacked), len(eligible), len(m["cell_errors"]))
            if measured
            else "미완",
            "loss": zone_loss(len(loss)) if measured else "미완",
            "decisive": zone_decisive(len(decisive)),
            "run": z4 if total else "미완",
        },
    }


def usage(m: dict, client, cache_hits: int) -> dict:
    """이 실행의 호출 수 · 토큰 · 비용 · 공고×프로필 하나의 시간. 캐시 판정은 토큰을 세지 않는다."""
    new = [v for _, v in _verdict_rows(m["cells"]) if not v["cached"] and not v["no_context"]]
    secs = [c["seconds"] for c in m["cells"]]
    return {
        "calls": client.calls,
        "retries": client.retries,
        "cache_hits": cache_hits,
        "input_tokens": sum(v["input_tokens"] for v in new),
        "output_tokens": sum(v["output_tokens"] for v in new),
        "usd": sum(v["usd"] for v in new),
        "cell_median_s": statistics.median(secs) if secs else 0.0,
        "cell_max_s": max(secs) if secs else 0.0,
    }


def _add(a: dict, b: dict) -> dict:
    """멈춘 실행이 쓴 호출·토큰·비용에 이어 받은 실행의 것을 더한다. 시간은 뒤 실행의 값이다."""
    keys = ("calls", "retries", "cache_hits", "input_tokens", "output_tokens", "usd")
    return {**b, **{k: a[k] + b[k] for k in keys}}


def attach_runs(run: dict, prev: dict | None) -> None:
    """첫 실행(`first_run`)과 같은 명령을 한 번 더 돌린 실행(`second_run`)을 가른다.

    직전 기록이 같은 프롬프트·모델의 첫 실행이 있으면 이번 완주 실행은 호출 수와 상관없이 두 번째
    실행이다 — 캐시 키가 매번 바뀌어 호출이 첫 실행만큼 나와도 새 첫 실행으로 덮지 않는다.
    실행이 멈추거나, 셀 전체가 실패했거나, 판정을 못 낸 하위 질의가 있으면 첫 실행이 아니다.
    그런 실행이 이어지면 비용을 더해 다음 완주 실행의 첫 실행 값으로 쓴다 — 캐시가 일부 찬
    뒤의 비용만 첫 실행으로 적지 않으려는 것이다.
    """
    prev = prev or {}
    same = prev.get("system_sha") == run["system_sha"] and prev.get("model") == run["model"]
    old = prev.get("first_run") if same else None
    cur = run["usage"]
    carried = prev.get("usage_total") if same and prev.get("incomplete") else None
    total = _add(carried, cur) if carried else cur
    incomplete = bool(run["stop"] or run["cell_errors"] or run["symptoms"].get("missing"))
    run["usage_total"], run["incomplete"] = total, incomplete
    if incomplete:
        first, second = old, None
    elif old:
        first, second = old, cur
    else:
        first, second = total, None
    run["first_run"], run["second_run"] = first, second
    base = first or total
    run["symptoms"]["zones"]["cost"] = zone_cost(
        base["calls"], base["usd"], second["calls"] if second else None, incomplete,
        run["symptoms"].get("dist_same") is not False,
    )  # fmt: skip


# ── 리포트 ───────────────────────────────────────────────────────────────


def _one(text: str | None) -> str:
    return " ".join((text or "").split())


def detail(v: dict) -> str:
    """판정 한 개의 이유 · 조건 · 필요한 정보를 한 칸 문장으로."""
    if v["error"]:
        return f"판정 실패: {_one(v['error'])}"
    parts = (
        [(f"모델 이유: {_one(v['reason'])}" if v["guarded"] else _one(v["reason"]))]
        if v["reason"]
        else []
    )
    parts += [f"조건: {_one(x)}" for x in v["conditions"]]
    parts += [f"필요한 정보: {_one(x)}" for x in v["need_info"]]
    return " / ".join(parts) or "—"


def cites(v: dict) -> str:
    return " · ".join(f"{c}({v['titles'][c]})" if c in v["titles"] else c for c in v["citations"])


def summary_line(run: dict) -> str:
    s = run["symptoms"]
    return (
        f"최종 ELIGIBLE {len(s['eligible'])}개 중 프로필에 없는 값을 이유로 든 것"
        f" {len(s['unbacked'])}(guard 전 ELIGIBLE {s['pre_eligible_n']}개 중"
        f" {s['unbacked_pre']}) (공고 {len(run['notices'])}건 × 프로필 {len(run['profiles'])}종,"
        f" 켜진 하위 질의 {s['total']}개)."
    )


def _case(c: dict, v: dict) -> str:
    return f"{c['name']} × {c['profile']} · `{v['axis']}` · {v['verdict']} — {detail(v)}"


def _dist_tables(cells: list[dict]) -> list[str]:
    """프로필별 축 × 판정값. 칸은 guard 전→후이고 같으면 한 숫자다."""
    pre, post = distribution(cells, pre=True), distribution(cells, pre=False)
    out = []
    for pname in PROFILE_NAMES:
        out += [f"### 프로필 `{pname}`", ""]
        rows = []
        for a in axes.AXES:
            b = pre.get(pname, {}).get(a.id, {})
            f = post.get(pname, {}).get(a.id, {})
            rows.append(
                (
                    f"{a.name} (`{a.id}`)",
                    *[
                        str(f.get(x, 0))
                        if b.get(x, 0) == f.get(x, 0)
                        else f"{b.get(x, 0)}→{f.get(x, 0)}"
                        for x in vd.VERDICTS
                    ],
                    sum(f.values()),
                )
            )
        out += _table(["축", *vd.VERDICTS, "합"], rows) + [""]
    return out


def _sample_sections(run: dict) -> list[str]:
    out = []
    for c in run["cells"]:
        out += [
            f"### {c['name']} (`{c['notice']}`) × `{c['profile']}`",
            "",
            f"공고일 {c['as_of']} · 켜진 축 {' · '.join(c['on'])}",
            "",
        ]
        out += _table(
            ["축", "하위 질의", "판정", "이유 · 조건 · 필요한 정보", "인용", "기각된 인용"],
            [
                (
                    v["axis_name"],
                    v["query"],
                    (v["verdict"] or "—")
                    + (" (인용 기각으로 코드가 바꿈)" if v["forced"] else "")
                    + (" (guard가 바꿈 — 모델 판정 ELIGIBLE)" if v["guarded"] else ""),
                    detail(v),
                    cites(v) or "없음",
                    ", ".join(v["invalid_citations"]) or "—",
                )
                for v in c["verdicts"]
            ],
        )
        out.append("")
    return out


def _guardrail_rows(rows: list) -> list[tuple]:
    return [
        (
            f"{c['name']} × {c['profile']}",
            f"`{v['axis']}`",
            v["original_verdict"] or v["verdict"],
            v["verdict"],
            ", ".join(v["invalid_citations"]) or "—",
        )
        for c, v in rows
    ]


def _usage_text(u: dict) -> str:
    return (
        f"호출 {u['calls']} (재시도 {u['retries']}) · 캐시 {u['cache_hits']}"
        f" · 입력 {u['input_tokens']:,} · 출력 {u['output_tokens']:,} 토큰 · ${u['usd']:.4f}"
        f" · 공고×프로필 하나 중앙값 {u['cell_median_s']:.1f}초 · 최댓값 {u['cell_max_s']:.1f}초"
    )


def _guard_rows(rows: list) -> list[tuple]:
    return [
        (
            f"{c['name']} × {c['profile']}",
            f"`{v['axis']}`",
            v["query"],
            _one(v["reason"]) or "—",
            " · ".join(v["need_info"]),
        )
        for c, v in rows
    ]


def _guard_by_cell(guarded: list) -> list[tuple]:
    n = Counter((c["profile"], v["axis"]) for c, v in guarded)
    return [
        (
            f"`{p}`",
            *[n.get((p, a.id), 0) for a in axes.AXES],
            sum(k for (q, _), k in n.items() if q == p),
        )
        for p in PROFILE_NAMES
    ]


def _counts(d: dict) -> str:
    return " · ".join(f"{k} {n}" for k, n in d.items()) or "없음"


def _eligible_rows(rows: list) -> list[tuple]:
    return [
        (
            f"{c['name']} × {c['profile']}",
            f"`{v['axis']}`",
            v["query"],
            _one(v["reason"]) or "—",
            " · ".join(reason_words(v)) or "—",
            "✓" if NO_VALUE_RE.search(v["reason"] or "") else "—",
        )
        for c, v in rows
    ]


def render(run: dict, baseline: dict) -> str:
    s, z = run["symptoms"], run["symptoms"]["zones"]
    first, second = run["first_run"], run["second_run"]
    lines = [
        summary_line(run),
        "",
        "# #80 축별 판정 — 프로필에 없는 이유로 ELIGIBLE을 내지 않는다",
        "",
    ]
    lines += [
        f"실행 {run['run_at']} · 모델 `{run['model']}` · 프롬프트 {run['system_sha']}"
        f" (PR #13 {baseline['system_sha']}) · 공고 {len(run['notices'])}건"
        f" × 프로필 {len(run['profiles'])}종",
        "",
    ]
    if run["stop"]:
        kind = "비용 상한에서 멈춤" if run["stop"][0] == "budget" else "인증·쿼터 오류로 멈춤"
        lines += [f"**{kind}** — {run['stop'][1]}", ""]
    same = s["dist_same"]
    vacuous = not s["eligible"] and not run["cell_errors"] and not run["stop"]
    lines += ["## 1. 실패 징후 측정값", ""]
    lines += _table(
        ["지표", "측정값", "구간"],
        [
            (
                "1. 프로필에 없는 값을 이유로 든 ELIGIBLE (jw 기준, 세 프로필 전부의 최종 판정,"
                f" 이유에 {' '.join(f'`{w}`' for w in REASON_WORDS)} 중 하나)",
                f"A {len(s['unbacked'])} (guard 전 ELIGIBLE {s['pre_eligible_n']}개 중"
                f" {s['unbacked_pre']}; PR #13 최종 {baseline['eligible_final_words']}, guard 전"
                f" {baseline['eligible_pre_words']}/{baseline['eligible_pre']})"
                f" · B {len(s['eligible'])} (PR #13 {baseline['eligible_final']})"
                f" · 판정을 못 낸 (공고, 프로필) {len(run['cell_errors'])}"
                + (" · 최종 ELIGIBLE이 없어 A 0은 공허하게 참이다" if vacuous else ""),
                z["jw"],
            ),
            (
                "2. guard가 정상 판정을 지웠나 (`full.json`의 `homeless`·`householder`)",
                f"{len(s['loss'])}개",
                z["loss"],
            ),
            (
                "3. 판정을 내리긴 하는가 (`full.json`의 `homeless`,"
                " ELIGIBLE·INELIGIBLE·CONDITIONAL)",
                f"{len(s['decisive'])}/{s['backed_n']} (PR #13 {baseline['decisive_homeless']}"
                f"/{baseline['decisive_homeless_n']})"
                f" · `full.json` `account` 판정값 {_counts(s['account_full'])}"
                f" (PR #13 guard 전 {_counts(baseline['account_full'])})",
                z["decisive"],
            ),
            (
                "4. 켜진 축만 판정하고 판정값이 5개 중 하나이고 남은 인용이 실제로 있다"
                " (PR #12 징후 1)",
                f"판정 없음 {len(s['missing'])} · 5값 밖 {len(s['out_of_enum'])}"
                f" · 꺼진 축 호출 {len(s['off_called'])} · 인용 0개인 판정 {len(s['no_cite'])}"
                f" · DB에 없는 라벨 {s['n_bad_labels']}"
                f" · 판정을 못 낸 (공고, 프로필) {len(run['cell_errors'])}"
                f" (켜진 하위 질의 {s['total']}개)",
                z["run"],
            ),
            (
                "5. 같은 응답을 읽었나 (첫 실행 호출 0 · 두 번째 실행 호출 0 ·"
                " guard 전 분포가 PR #13과 칸마다 같다)",
                (
                    f"첫 실행 {_usage_text(first)}"
                    if first
                    else "첫 실행 기록 없음(멈췄거나 판정을 못 낸 실행)"
                )
                + (
                    f" · 두 번째 실행 호출 {second['calls']}"
                    if second
                    else " · 두 번째 실행 아직 안 잼"
                )
                + " · guard 전 분포 "
                + ("PR #13과 칸마다 같다" if same else "PR #13과 다르다 — 3절에서 칸을 본다"),
                z["cost"],
            ),
            (
                "6. 값만 적는 것 (구간 없음)",
                f"guard가 바꾼 판정 {len(s['guarded'])}/{s['total']}"
                f" (PR #13 {baseline['guarded']}/{baseline['total']}; 프로필 × 축은 3절 끝 표)"
                f" · 인용 기각으로 코드가 바꾼 것 {len(s['forced'])}/{s['total']}"
                f" (PR #13 {baseline['forced']}/{baseline['total']})"
                f" · 최종 ELIGIBLE 중 값이 없는 것을 근거로 든 이유 {len(s['no_value'])}"
                f" (PR #13 {baseline['no_value']}; 정규식 `{NO_VALUE_RE.pattern}`)",
                "—",
            ),
        ],
    )
    lines += ["", "구간 기준과 경계는 plan §실패 징후와 같다.", "", "### 읽는 법", ""]
    lines += _bullets(
        [
            "징후 1은 `verdict.py`의 guard 표를 읽지 않는다. 최종 `ELIGIBLE`의 이유 문장에서"
            " 측정 코드의 단어 목록을 세므로 표가 틀려도 같이 틀리지 않는다."
            " 목록은 #77 프로필에 칸이 없는 사실(예치금·납입·거주·소득·자산·당첨)에서 정했고"
            " 이유 문장을 보고 고르지 않았다. 처음 보는 표현은 놓칠 수 있어"
            " 2절에 최종 `ELIGIBLE` 이유를 전부 싣는다",
            "guard 전은 인용 대조까지 마친 LLM 판정(캐시 응답 그대로)이고 guard 후는 최종 판정이다."
            " `account`의 `ELIGIBLE`은 표 정의상 최종에 남을 수 없고 guard 전 수로 본다",
            "꺼진 축 호출은 `notices`·`notice_models`를 SQL로 직접 읽어 따로 계산한 켜짐 목록"
            "(#79 `independent_on`)에 없는 축의 판정 수다. `axes.plan`과 같은 설계를"
            " 옮겨 적었으므로 같이 틀릴 수 있다",
            "DB에 없는 라벨은 측정 코드가 `verdict.py`의 대조 함수를 부르지 않고"
            " `chunks`를 SQL로 다시 센 값이다. 조문은 공고의 법령 버전(MST) 행만 본다",
            "인용이 판정 내용을 실제로 뒷받침하는지는 자동으로 재지 않는다."
            " 5절 표본을 사람이 읽는다",
            "`strict` schema가 5값 밖 응답을 막으므로 파싱에 실패한 응답은 「판정 없음」에 센다",
            "판정이 맞았는지는 정답이 없어 이번에 안 잰다(골든셋 #75)",
            "PR #13 값은 `runs/80/pr13_baseline.json`이고 출처는 " + baseline["source"],
            "처리 시간은 값만 적는다(baseline 없음). 호출이 0이면 캐시와 SQL을 읽은 시간이라"
            " LLM을 부른 실행과 비교할 수 없다: " + _usage_text(first or run["usage"]),
        ]
    )
    lines += ["", f"## 2. 최종 ELIGIBLE 전부 ({len(s['eligible'])}개)", ""]
    lines += (
        _table(
            ["공고 × 프로필", "축", "하위 질의", "이유 원문", "걸린 단어", "값 없음 근거"],
            _eligible_rows(s["eligible"]),
        )
        if s["eligible"]
        else ["최종 ELIGIBLE이 없다."]
    )
    lines += ["", "## 3. 판정값 분포 — 프로필 × 축 (칸은 guard 전→후)", ""]
    lines += _dist_tables(run["cells"])
    lines += ["### guard가 바꾼 판정 수 — 프로필 × 축", ""]
    lines += _table(
        ["프로필", *[a.name for a in axes.AXES], "합"], _guard_by_cell(s["guarded"])
    ) + [""]
    lines += [f"## 4. guard가 바꾼 판정 전부 ({len(s['guarded'])}개)", ""]
    lines += (
        _table(
            ["공고 × 프로필", "축", "하위 질의", "모델이 쓴 이유 원문", "guard가 넣은 필요한 정보"],
            _guard_rows(s["guarded"]),
        )
        if s["guarded"]
        else ["guard가 바꾼 판정이 없다."]
    )
    forced = s["forced"]
    lines += [
        "",
        f"인용 guardrail이 바꾼 판정은 {len(forced)}개, 근거 0개로 호출하지 않은 것은"
        f" {len(s['no_context'])}개, 기각된 인용 라벨은 {s['invalid_labels']}개다.",
        "",
    ]
    if forced:
        lines += _table(
            ["공고 × 프로필", "축", "모델이 낸 판정", "최종 판정", "기각된 라벨"],
            _guardrail_rows(forced[: SHOW * 3]),
        ) + [""]
    lines += ["## 5. 표본 — 공고 6건 × 프로필 3종 전부", ""] + _sample_sections(run)
    lines += ["## 6. 어긋난 곳", ""]
    for title, rows in (
        ("판정 없음", s["missing"]),
        ("꺼진 축을 호출한 것", s["off_called"]),
        ("인용 0개인 판정", s["no_cite"]),
        ("프로필에 없는 값을 이유로 든 최종 ELIGIBLE", s["unbacked"]),
        ("guard가 칸이 다 있는 축의 판정을 바꾼 것", s["loss"]),
    ):
        lines += [f"### {title}", ""] + _bullets([_case(c, v) for c, v in rows[:SHOW]]) + [""]
    lines += ["### 판정을 못 낸 (공고, 프로필)", ""]
    lines += _bullets([f"{e['notice']} × {e['profile']}: {e['error']}" for e in run["cell_errors"]])
    return "\n".join(lines) + "\n"


def dump(run: dict) -> str:
    return json.dumps(run, ensure_ascii=False, indent=2) + "\n"


def _read_prev(path: Path) -> dict | None:
    """직전 기록. 없으면 None. 있는데 못 읽으면 ValueError — 덮어쓰면 첫 실행 기록을 잃는다."""
    if not path.exists():
        return None
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"직전 실행 기록을 못 읽었다({path}): {e}") from e
    if not isinstance(prev, dict):
        raise ValueError(f"직전 실행 기록이 객체가 아니다({path})")
    return prev


# ── 실행 ─────────────────────────────────────────────────────────────────


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    embedder=None,
    client=None,
    cache_path: Path | None = None,
    samples_json: Path = SAMPLES_JSON,
    profiles_dir: Path = PROFILES_DIR,
    baseline_json: Path = BASELINE_JSON,
    out_md: Path = OUT_MD,
    out_json: Path = OUT_JSON,
    sleep=time.sleep,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.verdict_report")
    ap.add_argument(
        "--report",
        action="store_true",
        required=True,
        help="공고 6건 × 프로필 3종으로 징후 1~6을 잰다",
    )
    ap.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    ap.add_argument("--model", default=settings.openai_gen_model)
    args = ap.parse_args(argv)
    try:
        notices = sample_notices(samples_json)
        profiles = load_profiles(profiles_dir)
        baseline = load_baseline(baseline_json)
        prev = _read_prev(out_json)  # 호출 비용을 쓰기 전에 읽는다
        check_model(args.model)
        client = RetryingClient(client or make_client(), sleep=sleep)
    except (OSError, KeyError, ValueError, HardApiError) as e:
        print(f"준비 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        if not index_db._table_ready(engine):
            print("chunks 테이블이 없다. 먼저 uv run alembic upgrade head", file=sys.stderr)
            return 2
        cache = GenCache(cache_path or vd.cache_path_for(args.model))
        m = measure(
            engine, embedder or Embedder(settings.openai_embed_model), client, cache, args.model,
            notices, profiles, budget_usd=args.budget_usd,
        )  # fmt: skip
        run = {
            "run_at": now(),
            "model": args.model,
            "system_sha": system_sha(),
            "budget_usd": args.budget_usd,
            "notices": notices,
            "profiles": list(profiles),
            **m,
        }
        run["symptoms"] = symptoms(m, baseline)
        run["usage"] = usage(m, client, sum(v["cached"] for _, v in _verdict_rows(m["cells"])))
        attach_runs(run, prev)
        sym = run["symptoms"]
        run["symptoms"] = {k: _plain(v) for k, v in sym.items()}
        write(out_md, render({**run, "symptoms": sym}, baseline))
        write(out_json, dump(run))
        print(summary_line({**run, "symptoms": sym}))
        print("구간: " + " · ".join(f"{k} {v}" for k, v in {**sym["zones"]}.items()))
        print(f"→ {out_md} · {out_json}")
        if run["stop"]:
            print(f"멈춤({run['stop'][0]}): {run['stop'][1]}", file=sys.stderr)
        bad = [k for k in ("jw", "loss", "run") if sym["zones"][k] == "미완"]
        # 징후 1·2·4 중 하나가 미완이거나 실행이 멈췄으면 리포트를 쓴 뒤 exit 1
        return 1 if run["stop"] or bad else 0
    except SQLAlchemyError as e:
        print(f"DB 오류: {type(e).__name__}: {getattr(e, 'orig', e)}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


def _plain(v):
    """JSON에 쓰려고 (cell, verdict) 쌍 목록은 개수만 남기고 사례 이름으로 줄인다."""
    if isinstance(v, list) and v and isinstance(v[0], tuple):
        return [{"notice": c["notice"], "profile": c["profile"], "axis": x["axis"]} for c, x in v]
    return v


if __name__ == "__main__":
    sys.exit(main())
