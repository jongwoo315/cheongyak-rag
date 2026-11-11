"""run.jsonl로 지표를 따로 다시 세고 리포트 `docs/76-eval.md`를 쓴다 (#76).

python -m cheongyak_rag.eval.report [--run-dir runs/76] [--out docs/76-eval.md]

`run.jsonl`을 읽어 지표 7개를 이 파일 안에서 다시 센다(`recompute`). harness의 지표 함수
(`eval.metrics`)는 부르지도 import하지도 않는다 — 같은 함수를 부르면 같이 틀린다(설계 §3.5).
`metrics.json`(harness 값)과 다른 지표 수를 세고, 구간 이름(통과·다시 잰다·미완)과 경계는
plan §실패 징후의 것이다. 손으로 적은 메모는 `notes.json`의 `suspicious`
(의심스러운 정답 라벨)에서 읽는다.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from cheongyak_rag.retrieval.index_db_report import write

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "runs/76"
OUT_MD = ROOT / "docs/76-eval.md"

BUDGET_USD = 10.0
VERDICTS = ("ELIGIBLE", "INELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE")
ABSTAIN = ("NEED_INFO", "UNVERIFIABLE")
LAW_LABEL = re.compile(r"^제\d+조")
JW_CRITERIA = "청약공고 질의에 대한 검색을 완료하고, 검색결과에 대한 판정 기준을 세울 수 있다"
JW_CLARIFIED = "내가 말한 판정기준은 eval harness 쪽이었어"
# (이름, 표에 쓰는 말, 뜻 한 줄)
METRIC_NAMES = (
    ("recall_at_5", "recall@5", "정답 근거 조문 중 조문 검색 top-5에 든 것의 비율"),
    ("hit_at_5", "hit@5", "정답 근거 조문이 하나라도 top-5에 든 정답 라벨의 비율"),
    (
        "citation_precision",
        "citation precision",
        "시스템이 인용한 조문 중 정답 근거 조문인 것의 비율",
    ),
    ("judgment_accuracy", "판정 정확도", "시스템 최종 판정값이 정답 라벨과 같은 비율"),
    ("fatal_error_rate", "치명오답률", "정답이 INELIGIBLE인 라벨 중 시스템이 ELIGIBLE을 낸 비율"),
    (
        "justified_abstain",
        "정당 abstain 비율",
        "정답이 NEED_INFO인 라벨 중 시스템도 abstain한 비율",
    ),
    (
        "unjustified_abstain",
        "부당 abstain 비율",
        "정답이 ELIGIBLE·INELIGIBLE인 라벨 중 abstain한 비율",
    ),
)
READING = (
    "정답 라벨은 #75에서 라벨 규칙 문서를 스크립트로 옮겨 붙였고 jw 표본 20개가 20/20 맞았다."
    " 지표는 「골든셋과 얼마나 맞나」이지 「법적으로 맞나」가 아니다",
    "정답 라벨의 72%(378/524)가 `NEED_INFO`다. 판정 정확도 전체 값은 `NEED_INFO`를 맞힌 것이"
    " 대부분을 차지한다 — 축별·판정값별 표를 같이 본다",
    "거주·소득자산·재당첨 축은 정답이 전부 `NEED_INFO`다(프로필에 칸이 없다)",
)


# ── 따로 다시 세기 ───────────────────────────────────────────────────────


def _r(num: int, den: int) -> dict:
    return {"num": num, "den": den, "value": (num / den) if den else None}


def recompute(rows: list[dict]) -> dict:
    """줄을 한 번 훑으며 분자·분모를 쌓는다. `eval.metrics`와 같은 모양으로 돌려준다."""
    t: dict[str, int] = defaultdict(int)
    by_axis: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        want, top, got, gold = (
            r["gold_citations"],
            set(r["law_top5"]),
            r["sys_verdict"],
            r["gold_verdict"],
        )
        t["pair_den"] += len(want)
        t["pair_num"] += sum(1 for c in want if c in top)
        t["hit_den"] += 1
        t["hit_num"] += 1 if top & set(want) else 0
        for c in r["sys_citations"]:
            if LAW_LABEL.match(c):
                t["cite_den"] += 1
                t["cite_num"] += 1 if c in want else 0
        by_axis[r["axis"]][1] += 1
        by_axis[r["axis"]][0] += 1 if got is not None and got == gold else 0
        if gold == "INELIGIBLE":
            t["fatal_den"] += 1
            t["fatal_num"] += 1 if got == "ELIGIBLE" else 0
        if gold == "NEED_INFO":
            t["just_den"] += 1
            t["just_num"] += 1 if got in ABSTAIN else 0
        if gold in ("ELIGIBLE", "INELIGIBLE"):
            t["unjust_den"] += 1
            t["unjust_num"] += 1 if got in ABSTAIN else 0
    return {
        "recall_at_5": _r(t["pair_num"], t["pair_den"]),
        "hit_at_5": _r(t["hit_num"], t["hit_den"]),
        "citation_precision": _r(t["cite_num"], t["cite_den"]),
        "judgment_accuracy": {
            "total": _r(sum(n for n, _ in by_axis.values()), sum(d for _, d in by_axis.values())),
            "axes": {a: _r(n, d) for a, (n, d) in sorted(by_axis.items())},
        },
        "fatal_error_rate": _r(t["fatal_num"], t["fatal_den"]),
        "justified_abstain": _r(t["just_num"], t["just_den"]),
        "unjustified_abstain": _r(t["unjust_num"], t["unjust_den"]),
    }


def _pairs(m: dict) -> dict:
    """비교용으로 (분자, 분모)만 남긴다. 판정 정확도는 축마다 + 전체를 펴 둔다."""
    if "axes" in m:
        out = {"total": (m["total"]["num"], m["total"]["den"])}
        out.update({a: (v["num"], v["den"]) for a, v in m["axes"].items()})
        return out
    return {"": (m["num"], m["den"])}


def differing(harness: dict, mine: dict) -> list[str]:
    """harness 값과 따로 센 값이 다른 지표 이름."""
    return [
        name for name, *_ in METRIC_NAMES if _pairs(harness.get(name) or {"num": -1, "den": -1})
        != _pairs(mine[name])
    ]  # fmt: skip


def empty_metrics(mine: dict) -> list[str]:
    """분모가 0이라 값이 없는 지표 이름."""
    out = []
    for name, *_ in METRIC_NAMES:
        m = mine[name]["total"] if name == "judgment_accuracy" else mine[name]
        if m["den"] == 0:
            out.append(name)
    return out


# ── 구간 ─────────────────────────────────────────────────────────────────


def _zone(n: int, retry_max: int) -> str:
    return "통과" if n == 0 else "다시 잰다" if n <= retry_max else "미완"


def zone_search(n: int) -> str:
    """징후 1 — 못 맞춘 라벨 + 조문 결과가 0개인 라벨."""
    return _zone(n, 10)


def zone_criteria(n: int) -> str:
    """징후 2 — 값이 없거나 분모가 0인 지표 + 따로 센 값과 다른 지표."""
    return _zone(n, 2)


def zone_errors(n: int) -> str:
    """징후 3 — 판정 실패 하위 질의."""
    return _zone(n, 10)


def zone_cost(usd: float, stopped: bool) -> str:
    """징후 4 — 첫 실행 비용."""
    return "미완" if stopped or usd > BUDGET_USD else "통과"


def zone_repro(second_calls: int, same: bool) -> str:
    """징후 5 — 두 번째 실행의 호출 수와 지표 차이."""
    return "통과" if second_calls == 0 and same else "다시 잰다"


# ── 리포트 ───────────────────────────────────────────────────────────────


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _table(head: list[str], body: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return "\n".join(out)


def _pct(m: dict) -> str:
    return "없음" if m["value"] is None else f"{m['value'] * 100:.1f}%"


def _frac(m: dict) -> str:
    return f"{m['num']}/{m['den']}"


def render(rows: list[dict], harness: dict, notes: dict | None = None) -> str:
    notes = notes or {}
    mine = recompute(rows)
    diff = differing(harness["metrics"], mine)
    empty = empty_metrics(mine)
    counts = harness["counts"]
    unmatched = [r for r in rows if not r["matched"]]
    no_law = [r for r in rows if r["matched"] and not r["law_top5"]]
    failed = [r for r in rows if r["error"]]
    fatal = [
        r for r in rows if r["gold_verdict"] == "INELIGIBLE" and r["sys_verdict"] == "ELIGIBLE"
    ]
    n_search = len(unmatched) + len(no_law)
    n_criteria = len(set(empty) | set(diff))
    z1, z2, z3 = zone_search(n_search), zone_criteria(n_criteria), zone_errors(len(failed))
    first, second = harness.get("first_run"), harness.get("second_run")
    stopped = bool(harness.get("stop"))

    out = ["# #76 eval harness 리포트", ""]
    out += ["## jw 기준", "", f"「{JW_CRITERIA}」", f"(되물은 뒤: 「{JW_CLARIFIED}」)", ""]
    out += [
        f"- 검색을 완료했나: 정답 라벨 {len(rows)}개 중 시스템 하위 질의를 못 맞춘 라벨이"
        f" {len(unmatched)}개,"
        f" 맞췄지만 조문 검색 결과가 0개인 라벨이 {len(no_law)}개다. 합 {n_search}개 → {z1}",
        f"- 판정 기준을 세울 수 있나: 지표 7개 중 분모가 0인 지표가 {len(empty)}개,"
        f" 따로 센 값과 harness 값이 다른 지표가 {len(diff)}개다. 합 {n_criteria}개 → {z2}",
        "- 지표 값이 높은지 낮은지는 이 리포트가 판정하지 않는다. 첫 측정이라 baseline이 없고,"
        " 이번 값이 다음 티켓의 기준선이다",
        "",
    ]

    out += ["## 지표 7개", "", "분자·분모는 `run.jsonl`을 이 리포트가 따로 센 값이다.", ""]
    body = []
    for name, label, meaning in METRIC_NAMES:
        m = mine[name]["total"] if name == "judgment_accuracy" else mine[name]
        body.append(
            [label, meaning, _pct(m), m["num"], m["den"], "다름" if name in diff else "같음"]
        )
    out += [_table(["지표", "뜻", "값", "분자", "분모", "harness 값과"], body), ""]
    out += [
        f"- 못 맞춘 라벨 {counts['unmatched_labels']}개 · 정답 라벨이 없는 시스템 하위 질의"
        f" {counts.get('unmatched_system_queries', '?')}개 · 판정 실패 {counts['verdict_errors']}개"
        f" · FAQ 인용 {counts['faq_citations']}개 (citation precision에서 뺐다)",
        f"- 비용 ${harness['usd']:.4f} (이 실행) · 모델 {harness['model']}",
        "",
    ]

    out += ["## 축별 판정 정확도", ""]
    axes = mine["judgment_accuracy"]["axes"]
    out += [
        _table(
            ["축", "값", "분자", "분모"],
            [[a, _pct(v), v["num"], v["den"]] for a, v in axes.items()],
        )
    ]
    out += ["", ""]

    out += ["## 정답 × 시스템 판정값", "", "줄은 정답 라벨, 칸은 시스템 최종 판정이다."]
    out += ["「판정 없음」은 못 맞춘 라벨과 판정이 실패한 하위 질의다.", ""]
    grid = defaultdict(int)
    for r in rows:
        grid[(r["gold_verdict"], r["sys_verdict"] or "판정 없음")] += 1
    cols = [*VERDICTS, "판정 없음"]
    body = [[g, *[grid[(g, c)] for c in cols]] for g in VERDICTS]
    out += [_table(["정답 \\ 시스템", *cols], body), ""]

    out += [f"## 치명오답 하위 질의 ({len(fatal)}개 전부)", ""]
    out += [
        _table(
            ["문항 id", "공고명", "하위 질의", "시스템 이유", "정답 이유"],
            [
                [r["id"], r["notice_name"], r["query"], r["sys_reason"], r["gold_reason"]]
                for r in fatal
            ],
        )
        if fatal
        else "없다.",
        "",
    ]

    out += ["## 실패 징후", ""]
    rows5 = []
    if first is not None:  # 첫 실행이 끝났으면 뒤 실행이 멈춘 것은 이 구간과 상관없다
        z4 = zone_cost(first["usd"], False)
        c4 = f"첫 실행 ${first['usd']:.4f}, 호출 {first['calls']}회"
    elif stopped:
        z4 = zone_cost(0.0, True)
        spent = harness.get("usage_total", {}).get("usd", harness["usd"])
        c4 = f"실행이 멈췄다({harness['stop'][0]}). 지금까지 ${spent:.4f}"
    else:
        z4, c4 = "미측정", "첫 실행이 아직 끝나지 않았다"
    if second is None:
        z5, c5 = "미측정", "두 번째 실행이 없다"
    else:
        same = second["metrics"] == first["metrics"]
        z5 = zone_repro(second["calls"], same)
        c5 = f"두 번째 실행 호출 {second['calls']}회, 지표 {'같음' if same else '다름'}"
    rows5 = [
        [
            "1 jw 기준 — 검색 완료",
            f"못 맞춘 {len(unmatched)} + 조문 0개 {len(no_law)} = {n_search}",
            z1,
            "0 통과 · 1~10 다시 잰다 · 11 이상 미완",
        ],
        [
            "2 jw 기준 — 판정 기준",
            f"분모 0 {len(empty)} + 다른 값 {len(diff)} = {n_criteria}",
            z2,
            "0 통과 · 1~2 다시 잰다 · 3 이상 미완",
        ],
        ["3 판정 실패", f"{len(failed)}", z3, "0 통과 · 1~10 다시 잰다 · 11 이상 미완"],
        ["4 첫 실행 비용", c4, z4, f"${BUDGET_USD:g} 이하 통과 · 상한에서 멈추면 미완"],
        ["5 재현성", c5, z5, "호출 0 · 다른 지표 0이면 통과"],
        [
            "6 지표 값 자체",
            "값은 위 표에 적었다",
            "구간 없음",
            "적기만 한다. 첫 측정이라 baseline이 없다",
        ],
    ]
    out += [_table(["징후", "측정값", "구간", "구간 조건"], rows5), ""]
    if stopped:
        out += [f"- 실행이 멈췄다({harness['stop'][0]}): {harness['stop'][1]}", ""]

    out += ["## 못 맞춘 라벨과 조문 결과가 없는 라벨", ""]
    items = [[r["id"], r["query"], r["cause"]] for r in unmatched]
    items += [[r["id"], r["query"], "조문 검색 결과가 0개"] for r in no_law]
    out += [_table(["문항 id", "정답 라벨의 하위 질의", "이유"], items) if items else "없다.", ""]

    out += ["## 판정 실패 하위 질의", ""]
    out += [
        _table(
            ["문항 id", "하위 질의", "오류"], [[r["id"], r["query"], r["error"]] for r in failed]
        )
        if failed
        else "없다.",
        "",
    ]

    out += ["## 정답 라벨이 의심스러운 것", ""]
    sus = notes.get("suspicious") or []
    out += [
        _table(["문항 id", "하위 질의", "이유"], [[s["id"], s["query"], s["reason"]] for s in sus])
        if sus
        else "적을 것이 없다.",
        "",
    ]

    out += ["## 실행 기록", ""]
    for name, run in (("첫 실행", first), ("두 번째 실행", second)):
        if run:
            out.append(
                f"- {name} ({run['run_at']}): 호출 {run['calls']}회"
                f" · 캐시 {run.get('cache_hits', 0)}회 · ${run['usd']:.4f}"
            )
    if first and second:
        out.append(f"- 지표 값 {'같음' if second['metrics'] == first['metrics'] else '다름'}")
    out += ["", "## 지표를 읽는 법", ""]
    out += [f"- {s}" for s in READING]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.eval.report")
    ap.add_argument("--run-dir", type=Path, default=RUN_DIR)
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)
    try:
        rows = [
            json.loads(x) for x in (args.run_dir / "run.jsonl").read_text("utf-8").splitlines() if x
        ]
        harness = json.loads((args.run_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"읽기 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        notes = json.loads((args.run_dir / "notes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        notes = {}
    write(args.out, render(rows, harness, notes))
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
