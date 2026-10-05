"""법령 JSONL을 원본 JSON과 맞대는 대조 코드 (#69).

파서(`law.py`)를 부르지 않는다. 같은 코드로 세면 같은 버그가 양쪽에 들어가서 대조가 항상 통과한다.
원본 쪽은 JSON을 재귀로 훑고, 출력 쪽은 JSONL 줄(dict)만 읽는다.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

TEXT_KEYS = ("조문내용", "항내용", "호내용", "목내용")
COUNT_LEVELS = ("조문", "장절", "항", "호", "목")


@dataclass(frozen=True)
class Field:
    where: str  # `제3조`, 장·절 제목이면 `장절`
    text: str  # 공백을 하나로 접은 내용


@dataclass
class Check:
    missing: list[Field]  # 원본에 있는데 출력에 없다
    duplicated: list[Field]  # 출력에 원본보다 더 많이 들어갔다
    extra: list[Field]  # 원본에 없는 내용이 출력에 있다 (내용이 바뀐 경우)
    source_counts: dict[str, int] = field(default_factory=dict)
    output_counts: dict[str, int] = field(default_factory=dict)
    source_field_count: int = 0
    output_field_count: int = 0

    @property
    def ok(self) -> bool:
        clean = not (self.missing or self.duplicated or self.extra)
        return clean and self.source_counts == self.output_counts


def _norm(s: str) -> str:
    return " ".join(s.split())


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for n in node:
            yield from _strings(n)


def _units(law_json: dict) -> list[dict]:
    units = law_json["법령"]["조문"]["조문단위"]
    return [units] if isinstance(units, dict) else units


def _label(unit: dict) -> str:
    branch = unit.get("조문가지번호")
    return f"제{unit['조문번호']}조" + (f"의{branch}" if branch else "")


# ── 원본 쪽 ──────────────────────────────────────────────────────────────


def source_fields(law_json: dict) -> list[Field]:
    """원본 조문 트리의 텍스트 필드를 전부 모은다. 어느 깊이에 어떤 모양으로 있든 훑는다."""
    found: list[Field] = []

    def walk(node, where: str) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, where)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in TEXT_KEYS:
                    text = _norm(" ".join(_strings(value)))
                    if text:
                        found.append(Field(where, text))
                elif isinstance(value, dict | list):
                    walk(value, where)

    for unit in _units(law_json):
        walk(unit, "장절" if unit["조문여부"] == "전문" else _label(unit))
    return found


def _count_key(node, key: str) -> int:
    """키 아래 노드 수. 하나면 dict, 여럿이면 list로 온다."""
    total = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                total += len(v) if isinstance(v, list) else 1
            total += _count_key(v, key)
    elif isinstance(node, list):
        total += sum(_count_key(n, key) for n in node)
    return total


def source_counts(law_json: dict) -> dict[str, int]:
    units = _units(law_json)
    counts = {
        "조문": sum(u["조문여부"] == "조문" for u in units),
        "장절": sum(u["조문여부"] == "전문" for u in units),
    }
    counts.update({level: _count_key(units, level) for level in ("항", "호", "목")})
    return counts


# ── 출력 쪽 ──────────────────────────────────────────────────────────────


def _headings(rows: list[dict]) -> list[str]:
    """출력에서 장·절 제목은 뒤따르는 조문마다 반복된다. 제목 하나를 한 번만 센다."""
    seen: list[tuple] = []
    for r in rows:
        for key in ((r["chapter"],), (r["chapter"], r["section"])):
            if key[-1] is not None and key not in seen:
                seen.append(key)
    return [key[-1] for key in seen]


def output_fields(rows: list[dict]) -> list[Field]:
    found = [Field("장절", _norm(h)) for h in _headings(rows)]
    for r in rows:
        where = r["label"]
        texts = [r["text"]]
        for p in r["paragraphs"]:
            texts.append(p["text"])
            for i in p["items"]:
                texts.append(i["text"])
                texts.extend(s["text"] for s in i["subitems"])
        found.extend(Field(where, _norm(t)) for t in texts if _norm(t))
    return found


def output_counts(rows: list[dict]) -> dict[str, int]:
    paragraphs = [p for r in rows for p in r["paragraphs"]]
    items = [i for p in paragraphs for i in p["items"]]
    return {
        "조문": len(rows),
        "장절": len(_headings(rows)),
        "항": len(paragraphs),
        "호": len(items),
        "목": sum(len(i["subitems"]) for i in items),
    }


# ── 대조 ─────────────────────────────────────────────────────────────────


def check(law_json: dict, rows: list[dict]) -> Check:
    src, out = source_fields(law_json), output_fields(rows)
    src_n, out_n = Counter(f.text for f in src), Counter(f.text for f in out)
    missing_n, surplus_n = src_n - out_n, out_n - src_n

    def pick(fields: list[Field], budget: Counter) -> list[Field]:
        budget, picked = Counter(budget), []
        for f in fields:
            if budget[f.text] > 0:
                budget[f.text] -= 1
                picked.append(f)
        return picked

    surplus = pick(out, surplus_n)
    return Check(
        missing=pick(src, missing_n),
        duplicated=[f for f in surplus if f.text in src_n],
        extra=[f for f in surplus if f.text not in src_n],
        source_counts=source_counts(law_json),
        output_counts=output_counts(rows),
        source_field_count=len(src),
        output_field_count=len(out),
    )


# ── 별표·부칙 (본문은 이번 범위 밖 — 개수와 제목만) ─────────────────────────


@dataclass
class Appendix:
    table_titles: list[str]  # `별표 1 가점제 적용기준(제2조제8호 관련)`
    supplement_count: int


def _as_list(node) -> list:
    if node is None:
        return []
    return [node] if isinstance(node, dict) else node


def appendix_summary(law_json: dict) -> Appendix:
    law = law_json["법령"]
    titles = []
    for t in _as_list(law.get("별표", {}).get("별표단위")):
        branch = int(t.get("별표가지번호") or 0)
        no = f"{int(t['별표번호'])}" + (f"의{branch}" if branch else "")
        titles.append(f"별표 {no} {t['별표제목']}")
    return Appendix(titles, len(_as_list(law.get("부칙", {}).get("부칙단위"))))


# ── 실패 징후 3: #70 FAQ 인용과 현행 법령 대조 ────────────────────────────

ARTICLE_REF = re.compile(r"제(\d+)조(?:의(\d+))?")


@dataclass
class FaqCross:
    pair_count: int
    cutoff: str  # FAQ 기준일. 이보다 늦은 날짜가 붙은 개정만 센다
    cited_label_count: int  # 인용된 조(가지 포함)의 종류 수
    missing_labels: list[str]  # 현행에 없는 조. 다른 법령 조문이 섞여 있다
    pairs_citing_missing: int
    amended_labels: list[str]  # 현행에 있고 cutoff 뒤에 개정 날짜가 붙은 조
    pairs_citing_amended: int


def _label_key(label: str) -> tuple[int, int]:
    no, branch = ARTICLE_REF.fullmatch(label).groups()
    return int(no), int(branch or 0)


def _cited_labels(pair: dict) -> list[str]:
    """`제4조제1항`을 조 단위 `제4조`로 묶는다."""
    text = " ".join(pair["cited_articles"])
    found = [f"제{m[1]}조" + (f"의{m[2]}" if m[2] else "") for m in ARTICLE_REF.finditer(text)]
    return list(dict.fromkeys(found))


def faq_cross(rows: list[dict], faq_rows: list[dict]) -> FaqCross:
    amendments = {r["label"]: r["amendments"] for r in rows}
    cutoff = max((p["as_of"] for p in faq_rows), default="")
    cited, missing, amended = set(), set(), set()
    citing_missing = citing_amended = 0
    for pair in faq_rows:
        labels = _cited_labels(pair)
        cited.update(labels)
        gone = [lb for lb in labels if lb not in amendments]
        late = [lb for lb in labels if any(d > cutoff for d in amendments.get(lb, []))]
        missing.update(gone)
        amended.update(late)
        citing_missing += bool(gone)
        citing_amended += bool(late)
    return FaqCross(
        pair_count=len(faq_rows),
        cutoff=cutoff,
        cited_label_count=len(cited),
        missing_labels=sorted(missing, key=_label_key),
        pairs_citing_missing=citing_missing,
        amended_labels=sorted(amended, key=_label_key),
        pairs_citing_amended=citing_amended,
    )


# ── 리포트 ───────────────────────────────────────────────────────────────

# 2026-10-05에 현행 시행 2026-06-15 판본에서 센 값 (plan §실패 징후 1)
REFERENCE_COUNTS = {"조문": 90, "장절": 20, "항": 304, "호": 504, "목": 169}
REFERENCE_EFFECTIVE = "2026-06-15"
FAQ_HINT = (
    "FAQ JSONL이 없어 이 항목은 건너뛴다. 먼저 `python -m cheongyak_rag.ingest.faq`를 돌릴 것"
)
SHOW = 5  # 목록은 앞 몇 개만 보인다. 전체 수는 따로 적는다


def _listing(items: list[str]) -> str:
    head = ", ".join(items[:SHOW])
    return head + (f" … 외 {len(items) - SHOW}개" if len(items) > SHOW else "")


def format_report(
    current: dict[str, str],
    check_result: Check,
    appendix: Appendix,
    cross: FaqCross | None,
) -> str:
    c = check_result
    out = [
        "== 법령 수집 리포트 ==",
        f"현행: MST {current['mst']} · 법령ID {current['law_id']}"
        f" · 시행일 {current['effective_date']}",
        "",
        "계층 개수 (원본 → 출력):",
    ]
    for level in COUNT_LEVELS:
        s, o = c.source_counts[level], c.output_counts[level]
        out.append(f"  {level} {s} → {o} {'일치' if s == o else '불일치'}")
    if c.source_counts == REFERENCE_COUNTS:
        out.append(f"  2026-10-05 기준값(시행 {REFERENCE_EFFECTIVE})과 같다")
    else:
        out.append(
            f"  2026-10-05 기준값(시행 {REFERENCE_EFFECTIVE})과 다르다: {REFERENCE_COUNTS}"
            " — 현행 판본이 바뀌었으면 원본에서 다시 센 위 값이 기준이다"
        )
    out += [
        "",
        f"텍스트 필드 대조 (원본 {c.source_field_count}개 → 출력 {c.output_field_count}개,"
        " 공백은 하나로 접어 비교): "
        f"누락 {len(c.missing)} · 중복 {len(c.duplicated)} · 내용이 바뀐 것 {len(c.extra)}",
    ]
    for label, fields in (("누락", c.missing), ("중복", c.duplicated), ("바뀜", c.extra)):
        out += [f"  [{label}] {f.where}: {f.text[:80]!r}" for f in fields]
    out += [
        "",
        f"별표 {len(appendix.table_titles)}개 · 부칙 {appendix.supplement_count}개"
        " (본문은 이번 범위 밖)",
    ]
    out += [f"  {t}" for t in appendix.table_titles]
    out.append("")
    if cross is None:
        out.append(f"FAQ 인용 대조: {FAQ_HINT}")
    else:
        out += [
            f"FAQ 인용 대조 (값만, 판정은 PR 게이트에서): FAQ {cross.pair_count}쌍, "
            f"인용된 조 {cross.cited_label_count}종, 기준일 {cross.cutoff}",
            f"  (a) 현행에 없는 조를 인용한 쌍: {cross.pairs_citing_missing} "
            f"(조 {len(cross.missing_labels)}종: {_listing(cross.missing_labels)})",
            "      FAQ의 `제N조`는 규칙·법·시행령 중 어느 것인지 갈라져 있지 않다."
            " 다른 법령 조문이 섞여 있어 실제보다 클 수 있다",
            f"  (b) {cross.cutoff} 뒤에 개정 날짜가 붙은 조를 인용한 쌍: "
            f"{cross.pairs_citing_amended} "
            f"(조 {len(cross.amended_labels)}종: {_listing(cross.amended_labels)})",
        ]
    return "\n".join(out)
