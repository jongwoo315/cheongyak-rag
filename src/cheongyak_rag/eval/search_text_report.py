"""#138 검색 문장 리포트 — `runs/76`과 `runs/138`의 `run.jsonl`에서 실패 징후 1~4를 센다.

python -m cheongyak_rag.eval.search_text_report [--base runs/76] [--now runs/138]
    [--out docs/138-search-text.md]
python -m cheongyak_rag.eval.search_text_report --search-only

`--search-only`는 판정(OpenAI)을 부르지 않고 골든셋 공고로 축별 검색만 돌려 실패 징후 1·2의
검색 쪽 값을 stdout에 낸다. DB는 읽기만 한다. 구간 이름과 경계는 plan §실패 징후의 것이다.
"""

import argparse
import json
import sys
from pathlib import Path

import sqlalchemy as sa

from cheongyak_rag.config import settings
from cheongyak_rag.eval.metrics import is_law
from cheongyak_rag.eval.report import METRIC_NAMES
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import write

ROOT = Path(__file__).resolve().parents[3]
BASE_DIR = ROOT / "runs/76"
NOW_DIR = ROOT / "runs/138"
GOLDEN = ROOT / "runs/75/golden.jsonl"
OUT_MD = ROOT / "docs/138-search-text.md"

JW_CRITERIA = "청약통장·기관추천 두 질문이 상위 5개에 정답 조문을 올리면 성공"
Q_INSTT = axes.Q_SPECIAL.format(type="기관추천")
GROUPS = (("account", "청약통장"), ("instt", "기관추천"))
# 주택 구분 → 정답 근거 조문이 어긋난 짝. 민영(01)은 제28조·제36조, 국민(03)은 제27조·제35조다
WRONG = {
    "account": {"01": "제27조", "03": "제28조"},
    "instt": {"01": "제35조", "03": "제36조"},
}


WRONG_HOUSES = ("01", "03")


def group(r: dict) -> str | None:
    if r["axis"] == "account":
        return "account"
    if r["axis"] == "special_type" and r["query"] == Q_INSTT:
        return "instt"
    return None


def has_law_gold(r: dict) -> bool:
    return any(is_law(c) for c in r["gold_citations"])


def hit(r: dict) -> bool:
    return bool(set(r["gold_citations"]) & set(r["law_top5"]))


# ── 실패 징후 1: jw 기준 ─────────────────────────────────────────────────


def jw(rows: list[dict]) -> dict:
    """정답 근거 조문이 있는 하위 질의 중 `law_top5`에 정답 근거 조문이 하나 이상 든 수 / 전체."""
    out = {}
    for g, _ in GROUPS:
        sel = [r for r in rows if group(r) == g and has_law_gold(r)]
        missed = [r for r in sel if not hit(r)]
        out[g] = {"hit": len(sel) - len(missed), "den": len(sel), "missed": missed}
    return out


def band_jw(j: dict) -> str:
    """통과: 둘 다 전부 / 미완: 하나라도 절반 이하(분모 0 포함) / 그 사이는 다시 잰다."""
    parts = [j[g] for g, _ in GROUPS]
    if any(p["den"] == 0 or p["hit"] * 2 <= p["den"] for p in parts):
        return "미완"
    return "통과" if all(p["hit"] == p["den"] for p in parts) else "다시 잰다"


# ── 실패 징후 2: 다른 축으로 샜나 ────────────────────────────────────────


def _key(r: dict) -> tuple:
    return (r["id"], r["axis"], r["query"])


def leak(base: list[dict], now: list[dict]) -> list[dict]:
    """①·② 밖의 하위 질의 중 `law_top5`가 두 실행에서 글자까지 다른 것(빠진 줄 포함)."""
    now_by = {_key(r): r for r in now}
    out = []
    for r in base:
        if group(r) is not None:
            continue
        other = now_by.get(_key(r))
        got = other["law_top5"] if other else None
        if got != r["law_top5"]:
            out.append(
                {"id": r["id"], "axis": r["axis"], "query": r["query"],
                 "base": r["law_top5"], "now": got}
            )  # fmt: skip
    return out


def band_leak(n: int) -> str:
    return "정상" if n == 0 else "다시 잰다" if n <= 5 else "미완"


# ── 실패 징후 3: 주택 구분과 정답 근거 조문 ──────────────────────────────


def house_mismatch(rows: list[dict], house: dict[str, str | None]) -> list[dict]:
    """주택 구분과 정답 근거 조문이 어긋난 하위 질의. 주택 구분이 `01`·`03`이 아니면 세지 않는다."""
    out = []
    for r in rows:
        g = group(r)
        if g is None:
            continue
        wrong = WRONG[g].get(house.get(r["id"]))
        if wrong and wrong in r["gold_citations"]:
            out.append({**r, "house": house[r["id"]], "wrong": wrong})
    return out


def band_house(n: int) -> str:
    return "정상" if n == 0 else "다시 잰다" if n <= 3 else "미완"


# ── 실패 징후 4: 치명오답 ────────────────────────────────────────────────


def fatal(rows: list[dict]) -> tuple[list[dict], int]:
    """(정답이 INELIGIBLE인데 시스템이 ELIGIBLE을 낸 줄, 정답이 INELIGIBLE인 줄 수)."""
    gold = [r for r in rows if r["gold_verdict"] == "INELIGIBLE"]
    return [r for r in gold if r["sys_verdict"] == "ELIGIBLE"], len(gold)


def band_fatal(n: int) -> str:
    return "정상" if n <= 2 else "다시 잰다" if n <= 5 else "미완"


# ── 검색만 돌리기 ────────────────────────────────────────────────────────


def search_only_lines(gold_row: dict, results: list) -> list[dict]:
    """골든셋 문항 하나의 정답 라벨마다 검색 결과를 붙인 줄 — `run.jsonl` 줄 중 쓰는 칸만 낸다."""
    top = {(r.id, h.query): [c.label for c in h.law] for r in results for h in r.hits}
    out = []
    for g in gold_row["labels"]:
        got = top.get((g["axis"], g["query"]))
        out.append(
            {"id": gold_row["id"], "axis": g["axis"], "query": g["query"],
             "gold_citations": g["citations"], "law_top5": got or [], "matched": got is not None}
        )  # fmt: skip
    return out


def run_search_only(engine, embedder, golden_rows: list[dict]) -> list[dict]:
    cache: axes.Cache = {}
    lines = []
    for row in golden_rows:
        plans = axes.plan_from_facts(
            axes.load_facts(engine, row["house_manage_no"], row["pblanc_no"])[2]
        )
        results = axes.search(
            engine, embedder, row["house_manage_no"], row["pblanc_no"], plans=plans, cache=cache
        )
        lines += search_only_lines(row, results)
    return lines


def house_by_id(engine, golden_rows: list[dict]) -> dict[str, str | None]:
    sql = sa.text(
        "SELECT house_dtl_secd FROM notices WHERE house_manage_no = :h AND pblanc_no = :p"
    )
    with engine.connect() as conn:
        return {
            r["id"]: conn.execute(sql, {"h": r["house_manage_no"], "p": r["pblanc_no"]}).scalar()
            for r in golden_rows
        }


# ── 리포트 ───────────────────────────────────────────────────────────────


def read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def read_metrics(run_dir: Path) -> dict:
    return json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], body: list[list]) -> str:
    rows = [head, ["---"] * len(head), *body]
    return "\n".join("| " + " | ".join(_cell(c) for c in r) + " |" for r in rows)


def _metric(m: dict) -> dict:
    return m["total"] if "total" in m else m


def _pct(m: dict) -> str:
    return "—" if m["value"] is None else f"{m['value'] * 100:.1f}% ({m['num']}/{m['den']})"


def _top(labels: list[str] | None) -> str:
    return "없음" if labels is None else "·".join(labels) or "비었다"


def render(base: list[dict], now: list[dict], house: dict, base_m: dict, now_m: dict) -> str:
    j0, j1 = jw(base), jw(now)
    band1 = band_jw(j1)
    leaks = leak(base, now)
    bad_house = house_mismatch(now, house)
    unknown_house = {r["id"] for r in now if group(r) and house.get(r["id"]) not in WRONG_HOUSES}
    f0, d0 = fatal(base)
    f1, d1 = fatal(now)
    out = [
        "# #138 검색 문장 — 청약통장·기관추천 하위 질의의 정답 근거 조문 검색",
        "",
        "측정: `runs/76/run.jsonl`(#76)과 `runs/138/run.jsonl`(이번)을 읽어"
        " 이 파일의 코드가 센 값이다. 바뀐 것은 청약통장·기관추천 하위 질의의 검색 문장 하나다"
        "(설계 `docs/plans/138-1112-design-search-text.md` §3).",
        "",
        "## jw 기준",
        "",
        f"「{JW_CRITERIA}」",
        "",
        f"- 구간: **{band1}** (통과: ①·② 둘 다 전부 들었다 / 다시 잰다: 둘 다 절반 넘게 들었지만"
        " 하나라도 전부가 아니다 / 미완: 하나라도 절반 이하)",
    ]
    out += [""]
    out.append(
        _table(
            ["하위 질의", "정답 근거 조문이 `law_top5`에 든 수 / 전체", "#76"],
            [
                [
                    f"{'①②'[i]} {name}",
                    f"{j1[g]['hit']}/{j1[g]['den']}",
                    f"{j0[g]['hit']}/{j0[g]['den']}",
                ]
                for i, (g, name) in enumerate(GROUPS)
            ],
        )
    )
    for g, name in GROUPS:
        missed = j1[g]["missed"]
        if missed:
            out += ["", f"{name}에서 못 든 하위 질의 {len(missed)}개:", ""]
            out.append(
                _table(
                    ["문항", "공고", "정답 근거 조문", "`law_top5`", "주택 구분"],
                    [
                        [
                            r["id"],
                            r["notice_name"],
                            "·".join(r["gold_citations"]),
                            _top(r["law_top5"]),
                            house.get(r["id"]),
                        ]
                        for r in missed
                    ],
                )  # fmt: skip
            )
    out += [
        "",
        "## 실패 징후 2 — 다른 축으로 샜나",
        "",
        "- 청약통장·기관추천 밖의 하위 질의 중 `law_top5`가 #76과 글자까지 다른 것:"
        f" **{len(leaks)}개** → 구간 **{band_leak(len(leaks))}**"
        " (정상: 0 / 다시 잰다: 1~5 / 미완: 6 이상)",
    ]
    if leaks:
        out += [""]
        out.append(
            _table(
                ["문항", "축", "하위 질의", "#76 `law_top5`", "이번 `law_top5`"],
                [[d["id"], d["axis"], d["query"], _top(d["base"]), _top(d["now"])] for d in leaks],
            )
        )
    out += [
        "",
        "## 실패 징후 3 — 주택 구분과 정답 근거 조문",
        "",
        "- 민영(`01`)은 제28조·제36조, 국민(`03`)은 제27조·제35조가 정답 근거 조문이어야 한다"
        "(`docs/75-label-rules.md`). 어긋난 짝을 센다",
        f"- 어긋난 하위 질의: **{len(bad_house)}개**"
        f" → 구간 **{band_house(len(bad_house))}** (정상: 0 / 다시 잰다: 1~3 / 미완: 4 이상)",
        f"- 주택 구분이 `01`·`03`이 아니거나 비어서 세지 못한 공고: **{len(unknown_house)}개**",
    ]
    if bad_house:
        out += [""]
        out.append(
            _table(
                ["문항", "공고", "축", "주택 구분", "정답 근거 조문"],
                [
                    [
                        r["id"],
                        r["notice_name"],
                        r["axis"],
                        r["house"],
                        "·".join(r["gold_citations"]),
                    ]
                    for r in bad_house
                ],
            )
        )
    out += [
        "",
        "## 실패 징후 4 — 치명오답",
        "",
        f"- 치명오답(정답이 `INELIGIBLE`인데 시스템이 `ELIGIBLE`): **{len(f1)}/{d1}**,"
        f" #76은 {len(f0)}/{d0} → 구간 **{band_fatal(len(f1))}**"
        " (정상: 2 이하 / 다시 잰다: 3~5 / 미완: 6 이상)",
    ]
    if f1:
        out += [""]
        out.append(
            _table(
                ["문항", "공고", "축", "정답 라벨", "시스템 판정", "인용 조문"],
                [
                    [
                        r["id"],
                        r["notice_name"],
                        r["axis"],
                        r["gold_verdict"],
                        r["sys_verdict"],
                        "·".join(c for c in r["sys_citations"] if is_law(c)),
                    ]
                    for r in f1
                ],
            )  # fmt: skip
        )
    out += [
        "",
        "## 지표 7개 — #76 대비 전후",
        "",
        "판정 지표(판정 정확도·정당 abstain·부당 abstain·citation precision)는 이번 기준이 아니다."
        " 검색 문맥이 바뀌어 판정을 새로 돌렸으므로 같이 움직인다. 전후 값만 적는다.",
        "",
    ]
    body = []
    for key, name, _ in METRIC_NAMES:
        a, b = _metric(base_m["metrics"][key]), _metric(now_m["metrics"][key])
        body.append([name, _pct(a), _pct(b)])
    out.append(_table(["지표", "#76", "이번"], body))
    out += [
        "",
        "- 시스템에만 있는 하위 질의(`unmatched_system_queries`):"
        f" #76 {base_m['counts']['unmatched_system_queries']},"
        f" 이번 {now_m['counts']['unmatched_system_queries']}",
        f"- 이번 실행 비용 ${now_m['usd']:.4f}, 멈춤: {now_m['stop'] or '없음'}",
        "",
        "## 숫자를 읽을 때 알아야 할 것",
        "",
        "- 검색 문장은 정답 근거 조문과 그 본문을 보고 썼다. 골든셋이 유일한 측정 데이터라"
        " 따로 떼어 둔 확인용 문항이 없다."
        " 이번 결과가 통과여도 「다른 질문에도 이 방식이 듣는다」는 뜻이 아니다",
        "",
    ]
    return "\n".join(out)


def _search_only(args) -> int:
    golden = read_rows(args.golden)
    engine = sa.create_engine(settings.database_url)
    try:
        lines = run_search_only(engine, Embedder(settings.openai_embed_model), golden)
    finally:
        engine.dispose()
    base = read_rows(args.base / "run.jsonl")
    j0, j1 = jw(base), jw(lines)
    for g, name in GROUPS:
        print(f"jw {name}: {j1[g]['hit']}/{j1[g]['den']} (#76 {j0[g]['hit']}/{j0[g]['den']})")
    print(f"jw 구간: {band_jw(j1)}")
    diffs = leak(base, lines)
    print(f"다른 축으로 샌 하위 질의: {len(diffs)} → {band_leak(len(diffs))}")
    for d in diffs:
        print(f"  {d['id']} {d['axis']} {d['query']}: {_top(d['base'])} → {_top(d['now'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.eval.search_text_report")
    ap.add_argument("--base", type=Path, default=BASE_DIR)
    ap.add_argument("--now", type=Path, default=NOW_DIR)
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--out", type=Path, default=OUT_MD)
    ap.add_argument("--search-only", action="store_true", help="판정 없이 검색만 돌려 값을 낸다")
    args = ap.parse_args(argv)
    try:
        if args.search_only:
            return _search_only(args)
        golden = read_rows(args.golden)
        engine = sa.create_engine(settings.database_url)
        try:
            house = house_by_id(engine, golden)
        finally:
            engine.dispose()
        md = render(
            read_rows(args.base / "run.jsonl"), read_rows(args.now / "run.jsonl"), house,
            read_metrics(args.base), read_metrics(args.now),
        )  # fmt: skip
    except (OSError, ValueError, KeyError) as e:
        print(f"읽기 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    write(args.out, md)
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
