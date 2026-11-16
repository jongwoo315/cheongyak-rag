"""#180 리포트 — 프로필 가능 규칙을 건 뒤의 실패 징후 1~5를 재고 `docs/180-eligible.md`를 쓴다.

python -m cheongyak_rag.generate.eligible_report [--out docs/180-eligible.md]

두 표본(골든셋 50문항 `runs/180/run.jsonl`, 시연 18쌍 `runs/180/demo/last_run.json`)과 착수 때
값(`runs/82`·`runs/81`)을 같은 함수로 센다. 판정(OpenAI)을 부르지 않고 DB 공고 값은 읽기만 한다.
「정보가 없음」 칸의 정의는 설계 `docs/plans/180-1116-design-eligible-missing-info.md` §3,
구간 이름과 경계는 plan §실패 징후의 것이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import sqlalchemy as sa

from cheongyak_rag.config import settings
from cheongyak_rag.eval import report as eval_report
from cheongyak_rag.generate import questions, rules
from cheongyak_rag.generate import verdict_report as vr
from cheongyak_rag.ingest.notice_report import _table
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.index_db_report import write

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "runs/75/golden.jsonl"
NOW_RUN = ROOT / "runs/180/run.jsonl"
BASE_RUN = ROOT / "runs/82/run.jsonl"
NOW_DEMO = ROOT / "runs/180/demo/last_run.json"
BASE_DEMO = ROOT / "runs/81/last_run.json"
PROFILES_DIR = ROOT / "runs/80/profiles"
OUT_MD = ROOT / "docs/180-eligible.md"

JW_CRITERIA = "'정보가 없음' 프로필 칸에 정답 라벨 'ELIGIBLE'이 붙는 케이스가 발생하지 않는다"
JW_CLARIFIED = "「정답 라벨」은 시스템 판정, LLM이 낸 ELIGIBLE을 뜻한다"
VERDICTS = ("ELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE", "INELIGIBLE")
GOLDEN_NAME, DEMO_NAME = "골든셋", "시연"
ACCURACY_OK, ACCURACY_RETRY_MIN = (
    421,
    416,
)  # 실패 징후 4: 이 값 이상 정상, 이 값 이상 420까지 다시 잰다

# 설계 §4 세 줄 (PR 본문 Notes에도 그대로 옮긴다)
DESIGN_SECTION_4 = (
    "jw 기준 측정값은 이번 변경 전에도 0이다. 프로필 칸이 빈 ELIGIBLE은 #80 ELIGIBLE guard가 "
    "이미 막고 있다. 이번 티켓이 바꾸는 것은 화면에 나가는 이유(같이 재는 것 첫 줄)와, 칸이 "
    "찼는데 LLM이 놓친 ELIGIBLE이다",
    "규칙과 정답 라벨이 같은 문서에서 나왔다. 프로필 가능 규칙은 라벨 규칙 ELIGIBLE 줄을 옮긴 "
    "것이다. 판정 정확도가 오르면 거의 정의상 오른 것이다(#82와 같다)",
    "「정보가 없음」 칸 정의가 결손 분석에 기댄다. 결손 분석 표가 축에 필요한 정보를 빠뜨렸으면 "
    "측정값도 같이 0으로 나온다. #82에서 결손 분석은 정답 라벨 `need`와 378/378 같았다",
)


# ── 「정보가 없음」 칸 (설계 §3) ─────────────────────────────────────────


def missing_cells(axis: str, query: str, profile: dict, facts: axes.Facts) -> list[str]:
    """하위 질의의 「정보가 없음」 칸. 결손 분석의 없는 정보 · 불가 판정을 낼 수 있는 빈 칸 ·
    가능 규칙이 보는 칸 중 빈 것을 한 번씩만 적는다."""
    miss = questions.analyze(axis, query, profile, facts)
    empty = [f for f in rules.eligible_fields(axis, query) if profile.get(f) is None]
    return list(dict.fromkeys([*miss.info, *miss.can_rule_out, *empty]))


def ruled_by(axis: str, query: str, profile: dict, reason: str) -> str | None:
    """`reason`이 프로필 가능 규칙이 쓴 이유 문장이면 그 규칙 번호. 판정 줄에 규칙 표시가 없는
    `runs/82`·`runs/81`도 같은 함수로 센다."""
    hit = rules.rule_eligible(axis, query, profile)
    return hit[0] if hit and hit[1] == reason else None


# ── 하위 질의 기록 ───────────────────────────────────────────────────────


def read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def golden_records(
    golden: list[dict], lines: list[dict], facts: dict[str, axes.Facts]
) -> list[dict]:
    """골든셋 run 줄 → 하위 질의 기록. 시스템 하위 질의를 못 맞춘 줄(`matched=false`)은 뺀다."""
    by_id: dict[str, list[dict]] = {}
    for r in lines:
        by_id.setdefault(r["id"], []).append(r)
    return [
        {"sample": GOLDEN_NAME, "where": f"{row['id']} {row['notice_name']}", "axis": r["axis"],
         "query": r["query"], "verdict": r["sys_verdict"], "reason": r["sys_reason"],
         "model": r["sys_pre_verdict"], "gold": r["gold_verdict"], "gold_reason": r["gold_reason"],
         "profile": row["profile"], "facts": facts[row["id"]],
         "key": (row["id"], r["axis"], r["query"])}
        for row in golden
        for r in by_id.get(row["id"], [])
        if r["matched"]
    ]  # fmt: skip


def demo_records(run: dict, profiles: dict[str, dict], facts: dict[str, axes.Facts]) -> list[dict]:
    """시연 18쌍 결과 → 하위 질의 기록. 정답 라벨이 없다."""
    out = []
    for c in run["cells"]:
        for v in c["verdicts"]:
            changed = v.get("guarded") or v.get("forced") or v.get("ruled")
            out.append({
                "sample": DEMO_NAME, "where": f"{c['name']} × {c['profile']}", "axis": v["axis"],
                "query": v["query"], "verdict": v["verdict"], "reason": v["reason"],
                "model": v["original_verdict"] if changed else v["verdict"],
                "gold": None, "gold_reason": None, "profile": profiles[c["profile"]],
                "facts": facts[c["notice"]],
                "key": (c["notice"], c["profile"], v["axis"], v["query"]),
            })  # fmt: skip
    return out


def final_eligible(recs: list[dict]) -> list[dict]:
    return [r for r in recs if r["verdict"] == "ELIGIBLE"]


# ── 실패 징후 ────────────────────────────────────────────────────────────


def jw_hits(recs: list[dict]) -> list[dict]:
    """실패 징후 1 — 최종 ELIGIBLE 중 「정보가 없음」 칸이 있는 하위 질의와 그 칸."""
    out = []
    for r in final_eligible(recs):
        cells = missing_cells(r["axis"], r["query"], r["profile"], r["facts"])
        if cells:
            out.append({"rec": r, "cells": cells})
    return out


def model_reasons(recs: list[dict]) -> list[dict]:
    """실패 징후 2 — 최종 ELIGIBLE 중 이유를 LLM이 쓴 것."""
    return [
        r
        for r in final_eligible(recs)
        if not ruled_by(r["axis"], r["query"], r["profile"], r["reason"])
    ]


def wrong_eligible(recs: list[dict]) -> list[dict]:
    """실패 징후 3 — 정답 라벨이 있는 표본에서 최종 ELIGIBLE인데 정답이 ELIGIBLE이 아닌 것."""
    return [r for r in final_eligible(recs) if r["gold"] is not None and r["gold"] != "ELIGIBLE"]


def rule_changes(recs: list[dict]) -> Counter:
    """(규칙 번호, 모델 판정) → 가능 규칙이 이유를 쓴 최종 ELIGIBLE 하위 질의 수."""
    c: Counter = Counter()
    for r in final_eligible(recs):
        rule = ruled_by(r["axis"], r["query"], r["profile"], r["reason"])
        if rule:
            c[(rule, r["model"])] += 1
    return c


def zone_count(n: int, ok: str = "통과") -> str:
    """실패 징후 1·2·3·5: 0이 `ok`, 1~2는 다시 잰다, 3 이상은 미완."""
    return ok if n == 0 else "다시 잰다" if n <= 2 else "미완"


def zone_accuracy(n: int) -> str:
    """실패 징후 4: 421 이상 정상, 416~420 다시 잰다, 415 이하 미완."""
    return "정상" if n >= ACCURACY_OK else "다시 잰다" if n >= ACCURACY_RETRY_MIN else "미완"


def measure(now: dict, base: dict) -> dict:
    """`now`·`base`는 `{"golden": 기록, "demo": 기록, "rows": run 줄}`. 같은 함수로 센다."""

    def side(d: dict) -> dict:
        both = d["golden"] + d["demo"]
        metrics = eval_report.recompute(d["rows"])
        return {
            "eligible": {
                GOLDEN_NAME: len(final_eligible(d["golden"])),
                DEMO_NAME: len(final_eligible(d["demo"])),
            },
            "jw": jw_hits(both), "model": model_reasons(both), "wrong": wrong_eligible(d["golden"]),
            "changes": rule_changes(both), "metrics": metrics,
            "acc": metrics["judgment_accuracy"]["total"], "fatal": metrics["fatal_error_rate"],
        }  # fmt: skip

    n, b = side(now), side(base)
    count = lambda hits, sample: sum(1 for h in hits if (h.get("rec") or h)["sample"] == sample)  # noqa: E731
    return {
        "now": n, "base": b, "count": count,
        "zones": {
            "jw": zone_count(len(n["jw"])),
            "model": zone_count(len(n["model"]), "정상"),
            "wrong": zone_count(len(n["wrong"]), "정상"),
            "accuracy": zone_accuracy(n["acc"]["num"]),
            "fatal": zone_count(n["fatal"]["num"], "정상"),
        },
    }  # fmt: skip


# ── 리포트 ───────────────────────────────────────────────────────────────


def _short(text: str, n: int = 120) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _frac(num: int, den: int) -> str:
    return f"{num}/{den}"


def _pct(m: dict) -> str:
    return "—" if m["value"] is None else f"{m['value'] * 100:.1f}%"


def _profile_cells(r: dict) -> str:
    names = rules.eligible_fields(r["axis"], r["query"])
    return ", ".join(f"{f}={r['profile'].get(f)}" for f in names) or "—"


def _rec(h: dict) -> dict:
    return h.get("rec", h)  # 징후 1 줄은 `{"rec", "cells"}`, 나머지는 기록 그대로다


def _by_sample(side: dict, key: str) -> str:
    """`골든셋 a/b · 시연 c/d` 꼴. 분모는 그 표본의 최종 ELIGIBLE 수다."""
    parts = [
        f"{name} {_frac(sum(1 for h in side[key] if _rec(h)['sample'] == name), den)}"
        for name, den in side["eligible"].items()
    ]
    return " · ".join(parts)


def _metric(x: dict, key: str) -> dict:
    m = x["metrics"][key]
    return m["total"] if key == "judgment_accuracy" else m


def _symptom_table(n: dict, b: dict, z: dict) -> list[str]:
    rows = [
        ["1. jw 기준 — 최종 ELIGIBLE 중 「정보가 없음」 칸이 있는 하위 질의",
         _by_sample(b, "jw"), f"{_by_sample(n, 'jw')} · 합 {len(n['jw'])}", z["jw"]],
        ["2. 이유를 LLM이 쓴 최종 ELIGIBLE",
         _by_sample(b, "model"), f"{_by_sample(n, 'model')} · 합 {len(n['model'])}", z["model"]],
        ["3. 틀린 ELIGIBLE — 골든셋 최종 ELIGIBLE인데 정답 라벨이 ELIGIBLE이 아닌 것",
         _frac(len(b["wrong"]), b["eligible"][GOLDEN_NAME]),
         _frac(len(n["wrong"]), n["eligible"][GOLDEN_NAME]), z["wrong"]],
        ["4. 판정 정확도 — 골든셋 맞힌 하위 질의",
         _frac(b["acc"]["num"], b["acc"]["den"]), _frac(n["acc"]["num"], n["acc"]["den"]),
         z["accuracy"]],
        ["5. 치명오답 — 정답이 INELIGIBLE인 하위 질의에 최종 ELIGIBLE",
         _frac(b["fatal"]["num"], b["fatal"]["den"]),
         _frac(n["fatal"]["num"], n["fatal"]["den"]), z["fatal"]],
    ]  # fmt: skip
    return _table(["징후", "착수 때 값", "이번 값", "구간"], rows)


def _hit_tables(n: dict) -> list[str]:
    """구간이 다시 잰다·미완일 때 걸린 하위 질의를 적는다. 0이면 아무것도 안 낸다."""
    out: list[str] = []
    if n["jw"]:
        rows = []
        for h in n["jw"]:
            r = h["rec"]
            who = (
                "가능 규칙"
                if ruled_by(r["axis"], r["query"], r["profile"], r["reason"])
                else "모델"
            )
            rows.append([r["sample"], r["where"], r["axis"], ", ".join(h["cells"]), who])
        head = ["표본", "문항 · 공고×프로필", "축", "「정보가 없음」 칸", "판정을 바꾼 주체"]
        out += ["", "### 징후 1 — 「정보가 없음」 칸이 있는 최종 ELIGIBLE", "", *_table(head, rows)]
    if n["model"]:
        rows = [[r["sample"], r["where"], r["axis"], _profile_cells(r), _short(r["reason"])]
                for r in n["model"]]  # fmt: skip
        head = ["표본", "문항 · 공고×프로필", "축", "프로필 칸", "모델 이유"]
        out += ["", "### 징후 2 — 이유를 LLM이 쓴 최종 ELIGIBLE", "", *_table(head, rows)]
    if n["wrong"]:
        rows = [[r["where"], r["axis"], _profile_cells(r), r["gold"], _short(r["gold_reason"])]
                for r in n["wrong"]]  # fmt: skip
        head = ["문항", "축", "프로필 칸", "정답 라벨", "정답 이유"]
        out += ["", "### 징후 3 — 틀린 ELIGIBLE", "", *_table(head, rows)]
    if n["fatal"]["num"]:
        out += ["", "### 징후 5 — 치명오답", "",
                "- `runs/180/run.jsonl`에서 `gold_verdict`가 INELIGIBLE이고 `sys_verdict`가 "
                "ELIGIBLE인 줄이다"]  # fmt: skip
    return out


def _metric_table(n: dict, b: dict) -> list[str]:
    rows = []
    for key, label, _ in eval_report.METRIC_NAMES:
        bm, nm = _metric(b, key), _metric(n, key)
        rows.append([label, f"{_pct(bm)} ({bm['num']}/{bm['den']})",
                     f"{_pct(nm)} ({nm['num']}/{nm['den']})"])  # fmt: skip
    return _table(["지표", "변경 전", "변경 후"], rows)


def _change_table(n: dict) -> list[str]:
    rows = []
    for r in rules.ELIGIBLE_RULES:
        counts = [n["changes"][(r.id, v)] for v in VERDICTS]
        rows.append([r.id, *counts, sum(counts)])
    return _table(["규칙", *VERDICTS, "합"], rows)


def render(m: dict, golden_changed: list[dict]) -> str:
    n, b = m["now"], m["base"]
    total = sum(n["eligible"].values())
    changed = [
        [c["where"], c["axis"], c["gold"], c["base"], c["now"], c["rule"] or "—"]
        for c in golden_changed
    ]
    out = [
        "# #180 「정보가 없다」에 기대는 ELIGIBLE 막기 — 측정",
        "",
        f"- jw 기준: 「{JW_CRITERIA}」",
        f"  - 되물은 뒤: {JW_CLARIFIED}",
        "- 표본은 골든셋 50문항(`runs/180/run.jsonl`)과 시연 18쌍이다",
        "  - 시연 18쌍은 `runs/180/demo/last_run.json`이다",
        "- 착수 때 값은 변경 전 코드로 돌린 `runs/82`·`runs/81`을 같은 함수로 센 것이다",
        "- 「정보가 없음」 칸은 하위 질의 하나에서 아래 셋 중 하나에 드는 것이다",
        "  - 결손 분석(#82 `questions.analyze`)의 없는 정보",
        "  - 결손 분석의 불가 판정을 낼 수 있는 빈 칸",
        "  - 그 하위 질의에 걸리는 프로필 가능 규칙이 보는 칸 중 비어 있는 것",
        "",
        "## 실패 징후 1~5",
        "",
        *_symptom_table(n, b, m["zones"]),
        "",
        "- 구간: 징후 1은 0 통과 · 1~2 다시 잰다 · 3 이상 미완이다",
        "- 징후 2·3·5는 0 정상 · 1~2 다시 잰다 · 3 이상 미완이다",
        "- 징후 4는 421 이상 정상 · 416~420 다시 잰다 · 415 이하 미완이다",
        *_hit_tables(n),
        "",
        "## 지표 7개 — 변경 전(`runs/82`)과 변경 후(`runs/180`)",
        "",
        *_metric_table(n, b),
        "",
        "- 판정 정확도와 치명오답만 이번 기준이다. 나머지는 전후 값만 적는다",
        "",
        "## 가능 규칙이 이유를 쓴 하위 질의 — 규칙별 · 모델 판정별",
        "",
        "- 두 표본의 최종 ELIGIBLE 중 이유가 가능 규칙 문장인 하위 질의 수다",
        "- 모델 판정이 ELIGIBLE이 아닌 칸은 판정값까지 코드가 바꾼 것이다",
        "- 모델 판정이 ELIGIBLE인 칸은 이유만 바꾼 것이다",
        "",
        *_change_table(n),
        "",
        f"- 합 {sum(n['changes'].values())}개는 최종 ELIGIBLE {total}개 중 규칙이 이유를 쓴 것이다",
        f"- 착수 때 값은 {sum(b['changes'].values())}개다",
        "",
        f"## 골든셋에서 `runs/82`와 최종 판정이 달라진 하위 질의 — {len(golden_changed)}개",
        "",
        *_table(["문항", "축", "정답 라벨", "변경 전 판정", "변경 후 판정", "가능 규칙"], changed),
        "",
        "## 설계 §4 — 숫자 읽는 법",
        "",
        *[f"- {s}" for s in DESIGN_SECTION_4],
    ]
    return "\n".join(out) + "\n"


def changed_golden(now: list[dict], base: list[dict]) -> list[dict]:
    """골든셋에서 `runs/82`와 최종 판정이 다른 하위 질의."""
    before = {r["key"]: r for r in base}
    out = []
    for r in now:
        old = before.get(r["key"])
        if old is None or old["verdict"] == r["verdict"]:
            continue
        rule = ruled_by(r["axis"], r["query"], r["profile"], r["reason"])
        out.append({"where": r["where"], "axis": r["axis"], "gold": r["gold"],
                    "base": old["verdict"], "now": r["verdict"], "rule": rule})  # fmt: skip
    return out


# ── 실행 ─────────────────────────────────────────────────────────────────


def _load(golden, run_path: Path, demo: dict, profiles, facts_g, facts_d) -> dict:
    rows = read_rows(run_path)
    return {
        "rows": rows,
        "golden": golden_records(golden, rows, facts_g),
        "demo": demo_records(demo, profiles, facts_d),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.eligible_report")
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--now-run", type=Path, default=NOW_RUN)
    ap.add_argument("--base-run", type=Path, default=BASE_RUN)
    ap.add_argument("--now-demo", type=Path, default=NOW_DEMO)
    ap.add_argument("--base-demo", type=Path, default=BASE_DEMO)
    ap.add_argument("--profiles", type=Path, default=PROFILES_DIR)
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)
    try:
        golden = read_rows(args.golden)
        profiles = {k: p.to_dict() for k, p in vr.load_profiles(args.profiles).items()}
        demo_now = json.loads(args.now_demo.read_text(encoding="utf-8"))
        demo_base = json.loads(args.base_demo.read_text(encoding="utf-8"))
        engine = sa.create_engine(settings.database_url)
        try:
            facts_g = {
                r["id"]: axes.load_facts(engine, r["house_manage_no"], r["pblanc_no"])[2]
                for r in golden
            }
            notices = {c["notice"] for d in (demo_now, demo_base) for c in d["cells"]}
            facts_d = {h: axes.load_facts(engine, h)[2] for h in sorted(notices)}
        finally:
            engine.dispose()
        now = _load(golden, args.now_run, demo_now, profiles, facts_g, facts_d)
        base = _load(golden, args.base_run, demo_base, profiles, facts_g, facts_d)
        m = measure(now, base)
        md = render(m, changed_golden(now["golden"], base["golden"]))
    except (OSError, ValueError, KeyError) as e:
        print(f"읽기 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    write(args.out, md)
    print("구간: " + " · ".join(f"{k} {v}" for k, v in m["zones"].items()))
    print(f"→ {args.out}")
    return 1 if "미완" in m["zones"].values() else 0


if __name__ == "__main__":
    sys.exit(main())
