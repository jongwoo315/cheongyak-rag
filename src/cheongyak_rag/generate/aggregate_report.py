"""#81 실패 징후 1~4를 재고 리포트 `docs/81-answer.md`·`runs/81/last_run.json`을 쓴다.

python -m cheongyak_rag.generate.aggregate_report --report [--budget-usd 3]

`runs/79/last_run.json`의 표본 공고 6건 × `runs/80/profiles/`의 프로필 3종에 `verdict.judge`를 돌려
(system 프롬프트를 안 바꿔 #80 캐시를 읽는다) 응답을 만든다.
B(경로별 판정)·C(검색 밖 언급)·D(근거 원문)는 `aggregate.py`의 함수를 부르지 않고 다시 계산한다
(`expected_routes`·`indep_outside`·`reread_text`). 우선순위 목록은 이 모듈의 `ORDER` 하나이고
규칙 일치 테스트(`rule_mismatches`)와 B 재계산이 둘 다 이것에서 기대값을 낸다.
"""

import argparse
import dataclasses
import hashlib
import itertools
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag.config import settings
from cheongyak_rag.generate import aggregate as agg
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate import verdict_report as vr
from cheongyak_rag.generate.answer import GenCache, HardApiError, check_model, make_client
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.ingest.notice_report import _bullets, _table
from cheongyak_rag.retrieval import axes, index_db
from cheongyak_rag.retrieval.axes_report import independent_on
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import now, write

ROOT = Path(__file__).resolve().parents[3]
OUT_MD = ROOT / "docs/81-answer.md"
OUT_JSON = ROOT / "runs/81/last_run.json"
PROFILES_DIR = ROOT / "runs/80/profiles"
SAMPLES_JSON = ROOT / "runs/79/last_run.json"
BASELINE_JSON = ROOT / "runs/80/last_run.json"  # PR #14 측정
EXAMPLE = ("2026000103", "full")  # 응답 한 개 전문: 더샵 분당하이스트 × 꽉 찬 프로필
BUDGET_USD = 3.0
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0"
SHOW = 200  # 검색 밖 언급 표에 싣는 최대 행. 이보다 많으면 JSON에서 본다

# 우선순위. 기대값의 유일한 출처다 (설계 §B8 · 바탕 설계 §168)
ORDER = ("INELIGIBLE", "UNVERIFIABLE", "NEED_INFO", "CONDITIONAL", "ELIGIBLE")
GENERAL = ("homeless", "account", "residence", "rewin", "householder")  # 일반 축 5
SLOTS = (*GENERAL, "income_asset", "special_type")  # 규칙 일치 테스트의 7칸
STATES = (None, *ORDER)  # 꺼짐 + 판정값 5개
COMBO_TYPE = "다자녀가구"


# ── 규칙 일치 (징후 1 A) ──────────────────────────────────────────────────


def _best(values: list[str]) -> str | None:
    """순번 최솟값. 값이 없으면 None."""
    return ORDER[min(ORDER.index(x) for x in values)] if values else None


def rule_mismatches() -> tuple[int, int]:
    """7칸 × 6가지 상태 279,936개 조합을 `aggregate.aggregate`에 넣어 (조합 수, 기대값과 다른 수).

    일반공급·전역 판정은 켜진 일반 축의 값, 특별공급 유형 경로는 거기에 소득·자산 축과 유형 질의를
    더한 값이어야 한다. 유형 질의가 꺼진 조합에는 특별공급 경로가 없어야 한다.
    """
    # 객체는 (칸, 상태)마다 하나씩 만들어 돌려 쓴다 — 조합마다 새로 만들면 느리다
    query = axes.Q_SPECIAL.format(type=COMBO_TYPE)
    cells = {
        (s, st): vd.Verdict(s, s, query if s == "special_type" else s, verdict=st)
        for s in SLOTS
        for st in ORDER
    }
    plans: dict[frozenset, list] = {}
    total = wrong = 0
    for combo in itertools.product(STATES, repeat=len(SLOTS)):
        total += 1
        on = {s for s, st in zip(SLOTS, combo, strict=True) if st is not None}
        key = frozenset(on)
        if key not in plans:
            plans[key] = [axes.AxisPlan(a.id, a.name, a.id in on, "") for a in axes.AXES]
        picked = [(s, st) for s, st in zip(SLOTS, combo, strict=True) if st is not None]
        got = agg.aggregate(plans[key], [cells[p] for p in picked])
        general = [st for s, st in picked if s in GENERAL]
        income = [st for s, st in picked if s == "income_asset"]
        typed = [st for s, st in picked if s == "special_type"]
        want = {COMBO_TYPE: _best(general + income + typed)} if typed else {}
        if (
            got.general.verdict != _best(general)
            or got.verdict != _best(general)
            or {r.key: r.verdict for r in got.special} != want
        ):
            wrong += 1
    return total, wrong


# ── 다시 계산 (징후 1 B · 징후 2 C · D) ───────────────────────────────────

_TYPE_RE = re.compile(r"^(.+?) 특별공급의")
_REF_RE = re.compile(r"제(\d+)조(?:의(\d+))?|(?<![A-Za-z0-9])Q(\d+)")
_GENERAL_IDS = {"homeless", "account", "residence", "rewin", "householder"}


def expected_routes(on_axes: list[str], verdicts: list[dict]) -> dict[str, str | None]:
    """경로 키 → 기대 판정. 켜진 축은 SQL로 따로 읽은 목록(`on_sql`)이고 판정은 dict다."""
    base, income, typed = [], [], {}
    for v in verdicts:
        if v["axis"] not in on_axes:
            continue
        value = v["verdict"] or "UNVERIFIABLE"
        if v["axis"] in _GENERAL_IDS:
            base.append(value)
        elif v["axis"] == "income_asset":
            income.append(value)
        elif v["axis"] == "special_type":
            m = _TYPE_RE.match(v["query"])
            typed.setdefault(m.group(1) if m else "유형 미상", []).append(value)
    return {"general": _best(base)} | {t: _best(base + income + xs) for t, xs in typed.items()}


def mentions(reason: str) -> list[str]:
    """이유 문장의 조·FAQ 번호 언급 전부(같은 번호도 나온 횟수만큼)."""
    out = []
    for m in _REF_RE.finditer(reason or ""):
        if m.group(3):
            out.append(f"Q{m.group(3)}")
        else:
            out.append(f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else ""))
    return out


def indep_outside(reason: str, context_labels: list[str]) -> list[str]:
    """`mentions` 중 문맥에 없는 번호, 처음 나온 순서, 같은 번호는 한 번."""
    return [m for m in dict.fromkeys(mentions(reason)) if m not in set(context_labels)]


def reread_text(engine: Engine, mst: str | None, label: str) -> str | None:
    """`chunks`에서 라벨 하나의 원문을 직접 읽는다. 조문은 공고의 MST 행만, FAQ는 `faq` 행."""
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT text FROM chunks WHERE label = :l"
                " AND ((source = 'law' AND law_mst = :m) OR source = 'faq') LIMIT 1"
            ),
            {"l": label, "m": mst},
        ).scalar()


def http_status(url: str) -> int | str:
    """링크를 한 번 요청해 받은 HTTP 상태. 쿠키를 유지하고 리다이렉트를 따라간다.

    응답을 못 받으면 예외 이름을 돌려준다.
    """
    try:
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as client:
            with client.stream("GET", url) as r:
                return r.status_code
    except httpx.HTTPError as e:
        return type(e).__name__


# ── 측정 ─────────────────────────────────────────────────────────────────


def measure(
    engine: Engine, embedder, client, cache, model: str, notices: list[str],
    profiles: dict, *, budget_usd: float,
) -> dict:  # fmt: skip
    """공고 × 프로필마다 판정 → 응답. 예산을 넘기거나 인증 오류면 거기서 멈춘다."""
    sql_on = independent_on(engine)
    search_cache: axes.Cache = {}
    cells, cell_errors, spent, stop = [], [], 0.0, None
    answers: dict[tuple[str, str], agg.Answer] = {}
    for hmn in notices:
        for pname, profile in profiles.items():
            t0 = time.perf_counter()
            try:
                notice, plans, verdicts = vd.judge(
                    engine, embedder, client, model, hmn, profile, cache=cache,
                    search_cache=search_cache,
                )  # fmt: skip
                spent += sum(v.usd for v in verdicts if not v.cached)
                answer = agg.build_answer(engine, notice, plans, verdicts, profile)
            except HardApiError as e:
                stop = ("hard", f"{hmn} × {pname}: {e}")
                break
            except Exception as e:  # noqa: BLE001 — 셀 하나의 실패로 보고서 전체를 잃지 않는다
                cell_errors.append(
                    {"notice": hmn, "profile": pname, "error": f"{type(e).__name__}: {e}"}
                )
                continue
            answers[(hmn, pname)] = answer
            cells.append(
                {
                    "notice": hmn,
                    "name": notice.name,
                    "profile": pname,
                    "as_of": notice.as_of.isoformat(),
                    "mst": notice.facts.law_mst,
                    "on": [p.id for p in plans if p.on],
                    "on_sql": sql_on.get((notice.house_manage_no, notice.pblanc_no), []),
                    "seconds": time.perf_counter() - t0,
                    "verdicts": [dataclasses.asdict(v) for v in verdicts],
                    "answer": dataclasses.asdict(answer),
                }
            )
            if spent > budget_usd:
                stop = ("budget", f"{hmn} × {pname}: 비용 상한 ${budget_usd} 초과 (${spent:.4f})")
                break
        if stop:
            break
    return {"cells": cells, "cell_errors": cell_errors, "stop": stop, "answers": answers}


def route_diffs(cells: list[dict]) -> tuple[list[dict], int]:
    """징후 1 B — (측정 코드와 다른 경로 판정, 경로 판정 총수).

    총수는 기대 경로와 응답 경로의 합집합이다.
    """
    diffs, total = [], 0
    for c in cells:
        a = c["answer"]
        want = expected_routes(c["on_sql"], c["verdicts"])
        got = {"general": a["general"]["verdict"]} | {r["key"]: r["verdict"] for r in a["special"]}
        for key in dict.fromkeys([*want, *got]):
            total += 1
            bad = key not in want or key not in got or want[key] != got[key]
            if key == "general" and a["verdict"] != a["general"]["verdict"]:
                bad = True  # 전역 판정은 일반공급 판정이어야 한다
            if bad:
                diffs.append({"cell": c, "key": key, "want": want.get(key), "got": got.get(key)})
    return diffs, total


def outside_rows(cells: list[dict]) -> list[dict]:
    """응답의 하위 질의마다 (응답이 붙인 검색 밖 언급, 측정 코드가 센 값)."""
    out = []
    for c in cells:
        for v, item in zip(c["verdicts"], c["answer"]["checklist"], strict=True):
            out.append(
                {"cell": c, "v": v, "got": item["outside"],
                 "want": indep_outside(v["reason"], v["context_labels"])}
            )  # fmt: skip
    return out


def evidence_diffs(engine: Engine, cells: list[dict], answers: dict) -> tuple[list[dict], int]:
    """징후 2 D — (문맥에 없거나 chunks 원문과 다른 근거, 실린 근거 총수).

    응답에 실린 원문은 객체에서 읽는다(JSON에서는 줄어든다).
    """
    diffs, total = [], 0
    reread: dict[tuple, str | None] = {}
    for c in cells:
        answer = answers[(c["notice"], c["profile"])]
        for v, item in zip(c["verdicts"], answer.checklist, strict=True):
            for e in item.citations:
                total += 1
                key = (c["mst"], e.label)
                if key not in reread:
                    reread[key] = reread_text(engine, c["mst"], e.label)
                why = (
                    "문맥에 없다" if e.label not in v["context_labels"]
                    else "chunks에 없다" if reread[key] is None
                    else "원문이 다르다" if reread[key] != e.text
                    else None
                )  # fmt: skip
                if why:
                    diffs.append({"cell": c, "query": v["query"], "label": e.label, "why": why})
    return diffs, total


def link_check(cells: list[dict], fetch_status) -> dict:
    """응답에 실린 링크 형식마다 한 번 요청한 HTTP 상태. 형식 → {url, status}."""
    sample: dict[str, str] = {}
    for c in cells:
        for item in c["answer"]["checklist"]:
            for e in item["citations"]:
                if e["url"]:
                    sample.setdefault(e["kind"], e["url"])
    return {k: {"url": u, "status": fetch_status(u)} for k, u in sample.items()}


def zone_rule(a: int, b: int, incomplete: bool) -> str:
    """징후 1 — A와 B가 0이면 통과. 규칙이 결정론적이라 다시 잰다 구간이 없다."""
    return "미완" if a or b or incomplete else "통과"


def zone_outside(c: int, d: int, e: int, incomplete: bool) -> str:
    """징후 2 — C 0 · D 0 · E 1 이상이면 통과, E 0이면 표시가 한 번도 안 붙어 다시 잰다."""
    if c or d or incomplete:
        return "미완"
    return "통과" if e >= 1 else "다시 잰다"


def zone_links(links: dict) -> str:
    return "통과" if all(v["status"] == 200 for v in links.values()) else "미완"


def counts(cells: list[dict]) -> dict:
    """같이 적는 값: 전역 판정 분포 · 유형별 판정 분포 · 신청 가능한 경로가 있는 쌍 수."""
    answers = [c["answer"] for c in cells]
    return {
        "global": dict(Counter(a["verdict"] or "판정할 축 없음" for a in answers)),
        "special": dict(
            Counter(r["verdict"] or "판정할 축 없음" for a in answers for r in a["special"])
        ),
        "applicable_pairs": sum(bool(a["applicable"]) for a in answers),
        "pairs": len(answers),
    }  # fmt: skip


def symptoms(m: dict, engine: Engine, baseline: dict, fetch_status, combos) -> dict:
    cells = m["cells"]
    total_q = sum(len(c["verdicts"]) for c in cells)
    total_c, wrong_a = combos()
    diffs_b, den_b = route_diffs(cells)
    rows = outside_rows(cells)
    diff_c = [r for r in rows if r["got"] != r["want"]]
    flagged = [r for r in rows if r["got"]]
    diffs_d, den_d = evidence_diffs(engine, cells, m["answers"])
    links = link_check(cells, fetch_status)
    refs = [(x, r["v"]["context_labels"]) for r in rows for x in mentions(r["v"]["reason"])]
    law = [(x, ctx) for x, ctx in refs if x.startswith("제")]
    faq = [(x, ctx) for x, ctx in refs if x.startswith("Q")]
    final_eligible = [r for r in rows if r["v"]["verdict"] == "ELIGIBLE"]
    missing = [r for r in rows if r["v"]["verdict"] is None]
    incomplete = bool(m["stop"] or m["cell_errors"] or not cells or missing)
    dist = vr.distribution(cells, pre=False)
    base_dist = vr.distribution(baseline["cells"], pre=False)
    return {
        "total_queries": total_q,
        "combos": total_c,
        "A": wrong_a,
        "B": len(diffs_b),
        "B_total": den_b,
        "diffs_b": diffs_b,
        "C": len(diff_c),
        "diffs_c": diff_c,
        "D": len(diffs_d),
        "D_total": den_d,
        "diffs_d": diffs_d,
        "E": len(flagged),
        "flagged": flagged,
        "mention_law": [len(law), sum(x not in ctx for x, ctx in law)],
        "mention_faq": [len(faq), sum(x not in ctx for x, ctx in faq)],
        "eligible_final": len(final_eligible),
        "eligible_flagged": sum(bool(r["got"]) for r in final_eligible),
        "missing": missing,
        "links": links,
        "counts": counts(cells),
        "dist_same": dist == base_dist,
        "zones": {
            "rule": zone_rule(wrong_a, len(diffs_b), incomplete),
            "outside": zone_outside(len(diff_c), len(diffs_d), len(flagged), incomplete),
            "links": zone_links(links),
        },
    }


def slim(cell: dict) -> dict:
    """JSON에 쓰려고 근거 원문을 길이와 해시로 줄인다. 원문은 `chunks`에 있다."""
    out = json.loads(json.dumps(cell, ensure_ascii=False, default=str))
    for item in out["answer"]["checklist"]:
        for e in item["citations"]:
            e["text_len"] = len(e["text"])
            e["text_sha256"] = hashlib.sha256(e["text"].encode("utf-8")).hexdigest()[:12]
            del e["text"]
    return out


# ── 리포트 ───────────────────────────────────────────────────────────────


def _one(text: str | None) -> str:
    return " ".join((text or "").split())


def _dist(d: dict) -> str:
    return " · ".join(f"{k} {n}" for k, n in sorted(d.items())) or "없음"


def first_lines(s: dict) -> list[str]:
    zr, zo = s["zones"]["rule"], s["zones"]["outside"]
    return [
        f"징후 1(B8 코드가 규칙대로 합치는가): 규칙 일치 테스트 {s['combos']:,}개 조합 중"
        f" 기대값과 다른 조합 {s['A']}개, 실데이터 경로 판정 {s['B_total']}개 중"
        f" 측정 코드와 다른 것 {s['B']}개다 ({zr}).",
        f"징후 2(검색에 없는 답이 나오는지 확인할 수 있는가): 하위 질의 {s['total_queries']}개 중"
        f" 검색 밖 언급이 측정 코드와 다르게 붙은 것 {s['C']}개, 실린 근거 원문"
        f" {s['D_total']}개 중 어긋난 것 {s['D']}개, 검색 밖 언급이 붙은 하위 질의"
        f" {s['E']}개다 ({zo}).",
    ]


def render(run: dict, baseline: dict) -> str:
    s, z = run["symptoms"], run["symptoms"]["zones"]
    first, second = run["first_run"], run["second_run"]
    c = s["counts"]
    lines = [*first_lines(s), "", "# #81 집계·응답 — 경로별 판정과 검색 밖 언급", ""]
    lines += [
        f"실행 {run['run_at']} · 모델 `{run['model']}` · 프롬프트 {run['system_sha']}"
        f" (PR #14 {baseline['system_sha']}) · 공고 {len(run['notices'])}건"
        f" × 프로필 {len(run['profiles'])}종 = {c['pairs']}쌍",
        "",
    ]
    if run["stop"]:
        kind = "비용 상한에서 멈춤" if run["stop"][0] == "budget" else "인증·쿼터 오류로 멈춤"
        lines += [f"**{kind}** — {run['stop'][1]}", ""]
    vacuous = z["outside"] == "다시 잰다"
    links = (
        " · ".join(f"{k} {v['status']} (`{v['url']}`)" for k, v in s["links"].items())
        or "응답에 링크가 실리지 않았다"
    )
    lines += ["## 1. 실패 징후 측정값", ""]
    lines += _table(
        ["지표", "측정값", "구간"],
        [
            (
                "1. B8 코드가 규칙대로 합치는가 (jw 기준 앞 절)",
                f"A {s['A']}/{s['combos']:,} 조합 · B {s['B']}/{s['B_total']} 경로 판정"
                f" · 판정을 못 낸 (공고, 프로필) {len(run['cell_errors'])}",
                z["rule"],
            ),
            (
                "2. 검색에 없는 답이 나오는지 확인할 수 있는가 (jw 기준 뒤 절)",
                f"C {s['C']}/{s['total_queries']} · D {s['D']}/{s['D_total']} · E {s['E']}"
                + (
                    " · E가 0이라 표시가 한 번도 안 붙었다 — 정규식·라벨 꼴부터 확인한다"
                    if vacuous
                    else ""
                ),
                z["outside"],
            ),
            (
                "3. 같은 응답을 읽었나 (첫 실행 호출 0 · 두 번째 실행 호출 0 ·"
                " 하위 질의 최종 판정 분포가 PR #14와 칸마다 같다)",
                (f"첫 실행 {vr._usage_text(first)}" if first else "첫 실행 기록 없음")
                + (
                    f" · 두 번째 실행 호출 {second['calls']}"
                    if second
                    else " · 두 번째 실행 아직 안 잼"
                )
                + " · 최종 판정 분포 "
                + ("PR #14와 칸마다 같다" if s["dist_same"] else "PR #14와 다르다"),
                z["cost"],
            ),
            ("4. 출처 링크 (실린 형식마다 한 번 요청한 HTTP 상태)", links, z["links"]),
        ],
    )
    lines += ["", "구간 기준과 경계는 plan §실패 징후와 같다.", "", "### 같이 적는 값", ""]
    lines += _bullets(
        [
            f"{c['pairs']}쌍의 전역 판정 분포: {_dist(c['global'])}",
            f"특별공급 유형별 판정 분포(경로 {sum(c['special'].values())}개):"
            f" {_dist(c['special'])}",
            "신청 가능한 경로(`ELIGIBLE`·`CONDITIONAL`)가 1개 이상인 쌍:"
            f" {c['applicable_pairs']}/{c['pairs']}",
            f"이유 문장의 조 번호 언급 {s['mention_law'][0]}회 중 검색 밖 {s['mention_law'][1]}회,"
            f" FAQ 번호 언급 {s['mention_faq'][0]}회 중 검색 밖 {s['mention_faq'][1]}회"
            " (같은 번호도 나온 횟수대로 센다. 착수 때 main 세션은 조 번호만 145 중 65로 셌다)",
            f"최종 `ELIGIBLE` {s['eligible_final']}개 중 검색 밖 언급이 붙은 것"
            f" {s['eligible_flagged']}개"
            " (착수 때 8개 중 0)",
            f"검색 밖 언급이 붙은 하위 질의 {s['E']}개 (착수 때 조 번호만 세어 15)",
        ]
    )
    lines += ["", "### 읽는 법", ""]
    lines += _bullets(
        [
            "B는 `aggregate.py`를 부르지 않고 `notices`·`notice_models`를 SQL로 직접 읽은"
            " 켜진 축 목록과"
            " 하위 질의 판정 dict에서 같은 우선순위를 다시 계산한 값이다. 우선순위 목록은"
            " 이 모듈의 `ORDER` 하나이고 규칙 일치 테스트(A)도 같은 목록에서 기대값을 낸다."
            " 측정이 구현과 같은 규칙을 옮겨 쓴 것이므로 둘이 같이 틀릴 수 있다",
            "C는 응답이 붙인 검색 밖 언급과, 측정 코드가 이유 원문의 `제N조`·`제N조의M`·`QN`을"
            " 정규식으로"
            " 따로 뽑아 하위 질의 `context_labels`와 대조한 값이 다른 하위 질의 수다",
            "D는 응답의 근거 원문마다 그 하위 질의 `context_labels`에 있는지와, `chunks`를 SQL로"
            " 다시 읽은"
            " `text`와 글자가 같은지를 본 값이다",
            "검색 밖 언급은 「LLM이 검색에 없는 조·FAQ를 이유에 끌어왔다」는 사실까지다."
            " 그 번호가 맞는 근거인지는 이 측정이 말하지 않는다."
            " 이번에는 표시만 하고 판정은 바꾸지 않는다",
            "PR #14 값은 `runs/80/last_run.json`이고 지금 기록과 프롬프트 해시가 "
            + ("같다" if run["system_sha"] == baseline["system_sha"] else "다르다"),
            "처리 시간은 값만 적는다(baseline 없음): " + vr._usage_text(first or run["usage"]),
        ]
    )
    lines += ["", f"## 2. {c['pairs']}쌍 응답 전부", ""]
    lines += _table(
        ["공고 × 프로필", "전역 판정(일반공급)", "특별공급 유형별 판정", "신청 가능한 경로"],
        [
            (
                f"{x['name']} × {x['profile']}",
                x["answer"]["verdict"] or "판정할 축 없음",
                " · ".join(f"{r['key']} {r['verdict']}" for r in x["answer"]["special"]) or "—",
                " · ".join(r["name"] for r in x["answer"]["applicable"]) or "없음",
            )
            for x in run["cells"]
        ],
    )
    lines += ["", f"## 3. 검색 밖 언급이 붙은 하위 질의 전부 ({s['E']}개)", ""]
    shown = s["flagged"][:SHOW]
    lines += (
        _table(
            ["공고 × 프로필", "축", "하위 질의", "최종 판정", "언급한 검색 밖 번호", "이유 원문"],
            [
                (
                    f"{r['cell']['name']} × {r['cell']['profile']}",
                    f"`{r['v']['axis']}`",
                    r["v"]["query"],
                    r["v"]["verdict"],
                    " · ".join(r["got"]),
                    _one(r["v"]["reason"]),
                )
                for r in shown
            ],
        )
        if shown
        else ["검색 밖 언급이 붙은 하위 질의가 없다."]
    )
    if len(s["flagged"]) > SHOW:
        lines += [
            "",
            f"{len(s['flagged'])}개 중 {SHOW}개만 싣는다. 나머지는 `runs/81/last_run.json`.",
        ]
    lines += ["", "## 4. 응답 한 개 전문 (더샵 분당하이스트 × 꽉 찬 프로필)", ""]
    lines += ["```text", run["example"] or "표본에 없다", "```", ""]
    lines += ["## 5. 표본", ""]
    lines += _bullets(
        [f"공고 {n}" for n in run["notices"]] + [f"프로필 {p}" for p in run["profiles"]]
    )
    lines += ["", "## 6. 어긋난 곳", ""]

    def who(c):
        return f"{c['name']} × {c['profile']}"

    for title, rows in (
        (
            "경로 판정이 측정 코드와 다른 것 (B)",
            [
                f"{who(d['cell'])} · {d['key']}: 측정 {d['want']} / 응답 {d['got']}"
                for d in s["diffs_b"]
            ],
        ),
        (
            "검색 밖 언급이 측정 코드와 다른 하위 질의 (C)",
            [
                f"{who(r['cell'])} · {r['v']['query']}: 응답 {r['got']} / 측정 {r['want']}"
                for r in s["diffs_c"]
            ],
        ),
        (
            "근거 원문이 어긋난 것 (D)",
            [f"{who(d['cell'])} · {d['label']} ({d['why']})" for d in s["diffs_d"]],
        ),
        (
            "판정을 못 낸 (공고, 프로필)",
            [f"{e['notice']} × {e['profile']}: {e['error']}" for e in run["cell_errors"]],
        ),
        (
            "호출이 실패해 판정이 없는 하위 질의 (UNVERIFIABLE로 센다)",
            [f"{who(r['cell'])} · {r['v']['query']}: {r['v']['error']}" for r in s["missing"]],
        ),
    ):
        lines += [f"### {title}", ""] + _bullets(rows[:SHOW]) + [""]
    return "\n".join(lines) + "\n"


def dump(run: dict) -> str:
    return json.dumps(run, ensure_ascii=False, indent=2) + "\n"


def _plain(v):
    """JSON에 쓰려고 사례 dict에 든 셀 전체를 이름만 남긴다."""
    if isinstance(v, list) and v and isinstance(v[0], dict) and ("cell" in v[0] or "v" in v[0]):
        return [
            {"notice": x["cell"]["notice"], "profile": x["cell"]["profile"]}
            | {k: val for k, val in x.items() if k not in ("cell",)}
            for x in v
        ]
    return v


def load_baseline(path: Path) -> dict:
    """PR #14 측정 기록. 없거나 못 읽으면 예외 — 비교 대상 없이 재면 같은 응답을 읽었는지 모른다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("system_sha", "cells"):
        data[key]  # noqa: B018 — 없는 키는 KeyError로 준비 실패가 된다
    return data


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
    fetch_status=http_status,
    combos=rule_mismatches,
    sleep=time.sleep,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.aggregate_report")
    ap.add_argument(
        "--report", action="store_true", required=True,
        help="공고 6건 × 프로필 3종으로 징후 1~4를 잰다",
    )  # fmt: skip
    ap.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    ap.add_argument("--model", default=settings.openai_gen_model)
    args = ap.parse_args(argv)
    try:
        notices = vr.sample_notices(samples_json)
        profiles = vr.load_profiles(profiles_dir)
        baseline = load_baseline(baseline_json)
        prev = vr._read_prev(out_json)  # 호출 비용을 쓰기 전에 읽는다
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
        sym = symptoms(m, engine, baseline, fetch_status, combos)
        example = m["answers"].get(EXAMPLE)
        run = {
            "run_at": now(),
            "model": args.model,
            "system_sha": vr.system_sha(),
            "budget_usd": args.budget_usd,
            "notices": notices,
            "profiles": list(profiles),
            "cells": m["cells"],
            "cell_errors": m["cell_errors"],
            "stop": m["stop"],
            "symptoms": sym,
            "example": agg.render_text(example, full_text=True) if example else None,
        }
        run["usage"] = vr.usage(
            m, client, sum(v["cached"] for c in m["cells"] for v in c["verdicts"])
        )
        vr.attach_runs(run, prev)  # 첫 실행 · 두 번째 실행을 가르고 zones["cost"]를 채운다
        text = render(run, baseline)
        saved = {
            **run,
            "cells": [slim(c) for c in run["cells"]],
            "symptoms": {k: _plain(v) for k, v in sym.items()},
        }
        write(out_md, text)
        write(out_json, dump(saved))
        print("\n".join(first_lines(sym)))
        print("구간: " + " · ".join(f"{k} {v}" for k, v in sym["zones"].items()))
        print(f"→ {out_md} · {out_json}")
        if run["stop"]:
            print(f"멈춤({run['stop'][0]}): {run['stop'][1]}", file=sys.stderr)
        bad = [k for k in ("rule", "outside") if sym["zones"][k] == "미완"]
        # 징후 1 또는 2가 미완이거나 실행이 멈췄으면 리포트를 쓴 뒤 exit 1
        return 1 if run["stop"] or bad else 0
    except SQLAlchemyError as e:
        print(f"DB 오류: {type(e).__name__}: {getattr(e, 'orig', e)}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
