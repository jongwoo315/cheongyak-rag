"""#82 리포트 — 골든셋 정답 라벨과 `runs/82`·`runs/138` 줄로 실패 징후 1~4를 센다.

python -m cheongyak_rag.generate.questions_report [--out docs/82-missing-info.md]

판정(OpenAI)을 부르지 않는다. 시스템 질문은 `runs/82/run.jsonl`의 시스템 판정으로 다시 만들고,
DB 공고 값은 읽기만 한다. 필요한 질문의 정의는 설계 `docs/plans/82-1114-design-missing-info.md` §3,
구간 이름과 경계는 plan §실패 징후의 것이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from cheongyak_rag.config import settings
from cheongyak_rag.eval import metrics
from cheongyak_rag.eval.report import METRIC_NAMES
from cheongyak_rag.generate import aggregate, questions, rules
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.index_db_report import write

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "runs/75/golden.jsonl"
NOW_DIR = ROOT / "runs/82"
BASE_DIR = ROOT / "runs/138"
OUT_MD = ROOT / "docs/82-missing-info.md"

NOT_PORTED = ("referral-1", "newlywed-3")  # 이번에 안 옮긴 라벨 규칙 (규칙 표 머리말)
JW_CRITERIA = (
    "입력한 프로필에서 어느 필드가 부족한지 분석이 된다, 불가 판정 여부를 먼저 진행하여 "
    "불필요한 질문을 하지 않는다"
)
RETRY_FLOOR = 360  # 실패 징후 1-①: 이 값 이상 전부 미만이면 다시 잰다
VERDICTS = ("ELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE", "INELIGIBLE")

# 설계 §4 세 줄 (PR 본문 Notes에도 그대로 옮긴다)
DESIGN_SECTION_4 = (
    "규칙과 정답 라벨이 같은 문서에서 나왔다. 2.1 규칙도 2.2 없는 정보도 라벨 규칙을 옮긴 것이고, "
    "정답 라벨도 그 규칙으로 붙였다. 그래서 결손 분석 일치 수와 규칙이 고친 판정은 거의 정의상 "
    "맞는다. 같이 틀릴 수 있다 — 라벨 규칙이 법령을 잘못 읽었으면 둘 다 틀린다",
    "따로 떼어 둔 확인용 문항은 없다. 골든셋이 유일한 측정 데이터다(#138과 같다)",
    "판정 정확도·치명오답률이 #138보다 오르는 것은 대부분 규칙 덕이다. "
    "규칙이 바꾼 하위 질의 수를 따로 센다",
)


# ── 입력 ─────────────────────────────────────────────────────────────────


def read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def lines_by_id(lines: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in lines:
        out.setdefault(r["id"], []).append(r)
    return out


def load_facts(engine, golden: list[dict]) -> dict[str, axes.Facts]:
    """문항 id → 공고 값. DB는 읽기만 한다."""
    return {
        r["id"]: axes.load_facts(engine, r["house_manage_no"], r["pblanc_no"])[2] for r in golden
    }


def _verdict(axis: str, query: str, verdict: str | None) -> vd.Verdict:
    return vd.Verdict(axis, axis, query, verdict=verdict)


def gold_verdicts(row: dict) -> list[vd.Verdict]:
    return [_verdict(g["axis"], g["query"], g["verdict"]) for g in row["labels"]]


def system_verdicts(lines: list[dict]) -> list[vd.Verdict]:
    """run 줄 → 시스템 판정. 시스템 하위 질의를 못 맞춘 줄(`matched=false`)은 뺀다."""
    return [_verdict(r["axis"], r["query"], r["sys_verdict"]) for r in lines if r["matched"]]


# ── 정답 라벨로 합친 경로와 필요한 질문 (설계 §3) ────────────────────────


def gold_routes(plans: list[axes.AxisPlan], row: dict) -> aggregate.Aggregate:
    """정답 라벨로 합친 경로 판정."""
    return aggregate.aggregate(plans, gold_verdicts(row))


def needed_questions(plans: list[axes.AxisPlan], row: dict, facts: axes.Facts) -> set[str]:
    """필요한 질문의 정보 이름.

    X가 어느 하위 질의 s의 없는 정보 또는 불가 판정을 낼 수 있는 빈 칸이고, s의 정답 라벨이
    NEED_INFO이고, s가 속한 경로 중 하나라도 정답 라벨로 합친 경로 판정이 INELIGIBLE이 아니다.
    """
    agg = gold_routes(plans, row)
    routes = [agg.general, *agg.special]
    open_keys = {r.key for r in routes if r.verdict != "INELIGIBLE"}
    special = [r.key for r in agg.special]
    out: set[str] = set()
    for v in gold_verdicts(row):
        if v.verdict != "NEED_INFO" or not open_keys & set(questions._route_keys(v, special)):
            continue
        miss = questions.analyze(v.axis, v.query, row["profile"], facts)
        out |= {*miss.info, *miss.can_rule_out}
    return out


def asked_questions(
    plans: list[axes.AxisPlan], row: dict, lines: list[dict], facts: axes.Facts
) -> list[questions.Question]:
    """시스템 판정으로 만든 질문."""
    return questions.build_questions(plans, system_verdicts(lines), row["profile"], facts)


def question_sources(
    row: dict, lines: list[dict], facts: axes.Facts, names: set[str]
) -> list[dict]:
    """시스템 질문 `names`가 쓰인 시스템 NEED_INFO 하위 질의와 그 정답 라벨."""
    gold = {(g["axis"], g["query"]): g for g in row["labels"]}
    out = []
    for v in system_verdicts(lines):
        if v.verdict != "NEED_INFO":
            continue
        miss = questions.analyze(v.axis, v.query, row["profile"], facts)
        g = gold[(v.axis, v.query)]
        for n in sorted(names & {*miss.info, *miss.can_rule_out}, key=questions.ORDER.index):
            out.append({"name": n, "axis": v.axis, "query": v.query, "gold": g["verdict"],
                        "gold_rule": g["rule"], "system": v.verdict})  # fmt: skip
    return out


def unfiltered_info(row: dict, lines: list[dict], facts: axes.Facts) -> set[str]:
    """규칙 없이 판정만 받아 경로를 안 거르고 NEED_INFO 하위 질의의 없는 정보를 다 묻는 값."""
    return {
        n
        for v in system_verdicts(lines)
        if v.verdict == "NEED_INFO"
        for n in questions.analyze(v.axis, v.query, row["profile"], facts).info
    }


# ── 실패 징후 1: jw 기준 ─────────────────────────────────────────────────


def analysis_mismatches(row: dict, facts: axes.Facts) -> tuple[int, list[dict]]:
    """정답 라벨이 NEED_INFO인 하위 질의 수와, 없는 정보 집합이 정답 `need`와 다른 것."""
    total, bad = 0, []
    for g in row["labels"]:
        if g["verdict"] != "NEED_INFO":
            continue
        total += 1
        got = questions.analyze(g["axis"], g["query"], row["profile"], facts).info
        if set(got) != set(g["need"]):
            bad.append({"id": row["id"], "axis": g["axis"], "query": g["query"],
                        "need": g["need"], "got": got})  # fmt: skip
    return total, bad


def band_jw(found: int, den: int, unneeded_items: int) -> str:
    """통과: ① 전부이고 ② 0 / 미완: ① RETRY_FLOOR 미만이거나 ② 4 이상 / 그 사이는 다시 잰다."""
    if found < RETRY_FLOOR or unneeded_items >= 4:
        return "미완"
    return "통과" if found == den and unneeded_items == 0 else "다시 잰다"


def band_missing(now: int, base: int) -> str:
    """정상: 비교값 이하 / 다시 잰다: 1~3 많다 / 미완: 4 이상 많다."""
    return "정상" if now <= base else "다시 잰다" if now - base <= 3 else "미완"


def band_rule(n: int) -> str:
    return "정상" if n == 0 else "다시 잰다" if n <= 3 else "미완"


def band_fatal(n: int) -> str:
    return "정상" if n <= 2 else "다시 잰다" if n <= 5 else "미완"


# ── 규칙이 바꾼 하위 질의 (실패 징후 3) ──────────────────────────────────


def rule_hits(row: dict, lines: list[dict], facts: axes.Facts) -> list[dict]:
    """`judge_one`이 규칙을 적용한 하위 질의. 호출이 성공했고 근거가 있는 줄만 센다."""
    by_key = {(r["axis"], r["query"]): r for r in lines}
    as_of = date.fromisoformat(row["as_of"])
    out = []
    for g in row["labels"]:
        r = by_key.get((g["axis"], g["query"]))
        if r is None or not r["matched"] or r["error"] or not (r["law_top5"] or r["faq_top3"]):
            continue
        hit = rules.rule_ineligible(g["axis"], g["query"], row["profile"], facts, as_of)
        if hit:
            out.append({"id": row["id"], "notice_name": row["notice_name"], "axis": g["axis"],
                        "query": g["query"], "rule": hit[0], "gold": g["verdict"],
                        "gold_reason": g["reason"], "model": r["sys_pre_verdict"],
                        "system": r["sys_verdict"], "profile": row["profile"]})  # fmt: skip
    return out


def rule_values(hit: dict) -> str:
    """규칙이 본 프로필 칸의 값."""
    rule = next(r for r in rules.RULES if r.id == hit["rule"])
    return ", ".join(f"{f}={hit['profile'].get(f)}" for f in rule.fields)


def fatal_lines(lines: list[dict]) -> list[dict]:
    return [
        r for r in lines if r["gold_verdict"] == "INELIGIBLE" and r["sys_verdict"] == "ELIGIBLE"
    ]


# ── 글 ───────────────────────────────────────────────────────────────────


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], body: list[list]) -> str:
    rows = [head, ["---"] * len(head), *body]
    return "\n".join("| " + " | ".join(_cell(c) for c in r) + " |" for r in rows)


def _pct(m: dict) -> str:
    return "—" if m["value"] is None else f"{m['value'] * 100:.1f}% ({m['num']}/{m['den']})"


def _names_of(profile: dict) -> str:
    return ", ".join(k for k, v in profile.items() if v is not None) or "없음"


def _names(names) -> str:
    return "·".join(sorted(names, key=questions.ORDER.index)) or "없음"


def measure(golden: list[dict], now: list[dict], base: list[dict], facts: dict) -> dict:
    """문항 50개 전체의 측정값."""
    now_by, base_by = lines_by_id(now), lines_by_id(base)
    out = {"den": 0, "found": 0, "mismatch": [], "unneeded": [], "unfiltered": [], "missing": [],
           "missing_base": [], "hits": [], "items": {}}  # fmt: skip
    for row in golden:
        f, plans = facts[row["id"]], axes.plan_from_facts(facts[row["id"]])
        den, bad = analysis_mismatches(row, f)
        out["den"] += den
        out["found"] += den - len(bad)
        out["mismatch"] += bad
        need = needed_questions(plans, row, f)
        asked = asked_questions(plans, row, now_by[row["id"]], f)
        names = {q.name for q in asked}
        base_names = {q.name for q in asked_questions(plans, row, base_by[row["id"]], f)}
        out["items"][row["id"]] = {"need": need, "asked": asked}
        base_info = unfiltered_info(row, base_by[row["id"]], f)
        for key, extra in (
            ("unneeded", names - need),
            ("unfiltered", base_info - need),
            ("missing", need - names),
            ("missing_base", need - base_names),
        ):
            if extra:
                entry = {"id": row["id"], "notice_name": row["notice_name"], "names": extra}
                if key == "unneeded":
                    entry["sources"] = question_sources(row, now_by[row["id"]], f, extra)
                out[key].append(entry)
        out["hits"] += rule_hits(row, now_by[row["id"]], f)
    return out


def example_item(golden: list[dict], m: dict) -> dict | None:
    """질문이 하나라도 있는 첫 부분 프로필 문항."""
    for row in golden:
        if row["profile_kind"] == "partial" and m["items"][row["id"]]["asked"]:
            return row
    return None


def render(golden: list[dict], now: list[dict], base: list[dict], m: dict) -> str:
    a, den = m["found"], m["den"]
    n_unneeded, n_unfiltered = len(m["unneeded"]), len(m["unfiltered"])
    n_miss, n_miss_base = len(m["missing"]), len(m["missing_base"])
    hits = m["hits"]
    wrong = [h for h in hits if h["gold"] != "INELIGIBLE"]
    f_now, f_base = fatal_lines(now), fatal_lines(base)
    changed = [h for h in hits if h["model"] != "INELIGIBLE"]
    out = [
        "# #82 결손 분석과 질문 순서 — 불가 판정을 먼저 내고 필요한 질문만 묻는다",
        "",
        "측정: 골든셋 정답 라벨(`runs/75/golden.jsonl`)과"
        " `runs/82/run.jsonl`·`runs/138/run.jsonl`을 읽어"
        " 이 파일의 코드(`generate/questions_report.py`)가 센 값이다."
        " 설계는 `docs/plans/82-1114-design-missing-info.md`다.",
        "",
        "## jw 기준",
        "",
        f"「{JW_CRITERIA}」",
        "",
        f"- 구간: **{band_jw(a, den, n_unneeded)}** (통과: ①이 전부이고 ②가 0문항 /"
        f" 다시 잰다: ①이 {RETRY_FLOOR}~{den - 1}개이거나 ②가 1~3문항 /"
        f" 미완: ①이 {RETRY_FLOOR - 1}개 이하이거나 ②가 4문항 이상)",
        "",
        _table(
            ["값", "이번(runs/82)", "비교값"],
            [
                [
                    "① 결손 분석 — 정답 라벨이 NEED_INFO인 하위 질의 중"
                    " 없는 정보 집합이 정답 `need`와 같은 수",
                    f"{a}/{den}",
                    "—",
                ],
                [
                    "② 불필요한 질문 — 시스템 질문에 불필요한 질문이 있는 문항 수 (50문항 중)",
                    n_unneeded,
                    f"{n_unfiltered} (규칙 없이 `runs/138` 판정으로 경로를 안 거르고"
                    " NEED_INFO 하위 질의의 없는 정보를 다 묻는 값)",
                ],
            ],
        ),
    ]
    if m["mismatch"]:
        out += ["", "결손 분석이 정답 `need`와 다른 하위 질의:", ""]
        out.append(
            _table(
                ["문항", "축", "하위 질의", "정답 `need`", "결손 분석 값"],
                [
                    [x["id"], x["axis"], x["query"], _names(x["need"]), _names(x["got"])]
                    for x in m["mismatch"]
                ],
            )  # fmt: skip
        )
    if m["unneeded"]:
        out += [
            "",
            "불필요한 질문이 있는 문항 — 질문마다 그 질문이 쓰인 시스템 NEED_INFO 하위 질의:",
            "",
        ]
        out.append(
            _table(
                [
                    "문항",
                    "공고",
                    "불필요한 질문",
                    "쓰인 하위 질의",
                    "정답 판정(규칙)",
                    "시스템 판정",
                ],
                [
                    [
                        x["id"],
                        x["notice_name"],
                        s["name"],
                        f"{s['axis']}: {s['query']}",
                        f"{s['gold']} ({s['gold_rule'] or '규칙 없음'})",
                        s["system"],
                    ]
                    for x in m["unneeded"]
                    for s in x["sources"]
                ],
            )  # fmt: skip
        )
        sources = [s for x in m["unneeded"] for s in x["sources"]]
        by_gap = [s for s in sources if s["gold_rule"] in NOT_PORTED]
        out += [
            "",
            f"- 위 표 {len(sources)}줄(불필요한 질문 × 쓰인 하위 질의) 중"
            " 정답 규칙이 이번에 옮기지 않은 규칙"
            f"({'·'.join(NOT_PORTED)}, 공고문 사실이 필요하다)인 것: **{len(by_gap)}줄**."
            " 시스템은 그 경로를 INELIGIBLE로 닫지 못해 질문이 남았다",
        ]
    out += [
        "",
        "## 실패 징후 2 — 빠진 질문이 늘었나",
        "",
        f"- 빠진 질문이 있는 문항: **{n_miss}개** (비교값 {n_miss_base}개: 같은 질문 거르기를"
        f" `runs/138` 판정에 돌린 값) → 구간 **{band_missing(n_miss, n_miss_base)}**"
        " (정상: 비교값 이하 / 다시 잰다: 1~3 많다 / 미완: 4 이상 많다)",
    ]
    if m["missing"]:
        out += ["", "빠진 질문이 있는 문항:", ""]
        out.append(
            _table(
                ["문항", "공고", "빠진 질문", "`runs/138` 판정에서도 빠졌나"],
                [
                    [
                        x["id"],
                        x["notice_name"],
                        _names(x["names"]),
                        "예"
                        if any(
                            b["id"] == x["id"] and b["names"] >= x["names"]
                            for b in m["missing_base"]
                        )
                        else "아니오",
                    ]
                    for x in m["missing"]
                ],
            )  # fmt: skip
        )
    out += [
        "",
        "## 실패 징후 3 — 규칙이 정답과 어긋났나",
        "",
        f"- 규칙이 INELIGIBLE로 정한 하위 질의 {len(hits)}개 중 정답 라벨이 INELIGIBLE이 아닌 것:"
        f" **{len(wrong)}개** → 구간 **{band_rule(len(wrong))}**"
        " (정상: 0 / 다시 잰다: 1~3 / 미완: 4 이상)",
    ]
    if wrong:
        out += [""]
        out.append(
            _table(
                ["문항", "규칙", "프로필 칸 값", "정답 라벨", "정답 이유"],
                [[h["id"], h["rule"], rule_values(h), h["gold"], h["gold_reason"]] for h in wrong],
            )
        )
    inconsistent = [h for h in hits if h["system"] != "INELIGIBLE"]
    out += [
        "- 규칙이 걸려야 하는데 `run.jsonl`의 시스템 판정이 INELIGIBLE이 아닌 하위 질의:"
        f" **{len(inconsistent)}개**",
        "",
        "## 실패 징후 4 — 치명오답",
        "",
        f"- 치명오답(정답 INELIGIBLE인데 시스템 ELIGIBLE): **{len(f_now)}개** (`runs/138`은"
        f" {len(f_base)}/91) → 구간 **{band_fatal(len(f_now))}**"
        " (정상: 2 이하 / 다시 잰다: 3~5 / 미완: 6 이상)",
    ]
    if len(f_now) > 2:
        out += [""]
        out.append(
            _table(
                ["문항", "축", "공고", "정답", "시스템"],
                [
                    [r["id"], r["axis"], r["notice_name"], r["gold_verdict"], r["sys_verdict"]]
                    for r in f_now
                ],
            )  # fmt: skip
        )
    mn, mb = metrics.compute(now), metrics.compute(base)
    out += [
        "",
        "## 지표 7개 — `runs/138` 대비 전후",
        "",
        "판정 지표는 이번 기준이 아니다. 값만 적는다."
        " 오른 것은 대부분 규칙이 INELIGIBLE을 낸 덕이다.",
        "",
    ]

    def pick(x, key):
        return x[key]["total"] if key == "judgment_accuracy" else x[key]

    out.append(
        _table(
            ["지표", "뜻", "#138", "#82"],
            [
                [label, mean, _pct(pick(mb, k)), _pct(pick(mn, k))]
                for k, label, mean in METRIC_NAMES
            ],
        )
    )
    counts = Counter((h["rule"], h["model"]) for h in hits)
    out += [
        "",
        f"## 규칙이 바꾼 하위 질의 — {len(changed)}개",
        "",
        f"규칙이 걸린 하위 질의 {len(hits)}개 중 모델 판정이 INELIGIBLE이 아니어서 규칙이 바꾼 것이"
        f" {len(changed)}개다. 모델 판정이 이미 INELIGIBLE이면 판정은 그대로이고"
        " 이유 문장만 규칙의 것이 된다.",
        "",
        _table(
            ["규칙", *[f"모델 {v}" for v in VERDICTS], "합"],
            [
                [
                    rid,
                    *[counts[(rid, v)] or "" for v in VERDICTS],
                    sum(counts[(rid, v)] for v in VERDICTS),
                ]
                for rid in dict.fromkeys(h["rule"] for h in hits)
            ],
        ),
        "",
        _table(
            ["모델 판정", "개수"],
            [[v, sum(1 for h in hits if h["model"] == v)] for v in VERDICTS],
        ),
    ]
    ex = example_item(golden, m)
    if ex:
        item = m["items"][ex["id"]]
        out += [
            "",
            f"## 질문 목록 예시 — 부분 프로필 문항 {ex['id']} ({ex['notice_name']})",
            "",
            f"- 프로필에 값이 있는 칸: {_names_of(ex['profile'])}",
            f"- 필요한 질문(정답 기준): {_names(item['need'])}",
            "",
            _table(
                ["차례", "정보 이름", "문장", "프로필 칸", "불가 판정을 낼 수 있음", "쓰이는 경로"],
                [
                    [i, q.name, q.text, "있음" if q.has_field else "입력란 없음",
                     "예" if q.can_rule_out else "", " · ".join(q.routes)]
                    for i, q in enumerate(item["asked"], 1)
                ],
            ),
        ]  # fmt: skip
    out += ["", "## 설계 §4 — 숫자 읽는 법", ""]
    out += [f"- {s}" for s in DESIGN_SECTION_4]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.questions_report")
    ap.add_argument("--now", type=Path, default=NOW_DIR)
    ap.add_argument("--base", type=Path, default=BASE_DIR)
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)
    try:
        golden = read_rows(args.golden)
        now, base = read_rows(args.now / "run.jsonl"), read_rows(args.base / "run.jsonl")
        engine = sa.create_engine(settings.database_url)
        try:
            facts = load_facts(engine, golden)
        finally:
            engine.dispose()
        md = render(golden, now, base, measure(golden, now, base, facts))
    except (OSError, ValueError, KeyError) as e:
        print(f"읽기 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    write(args.out, md)
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
