"""골든셋 검사 (#75).

    python -m cheongyak_rag.golden.check [--golden PATH] [--notices PATH]

통과 기준 1~5(줄 수·칸·켜진 하위 질의마다 라벨·프로필)와 글자 대조(실패 징후 2)를 검사하고,
어긋난 것을 줄마다 출력한다. 하나라도 있으면 종료 코드 1이다. 실패 징후 3·4·6의 값도 함께 찍는다.
`agreement`는 따로 붙인 라벨과의 일치율(실패 징후 1)을 센다.
"""

import argparse
import dataclasses
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from cheongyak_rag import profile as prof
from cheongyak_rag.config import settings
from cheongyak_rag.golden.text import article_text, pdf_pages, quote_in
from cheongyak_rag.profile import Profile
from cheongyak_rag.retrieval import axes

LAW_MST = "286965"
VERDICTS = ("ELIGIBLE", "INELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE")
PROFILE_FIELDS = tuple(f.name for f in dataclasses.fields(Profile))
EXPECT = {"rows": 50, "notices": 20, "kinds": {"full": 20, "partial": 22, "empty": 8}}
ROW_KEYS = {
    "id", "house_manage_no", "pblanc_no", "notice_name", "as_of", "profile_kind", "profile",
    "labels",
}  # fmt: skip
LABEL_KEYS = {
    "axis", "query", "verdict", "reason", "fields", "need", "citations", "article_quotes",
    "notice_evidence", "rule", "rule_note",
}  # fmt: skip
_ARTICLE = re.compile(r"^제\d+조(의\d+)?$")
_ROW_ID = re.compile(r"^g\d{2}$")
DEFAULT_GOLDEN = Path("runs/75/golden.jsonl")
DEFAULT_NOTICES = Path("runs/75/notices.json")


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    quote_mismatches: int = 0
    stats: dict = field(default_factory=dict)


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v)


def _check_profile(r: dict, add) -> None:
    p = r["profile"]
    if not isinstance(p, dict) or set(p) != set(PROFILE_FIELDS):
        add(f"{r['id']}: 프로필 칸이 15개가 아니다")
        return
    filled = [k for k, v in p.items() if v is not None]
    kind = r["profile_kind"]
    if kind == "full" and len(filled) != len(PROFILE_FIELDS):
        add(
            f"{r['id']}: 꽉 찬 프로필인데 빈 칸이 있다"
            f" ({sorted(set(PROFILE_FIELDS) - set(filled))})"
        )
    elif kind == "empty" and filled:
        add(f"{r['id']}: 빈 프로필인데 값이 있는 칸이 있다 ({filled})")
    elif kind == "partial" and not (0 < len(filled) < len(PROFILE_FIELDS)):
        add(f"{r['id']}: 일부 프로필은 값이 있는 칸과 빈 칸이 둘 다 있어야 한다")
    elif kind not in EXPECT["kinds"]:
        add(f"{r['id']}: 프로필 종류가 full·partial·empty가 아니다 ({kind!r})")
    try:
        prof.score(Profile.from_dict(p), date.fromisoformat(r["as_of"]))
    except (prof.ProfileError, ValueError) as e:
        add(f"{r['id']}: 프로필을 읽는 데 실패했다 — {e}")


def _check_label(r: dict, lb: dict, add, article_of, pages, counter: list) -> None:
    tag = f"{r['id']} {lb.get('axis')}"
    if set(lb) != LABEL_KEYS:
        add(
            f"{tag}: 라벨 칸이 다르다 (빠짐 {sorted(LABEL_KEYS - set(lb))},"
            f" 더 있음 {sorted(set(lb) - LABEL_KEYS)})"
        )
        return
    if lb["verdict"] not in VERDICTS:
        add(f"{tag}: 판정값이 5개 중 하나가 아니다 ({lb['verdict']!r})")
    if not (isinstance(lb["reason"], str) and lb["reason"].strip()):
        add(f"{tag}: reason이 비었다")
    if not (_is_str_list(lb["fields"]) and set(lb["fields"]) <= set(PROFILE_FIELDS)):
        add(f"{tag}: fields가 프로필 칸 이름 목록이 아니다 ({lb['fields']!r})")
    if not _is_str_list(lb["need"]):
        add(f"{tag}: need가 문자열 목록이 아니다")
    elif (lb["verdict"] == "NEED_INFO") != bool(lb["need"]):
        add(
            f"{tag}: NEED_INFO일 때만 need가 비어 있지 않아야 한다"
            f" (verdict={lb['verdict']}, need={lb['need']})"
        )
    cites = lb["citations"]
    if not (_is_str_list(cites) and cites and all(_ARTICLE.match(c) for c in cites)):
        add(f"{tag}: citations가 `제N조` 꼴 1개 이상이어야 한다 ({cites!r})")
        cites = []
    quotes = lb["article_quotes"]
    if not isinstance(quotes, dict) or set(quotes) != set(cites):
        add(f"{tag}: article_quotes의 조 라벨이 citations와 다르다")
        quotes = {}
    for label, quote in quotes.items():
        body = article_of(label)
        if body is None:
            counter[0] += 1
            add(f"{tag}: 존재하지 않는 조 {label}")
        elif not isinstance(quote, str) or not quote_in(quote, body):
            counter[0] += 1
            add(f"{tag}: {label}에 없는 구절 「{quote}」")
    if not isinstance(lb["notice_evidence"], list):
        add(f"{tag}: notice_evidence가 목록이 아니다")
    else:
        for ev in lb["notice_evidence"]:
            _check_page_quote(f"{tag} 공고문 근거", ev, pages, add, counter)
    if lb["rule"] is None:
        if not (isinstance(lb["rule_note"], str) and lb["rule_note"].strip()):
            add(f"{tag}: rule이 null이면 rule_note에 이유가 있어야 한다")
    elif not isinstance(lb["rule"], str) or lb["rule_note"] is not None:
        add(f"{tag}: rule이 있으면 rule_note는 null이어야 한다")


def _check_page_quote(tag: str, ev: dict, pages: list[str], add, counter: list) -> None:
    page, quote = ev.get("page"), ev.get("quote")
    if not (isinstance(page, int) and 1 <= page <= len(pages)):
        counter[0] += 1
        add(f"{tag}: 쪽 번호가 PDF 범위 밖이다 ({page!r}, 전체 {len(pages)}쪽)")
    elif not isinstance(quote, str) or not quote_in(quote, pages[page - 1]):
        counter[0] += 1
        add(f"{tag}: {page}쪽에 없는 구절 「{quote}」")


def check_rows(rows, notices, *, plan_of, article_of, pages_of, expect_counts=EXPECT) -> Report:
    """줄마다 통과 기준 1~5와 글자 대조를 본다.

    notices: 관리번호 → notices.json의 공고 한 건. plan_of(관리번호, 공고번호) → [(축, 하위 질의)],
    article_of(조 라벨) → 본문 또는 None, pages_of(관리번호) → 쪽마다 글자.
    """
    rep = Report()
    add = rep.problems.append
    counter = [0]
    if expect_counts:
        if len(rows) != expect_counts["rows"]:
            add(f"문항 50줄이어야 하는데 {len(rows)}줄이다")
        if len({r["house_manage_no"] for r in rows}) != expect_counts["notices"]:
            add(f"공고 20건이어야 하는데 {len({r['house_manage_no'] for r in rows})}건이다")
        kinds = Counter(r["profile_kind"] for r in rows)
        if dict(kinds) != expect_counts["kinds"]:
            add(f"프로필 종류가 꽉 찬 20·일부 22·빈 8이 아니다 ({dict(kinds)})")
        want_ids = {f"g{i:02d}" for i in range(1, expect_counts["rows"] + 1)}
        if {r["id"] for r in rows} != want_ids:
            add("id가 g01~g50이 아니다")
    verdicts: Counter = Counter()
    by_axis: Counter = Counter()
    inel_axes: set = set()
    null_rules = n_labels = 0
    for r in rows:
        if set(r) != ROW_KEYS:
            add(
                f"{r.get('id')}: 문항 칸이 다르다 (빠짐 {sorted(ROW_KEYS - set(r))},"
                f" 더 있음 {sorted(set(r) - ROW_KEYS)})"
            )
            continue
        if not _ROW_ID.match(r["id"]):
            add(f"{r['id']}: id가 g01 꼴이 아니다")
        n = notices.get(r["house_manage_no"])
        if n is None:
            add(f"{r['id']}: 공고 {r['house_manage_no']}가 notices.json에 없다")
            continue
        if n["as_of"] != r["as_of"]:
            add(f"{r['id']}: as_of {r['as_of']}가 공고의 모집공고일 {n['as_of']}와 다르다")
        _check_profile(r, add)
        pages = pages_of(r["house_manage_no"])
        want = plan_of(r["house_manage_no"], r["pblanc_no"])
        got = [(lb.get("axis"), lb.get("query")) for lb in r["labels"]]
        on_axes = {a for a, _ in want}
        for a, q in want:
            if got.count((a, q)) == 0:
                add(f"{r['id']}: 라벨 없는 하위 질의 {a} 「{q}」")
            elif got.count((a, q)) > 1:
                add(f"{r['id']}: 같은 하위 질의에 라벨이 둘 이상이다 {a} 「{q}」")
        for a, q in got:
            if a not in on_axes:
                add(f"{r['id']}: 켜지지 않은 축의 라벨 {a}")
            elif (a, q) not in want:
                add(f"{r['id']}: 하위 질의 문장이 axes.plan과 다르다 {a} 「{q}」")
        for lb in r["labels"]:
            _check_label(r, lb, add, article_of, pages, counter)
            n_labels += 1
            verdicts[lb.get("verdict")] += 1
            by_axis[lb.get("axis")] += 1
            if lb.get("verdict") == "INELIGIBLE":
                inel_axes.add(lb.get("axis"))
            null_rules += lb.get("rule") is None
    rep.quote_mismatches = counter[0]
    rep.stats = {
        "labels": n_labels,
        "verdicts": {v: verdicts.get(v, 0) for v in VERDICTS},
        "by_axis": dict(sorted(by_axis.items())),
        "ineligible_axes": sorted(inel_axes),
        "rule_null": null_rules,
        "rule_null_ratio": null_rules / n_labels if n_labels else 0.0,
    }
    return rep


def check_notices(notices: list[dict], *, pages_of) -> list[str]:
    """notices.json의 공고문 사실 구절이 그 쪽 글자에 있는지 본다. 어긋난 것을 줄마다 돌려준다."""
    bad: list[str] = []
    for n in notices:
        facts = n.get("facts") or {}
        pages = pages_of(n["house_manage_no"])
        items = [("regulation." + k, v) for k, v in (facts.get("regulation") or {}).items()]
        items += [
            (k, facts[k])
            for k in ("residence", "account_first_rank", "householder", "rewin")
            if k in facts
        ]
        items += [("special_types." + s["type"], s) for s in facts.get("special_types", [])]
        items += [("db_mismatch." + m["칸"], m) for m in n.get("db_mismatch", [])]
        for name, it in items:
            if it.get("quote") is None and it.get("page") is None:
                continue
            _check_page_quote(f"{n['house_manage_no']} {name}", it, pages, bad.append, [0])
    return bad


def agreement(first: list[dict], second: list[dict]) -> dict:
    """첫 라벨과 따로 붙인 라벨을 (문항, 축, 하위 질의)로 맞춰 판정값·조 라벨이 다른 수를 센다."""
    sec = {(r["id"], lb["axis"], lb["query"]): lb for r in second for lb in r["labels"]}
    diffs, by_axis = [], {}
    v_diff = c_diff = total = 0
    for r in first:
        for lb in r["labels"]:
            total += 1
            other = sec.get((r["id"], lb["axis"], lb["query"]))
            ax = by_axis.setdefault(
                lb["axis"], {"labels": 0, "verdict_diff": 0, "citation_diff": 0}
            )
            ax["labels"] += 1
            v = other is None or other["verdict"] != lb["verdict"]
            c = other is None or not (set(other["citations"]) & set(lb["citations"]))
            if v or c:
                diffs.append({
                    "id": r["id"], "axis": lb["axis"], "query": lb["query"],
                    "first_verdict": lb["verdict"], "second_verdict": other and other["verdict"],
                    "first_citations": lb["citations"],
                    "second_citations": other and other["citations"],
                    "kind": "both" if v and c else "verdict" if v else "citation",
                })  # fmt: skip
            v_diff += v
            c_diff += c
            ax["verdict_diff"] += v
            ax["citation_diff"] += c
    return {
        "labels": total,
        "verdict_diff": v_diff,
        "citation_diff": c_diff,
        "verdict_diff_ratio": v_diff / total if total else 0.0,
        "citation_diff_ratio": c_diff / total if total else 0.0,
        "by_axis": by_axis,
        "diffs": diffs,
    }


# ── CLI ──────────────────────────────────────────────────────────────────


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def run_check(golden: Path, notices_path: Path, engine) -> tuple[Report, list[str]]:
    rows = load_jsonl(golden)
    notices = json.loads(notices_path.read_text(encoding="utf-8"))["notices"]
    by_no = {n["house_manage_no"]: n for n in notices}
    cache: dict[str, list[str]] = {}
    plans: dict[tuple, list] = {}
    bodies: dict[str, str | None] = {}

    def pages_of(h):
        if h not in cache:
            cache[h] = pdf_pages(by_no[h]["pdf"])
        return cache[h]

    def plan_of(h, p):
        if (h, p) not in plans:
            plans[(h, p)] = [(a.id, q) for a in axes.plan(engine, h, p) if a.on for q in a.queries]
        return plans[(h, p)]

    def article_of(label):
        if label not in bodies:
            bodies[label] = article_text(engine, LAW_MST, label)
        return bodies[label]

    rep = check_rows(rows, by_no, plan_of=plan_of, article_of=article_of, pages_of=pages_of)
    notice_bad = check_notices(notices, pages_of=pages_of)
    rep.quote_mismatches += len(notice_bad)
    return rep, notice_bad


def main(argv: list[str] | None = None, *, engine=None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.golden.check")
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--notices", type=Path, default=DEFAULT_NOTICES)
    args = ap.parse_args(argv)
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        rep, notice_bad = run_check(args.golden, args.notices, engine)
    finally:
        if own:
            engine.dispose()
    for line in [*rep.problems, *notice_bad]:
        print(line)
    st = rep.stats
    print(f"라벨 {st['labels']}개 · 판정값 {st['verdicts']}")
    print(
        f"INELIGIBLE 축 {len(st['ineligible_axes'])}개 {st['ineligible_axes']} · "
        f"rule null {st['rule_null']}개 ({st['rule_null_ratio']:.1%})"
    )
    print(
        f"글자 대조 어긋난 구절 {rep.quote_mismatches}개"
        f" · 줄 단위 문제 {len(rep.problems) + len(notice_bad)}건"
    )
    return 1 if rep.problems or notice_bad else 0


if __name__ == "__main__":
    sys.exit(main())
