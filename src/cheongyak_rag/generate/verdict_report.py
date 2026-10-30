"""#80 실패 징후 1~6을 재고 리포트 `docs/80-axis-verdict.md`·`runs/80/last_run.json`을 쓴다.

python -m cheongyak_rag.generate.verdict_report --report [--budget-usd 3]

`runs/79/last_run.json`의 표본 공고 6건 × `runs/80/profiles/`의 프로필 3종에
`verdict.judge`를 돌린다. 판정은 guard 전(인용 대조까지 마친 LLM 판정)과 후(최종 판정)를
나란히 센다.
구간 이름(통과·다시 잰다·미완)과 경계는 plan §실패 징후의 것이다. 꺼진 축 판정과 없는 인용 라벨은
측정 코드가 SQL로 따로 다시 센다(`independent_on`·`label_exists` — `verdict.py`의 대조
함수를 부르지 않는다). PR #12 값은 `runs/80/pr12_baseline.json`에서 읽는다.
"""

import argparse
import dataclasses
import hashlib
import json
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
BASELINE_JSON = ROOT / "runs/80/pr12_baseline.json"
PROFILE_NAMES = ("full", "partial", "empty")

BUDGET_USD = 3.0
DECISIVE = ("ELIGIBLE", "INELIGIBLE", "CONDITIONAL")  # 정보 부족·근거 없음이 아닌 판정
NO_FIELD_AXES = ("residence", "income_asset", "rewin", "special_type")  # #77 프로필에 칸이 없다
GUARD_FIELD_AXES = ("homeless", "account", "householder")  # 필요한 칸이 #77에 있다
PROFILE_BACKED_AXES = ("homeless", "account")  # 징후 3 — 공고 6건 × 2축 = 12개
DECISIVE_PASS, DECISIVE_RETRY = 10, 6  # 징후 3 — 12개 중
FIRST_USD_MAX = 3.0  # 징후 5
FIRST_CALLS_RETRY = 3  # 징후 5 — 첫 실행 호출이 1~3이면 다시 잰다, 4 이상이면 미완
SECOND_CALLS_RETRY = 3
MISSING_RETRY = 2  # 징후 1 — 판정 없음이 이 개수까지면 다시 잰다
SHOW = 10
TRANSIENT = ("RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError")

# PR #12에서 system 프롬프트로 시도한 것. 이번 PR은 프롬프트를 고치지 않는다(통과 기준 6)
PROMPT_NOTES: list[str] = [
    "첫 측정(프롬프트 8f4b18cc): 징후 2는 10개, 징후 3은 24개로 둘 다 미완이었다."
    " ELIGIBLE이면서 이유가 빈 판정이 많아 표본을 읽을 수 없었다",
    "고침 1(b9ccf0a6): `reason`을 모든 판정에 한 문장으로 쓰게 하고, 값이 있는 프로필"
    " 칸을 직접 대조할 때만 ELIGIBLE·INELIGIBLE을 쓰게 했다. 징후 2는 5개, 징후 3은"
    " 18개였다",
    "고침 2(5ea17eff): 판정 절차 4단계와 재당첨·거주 예시를 넣었다. 징후 2는 6개, 징후"
    " 3은 15개였다",
    "고침 3(92f338a4, PR #12 리포트의 값): ELIGIBLE을 「어긋나는 값이 없다」만으로는 못 쓰게"
    " 정의했다. 징후 2는 7개, 징후 3은 18개였다",
    "네 번 사이 값이 징후 2는 5~10개, 징후 3은 15~24개에서 오르내렸고 방향이 일정하지"
    " 않아 프롬프트 고치기를 여기서 멈췄다. 남은 문제는 모델이 이유에 「프로필에서"
    " 확인된다」고 쓰면서 프로필에 없는 값을 지어내는 것이다(예: 프로필에 거주지역 칸이"
    " 없는데 「프로필의 공급지역이 경기로 확인되어」)",
    "칸이 없는 축 18개 중 INELIGIBLE 5개는 프로필에 실제 있는 값에서 나왔다. 미혼 자녀"
    " 수가 1명이라 다자녀(미성년 자녀 2명 이상)를 못 채우고, 혼인신고일이 2012-05-20이라"
    " 신혼부부(혼인 7년 이내)를 못 채운다. 징후 3은 칸이 없는 축의 충족·미충족을 모두"
    " 세므로 이 5개도 센다. 나머지 13개는 ELIGIBLE이고 이유가 요건 내용만 풀어 썼거나 없는"
    " 값을 있는 것처럼 썼다",
    "측정에 쓴 비용은 네 번 합쳐 $3.63이다($0.8665 + $0.9151 + $0.9216 + $0.9313)."
    " 비용 상한 $3은 실행 하나에 건다",
    "모델 비교(`gpt-5.6-sol` 등)와 프롬프트 재측정은 #143이, 모자란 값을 질문으로 받는 일은"
    " #82가 맡는다",
]


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


def zone_jw(a: int, b: int, missing: int, cell_errors: int) -> str:
    """징후 1 — A·B가 0이고 판정 없음도 0이면 통과, 판정 없음 1~2개면 다시 잰다.

    A 1 이상 · B 1 이상 · 판정 없음 3개 이상이면 미완이다.
    셀 전체가 실패한 것은 못 잰 것이라 미완이다.
    """
    if a or b or cell_errors or missing > MISSING_RETRY:
        return "미완"
    return "통과" if missing == 0 else "다시 잰다"


def zone_loss(n: int) -> str:
    """징후 2 — guard가 칸이 다 있는 축의 판정을 바꿨으면 표나 칸 읽기 코드가 틀린 것이다."""
    return "통과" if n == 0 else "미완"


def zone_decisive(n: int) -> str:
    return "통과" if n >= DECISIVE_PASS else "다시 잰다" if n >= DECISIVE_RETRY else "미완"


def zone_cost(
    first_calls: int, first_usd: float, second_calls: int | None, stopped: bool,
    dist_same: bool = True,
) -> str:  # fmt: skip
    """징후 5 — 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 PR #12와 칸마다 같다."""
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
    """PR #12 측정값. 없거나 못 읽으면 예외 — baseline 없이 재면 같은 응답을 읽었는지 모른다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = (
        "source", "system_sha", "total", "distribution", "eligible_empty", "eligible_full_nofield",
        "decisive_full", "decisive_full_n", "forced", "ineligible_full_nofield",
        "eligible_partial_nofield",
    )  # fmt: skip
    for key in keys:  # render가 쓰는 키 전부
        data[key]  # noqa: B018 — 없는 키는 KeyError로 준비 실패가 된다
    return data


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
    """징후 1~6의 값과 구간. `m`은 `measure`의 결과, `baseline`은 PR #12 측정값이다."""
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

    # 징후 1 — 빈 프로필의 ELIGIBLE(A)과 꽉 찬 프로필에서 칸 없는 4개 축의 ELIGIBLE(B)
    empty = [(c, v) for c, v in rows if c["profile"] == "empty" and v["verdict"] == "ELIGIBLE"]
    empty_pre = [(c, v) for c, v in rows if c["profile"] == "empty" and pre_guard(v) == "ELIGIBLE"]
    nofield = [
        (c, v) for c, v in rows
        if c["profile"] == "full" and v["axis"] in NO_FIELD_AXES and v["verdict"] == "ELIGIBLE"
    ]  # fmt: skip
    nofield_pre = [
        (c, v) for c, v in rows
        if c["profile"] == "full" and v["axis"] in NO_FIELD_AXES and pre_guard(v) == "ELIGIBLE"
    ]  # fmt: skip
    ef = ("empty", "full")
    jw_missing = [(c, v) for c, v in missing if c["profile"] in ef]
    jw_errors = [e for e in m["cell_errors"] if e["profile"] in ef]
    # 징후 2 — 칸이 다 있는 세 축에서 guard가 바꾼 판정
    loss = [
        (c, v) for c, v in rows
        if c["profile"] == "full" and v["axis"] in GUARD_FIELD_AXES and v["guarded"]
    ]  # fmt: skip
    # 징후 3 — 판정을 내리긴 하는가
    backed = [
        (c, v) for c, v in rows if c["profile"] == "full" and v["axis"] in PROFILE_BACKED_AXES
    ]
    decisive = [(c, v) for c, v in backed if v["verdict"] in DECISIVE]
    # 징후 5 · 6
    guarded = [(c, v) for c, v in rows if v["guarded"]]
    forced = [(c, v) for c, v in rows if v["forced"]]
    no_context = [(c, v) for c, v in rows if v["no_context"]]
    invalid = sum(len(v["invalid_citations"]) for _, v in rows)
    ineligible_nofield = [
        (c, v) for c, v in rows
        if c["profile"] == "full" and v["axis"] in NO_FIELD_AXES and v["verdict"] == "INELIGIBLE"
    ]  # fmt: skip
    partial_nofield = [
        (c, v) for c, v in rows if c["profile"] == "partial" and v["axis"] in NO_FIELD_AXES
    ]
    dist_pre = distribution(m["cells"], pre=True)
    return {
        "total": total,
        "missing": missing,
        "out_of_enum": out_enum,
        "off_called": off_called,
        "no_cite": no_cite,
        "bad_label": bad_label,
        "n_bad_labels": n_bad_labels,
        "empty_eligible": empty,
        "empty_eligible_pre": len(empty_pre),
        "nofield_eligible": nofield,
        "nofield_eligible_pre": len(nofield_pre),
        "jw_missing": len(jw_missing),
        "jw_cell_errors": len(jw_errors),
        "loss": loss,
        "backed_n": len(backed),
        "decisive": decisive,
        "guarded": guarded,
        "forced": forced,
        "no_context": no_context,
        "invalid_labels": invalid,
        "ineligible_nofield": len(ineligible_nofield),
        "partial_nofield_eligible": sum(v["verdict"] == "ELIGIBLE" for _, v in partial_nofield),
        "partial_nofield_eligible_pre": sum(pre_guard(v) == "ELIGIBLE" for _, v in partial_nofield),
        "dist_same": None if baseline is None else dist_pre == baseline["distribution"],
        "zones": {
            "jw": zone_jw(len(empty), len(nofield), len(jw_missing), len(jw_errors))
            if total and not m["stop"]
            else "미완",  # 멈춘 실행은 안 돈 셀을 못 쟀다
            "loss": zone_loss(len(loss)) if total and not m["stop"] else "미완",
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
        f"빈 프로필 ELIGIBLE {len(s['empty_eligible'])}(guard 전 {s['empty_eligible_pre']}),"
        f" 꽉 찬 프로필 칸 없는 4개 축 ELIGIBLE {len(s['nofield_eligible'])}"
        f"(guard 전 {s['nofield_eligible_pre']})이다"
        f" (공고 {len(run['notices'])}건 × 프로필 {len(run['profiles'])}종,"
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


def _open_questions(run: dict) -> list[str]:
    cells = run["cells"]
    groups = [[v for v in c["verdicts"] if v["axis"] == "special_type"] for c in cells]
    groups = [g for g in groups if len(g) >= 2]
    same = sum(len({pre_guard(v) for v in g}) == 1 for g in groups)  # guard 전: 모델이 낸 판정
    same_post = sum(len({v["verdict"] for v in g}) == 1 for g in groups)
    cond = [(c, v) for c, v in _verdict_rows(cells) if v["verdict"] == "CONDITIONAL"]
    need = [(c, v) for c, v in _verdict_rows(cells) if v["verdict"] == "NEED_INFO"]
    items = [
        "1번 특별공급 유형처럼 하위 질의가 여럿인 축은 이번에도 하위 질의마다 따로 물었다."
        f" 유형이 둘 이상인 (공고, 프로필) {len(groups)}쌍 중"
        f" 모델이 낸 유형 판정이 전부 같게 나온 것은 {same}쌍이다 (guard 뒤에는 {same_post}쌍)",
        "2번 `CONDITIONAL`과 `NEED_INFO`는 system 프롬프트에 「정보를 더 받으면 정해지면"
        " `NEED_INFO`, 정보가 다 있어도 신청자가 행동해야 채우면 `CONDITIONAL`」로 적었다."
        f" 표본에서 `CONDITIONAL` {len(cond)}개 · `NEED_INFO` {len(need)}개가 나왔다."
        " 사례는 아래다",
    ]
    if not cond:
        items.append(
            "CONDITIONAL이 한 건도 안 나와서 이 규칙대로 갈렸는지는 사례로 보지 못했다."
            " 표본의 하위 질의가 공고 이후 행동으로 채우는 요건을 거의 묻지 않았고,"
            " 모자란 값은 전부 NEED_INFO로 갔다"
        )
    items += [f"CONDITIONAL — {_case(c, v)}" for c, v in cond[:3]]
    items += [f"NEED_INFO — {_case(c, v)}" for c, v in need[:3]]
    items.append(
        f"이번 PR은 프롬프트(system_sha {run['system_sha']})를 고치지 않고"
        " LLM 응답 뒤에 코드 guard를 더했다. 모델 비교와 프롬프트 재측정은 #143이 맡는다"
    )
    items.append(
        "아래 징후 번호는 PR #12 plan의 것이다. 그쪽 징후 2는 빈 프로필의 ELIGIBLE·INELIGIBLE 수,"
        " 징후 3은 칸 없는 축의 ELIGIBLE·INELIGIBLE 수였고 이 리포트 1절의 번호와 다르다"
    )
    return items + [f"PR #12에서 프롬프트로 시도한 것: {x}" for x in PROMPT_NOTES]


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


def render(run: dict, baseline: dict) -> str:
    s, z = run["symptoms"], run["symptoms"]["zones"]
    first, second = run["first_run"], run["second_run"]
    lines = [summary_line(run), "", "# #80 축별 판정과 ELIGIBLE guard", ""]
    lines += [
        f"실행 {run['run_at']} · 모델 `{run['model']}` · 프롬프트 {run['system_sha']}"
        f" (PR #12 {baseline['system_sha']}) · 공고 {len(run['notices'])}건"
        f" × 프로필 {len(run['profiles'])}종",
        "",
    ]
    if run["stop"]:
        kind = "비용 상한에서 멈춤" if run["stop"][0] == "budget" else "인증·쿼터 오류로 멈춤"
        lines += [f"**{kind}** — {run['stop'][1]}", ""]
    same = s["dist_same"]
    lines += ["## 1. 실패 징후 측정값", ""]
    lines += _table(
        ["지표", "측정값", "구간"],
        [
            (
                "1. 빈 프로필 ELIGIBLE(A)과 꽉 찬 프로필에서 칸 없는 4개 축의 ELIGIBLE(B)"
                " (jw 기준, guard 후)",
                f"A {len(s['empty_eligible'])} (guard 전 {s['empty_eligible_pre']};"
                f" PR #12 {baseline['eligible_empty']})"
                f" · B {len(s['nofield_eligible'])} (guard 전 {s['nofield_eligible_pre']};"
                f" PR #12 {baseline['eligible_full_nofield']})"
                f" · 판정 없음(`empty`·`full`) {s['jw_missing']}"
                f" · 판정을 못 낸 (공고, 프로필)(`empty`·`full`) {s['jw_cell_errors']}",
                z["jw"],
            ),
            (
                "2. guard가 정상 판정을 지웠나 (`full.json`의 `homeless`·`account`·`householder`)",
                f"{len(s['loss'])}개",
                z["loss"],
            ),
            (
                "3. 판정을 내리긴 하는가 (`full.json`의 `homeless`·`account`,"
                " ELIGIBLE·INELIGIBLE·CONDITIONAL)",
                f"{len(s['decisive'])}/{s['backed_n']} (PR #12 {baseline['decisive_full']}"
                f"/{baseline['decisive_full_n']})",
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
                " guard 전 분포가 PR #12와 칸마다 같다)",
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
                + ("PR #12와 칸마다 같다" if same else "PR #12와 다르다 — 2절에서 칸을 본다"),
                z["cost"],
            ),
            (
                "6. guard가 얼마나 바꿨나 (값만, 구간 없음)",
                f"guard가 바꾼 판정 {len(s['guarded'])}/{s['total']}"
                f" · 인용 기각으로 코드가 바꾼 것 {len(s['forced'])}/{s['total']}"
                f" (PR #12 {baseline['forced']}/{baseline['total']})"
                f" · 꽉 찬 프로필 칸 없는 4개 축 INELIGIBLE {s['ineligible_nofield']}"
                f" (PR #12 {baseline['ineligible_full_nofield']}, guard 대상 아님)"
                f" · `partial.json` 칸 없는 4개 축 ELIGIBLE {s['partial_nofield_eligible']}"
                f" (guard 전 {s['partial_nofield_eligible_pre']};"
                f" PR #12 {baseline['eligible_partial_nofield']})",
                "—",
            ),
        ],
    )
    lines += ["", "구간 기준과 경계는 plan §실패 징후와 같다.", "", "### 읽는 법", ""]
    lines += _bullets(
        [
            "guard 전은 인용 대조까지 마친 LLM 판정(캐시 응답 그대로)이고 guard 후는 최종 판정이다."
            " guard는 축 단위 규칙이라 jw 기준 0은 규칙이 빠짐없이 걸렸다는 확인이다."
            " LLM이 지어내지 않게 됐다는 뜻이 아니고, 지어낸 값은 guard 전 수로 본다",
            "꺼진 축 호출은 `notices`·`notice_models`를 SQL로 직접 읽어 따로 계산한 켜짐 목록"
            "(#79 `independent_on`)에 없는 축의 판정 수다. `axes.plan`과 같은 설계를"
            " 옮겨 적었으므로 같이 틀릴 수 있다",
            "DB에 없는 라벨은 측정 코드가 `verdict.py`의 대조 함수를 부르지 않고"
            " `chunks`를 SQL로 다시 센 값이다. 조문은 공고의 법령 버전(MST) 행만 본다",
            "인용이 판정 내용을 실제로 뒷받침하는지는 자동으로 재지 않는다."
            " 4절 표본을 사람이 읽는다",
            "`strict` schema가 5값 밖 응답을 막으므로 파싱에 실패한 응답은 「판정 없음」에 센다",
            "판정이 맞았는지는 정답이 없어 이번에 안 잰다(골든셋 #75)",
            "PR #12 값은 `runs/80/pr12_baseline.json`이고 출처는 " + baseline["source"],
            "처리 시간은 값만 적는다(baseline 없음): " + _usage_text(first or run["usage"]),
        ]
    )
    lines += ["", "## 2. 판정값 분포 — 프로필 × 축 (칸은 guard 전→후)", ""]
    lines += _dist_tables(run["cells"])
    lines += ["### guard가 바꾼 판정 수 — 프로필 × 축", ""]
    lines += _table(
        ["프로필", *[a.name for a in axes.AXES], "합"], _guard_by_cell(s["guarded"])
    ) + [""]
    lines += [f"## 3. guard가 바꾼 판정 전부 ({len(s['guarded'])}개)", ""]
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
    lines += ["## 4. 표본 — 공고 6건 × 프로필 3종 전부", ""] + _sample_sections(run)
    lines += ["## 5. 열린 질문과 PR #12의 프롬프트 기록 (설계 §열린 질문 1·2)", ""]
    lines += _bullets(_open_questions(run))
    lines += ["", "## 6. 어긋난 곳", ""]
    for title, rows in (
        ("판정 없음", s["missing"]),
        ("꺼진 축을 호출한 것", s["off_called"]),
        ("인용 0개인 판정", s["no_cite"]),
        ("guard 후에도 남은 빈 프로필 ELIGIBLE", s["empty_eligible"]),
        ("guard 후에도 남은 `full.json` 칸 없는 축 ELIGIBLE", s["nofield_eligible"]),
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
