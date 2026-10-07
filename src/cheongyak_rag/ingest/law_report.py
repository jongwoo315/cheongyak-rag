"""법령 JSONL을 원본 JSON과 맞대는 대조 코드 (#69).

파서(`law.py`)를 부르지 않는다. 같은 코드로 세면 같은 버그가 양쪽에 들어가서 대조가 항상 통과한다.
원본 쪽은 JSON을 재귀로 훑고, 출력 쪽은 JSONL 줄(dict)만 읽는다.
"""

import html
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
    missing: list[Field]  # 원본에 있는데 출력에 없다 (조문 번호까지 맞아야 있는 것으로 센다)
    duplicated: list[Field]  # 같은 조문에 원본보다 더 많이 들어갔다
    extra: list[Field]  # 원본에 없는 내용이 출력에 있다 (내용이 바뀌었거나 다른 조문으로 옮겨졌다)
    misplaced: list[Field] = field(default_factory=list)  # 장·절 소속이 원본 순서와 다르다
    bad_meta: list[Field] = field(default_factory=list)  # 개정 날짜·삭제 여부·제목·번호가 다르다
    source_counts: dict[str, int] = field(default_factory=dict)
    output_counts: dict[str, int] = field(default_factory=dict)
    source_field_count: int = 0
    output_field_count: int = 0

    @property
    def ok(self) -> bool:
        problems = (self.missing, self.duplicated, self.extra, self.misplaced, self.bad_meta)
        # 조문이 하나도 없으면 개수가 0 == 0으로 맞아도 통과가 아니다. 빈 응답이 빈 JSONL이 된다
        has_articles = self.source_counts.get("조문", 0) > 0
        return has_articles and not any(problems) and self.source_counts == self.output_counts


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


# ── 소속·속성 (원본에서 따로 읽는다) ─────────────────────────────────────

DATE_IN_TAG = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")
TAG = re.compile(r"(?:<|&lt;)([^<>&]*)(?:>|&gt;)")
DELETED_HEAD = re.compile(r"^제\d+조(?:의\d+)?\s*삭제")


def source_headings(law_json: dict) -> dict[str, tuple[str | None, str | None]]:
    """조문 라벨 → 그 조문이 속한 (장, 절). 원본을 순서대로 읽어 장·절 제목을 따라간다."""
    chapter = section = None
    found = {}
    for unit in _units(law_json):
        text = _norm(" ".join(_strings(unit["조문내용"])))
        if unit["조문여부"] == "전문":
            if re.match(r"제\d+장", text):
                chapter, section = text, None
            else:
                section = text
        else:
            found[_label(unit)] = (chapter, section)
    return found


def _source_numbers(unit: dict) -> dict[str, list[tuple[str, ...]]]:
    """조문 하나의 항·호·목 번호를 문서 순서대로, 윗 단계 번호까지 붙인 경로로.

    호가 어느 항 아래인지까지 맞아야 같다. 하나면 dict로 와서 목록으로 맞춘다.
    """
    nums: dict[str, list[tuple[str, ...]]] = {"항": [], "호": [], "목": []}

    def listed(node) -> list:
        return [] if node is None else [node] if isinstance(node, dict) else node

    for hang in listed(unit.get("항")):
        h = hang.get("항번호", "").strip()
        nums["항"].append((h,))
        for ho in listed(hang.get("호")):
            branch = ho.get("호가지번호")
            o = ho["호번호"].strip().rstrip(".") + (f"의{branch}" if branch else "")
            nums["호"].append((h, o))
            nums["목"].extend((h, o, m["목번호"].strip().rstrip(".")) for m in listed(ho.get("목")))
    return nums


def _output_numbers(row: dict) -> dict[str, list[tuple[str, ...]]]:
    nums: dict[str, list[tuple[str, ...]]] = {"항": [], "호": [], "목": []}
    for p in row["paragraphs"]:
        nums["항"].append((p["no"],))
        for i in p["items"]:
            nums["호"].append((p["no"], i["no"]))
            nums["목"].extend((p["no"], i["no"], s["no"]) for s in i["subitems"])
    return nums


def _dates(text: str) -> set[str]:
    return {
        f"{y}-{int(m):02d}-{int(d):02d}"
        for tag in TAG.findall(text)
        for y, m, d in DATE_IN_TAG.findall(tag)
    }


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _meta_problems(law_json: dict, rows: list[dict], texts: dict[str, list[str]]) -> list[Field]:
    by_label = {r["label"]: r for r in rows}
    info = law_json["법령"]["기본정보"]
    problems = []
    for unit in _units(law_json):
        if unit["조문여부"] != "조문":
            continue
        label, row = _label(unit), by_label.get(_label(unit))
        if row is None:
            continue  # 없는 조문은 텍스트 대조가 이미 누락으로 센다
        head = _norm(" ".join(_strings(unit["조문내용"])))
        expected = {
            "amendments": sorted(_dates("\n".join(texts[label]))),
            "deleted": bool(DELETED_HEAD.match(head)),
            "title": unit.get("조문제목"),
            "article_no": int(unit["조문번호"]),
            "branch_no": int(unit.get("조문가지번호") or 0),
            "시행일": _iso(unit["조문시행일자"]),
            "law_id": info["법령ID"],
            "effective_date": _iso(info["시행일자"]),
            # 항 단위 개정 날짜는 조문 전체 합집합에 묻혀 위 amendments로는 안 보인다
            "항 개정": [
                sorted(_dates(" ".join(_strings(h.get("항내용")))))
                for h in _as_list(unit.get("항"))
            ],
            **{f"{lv}번호": nums for lv, nums in _source_numbers(unit).items()},
        }
        got = {
            "amendments": row["amendments"],
            "deleted": row["deleted"],
            "title": row["title"],
            "article_no": row["article_no"],
            "branch_no": row["branch_no"],
            "시행일": row["article_effective_date"],
            "law_id": row["law_id"],
            "effective_date": row["effective_date"],
            "항 개정": [p["amendments"] for p in row["paragraphs"]],
        }
        got.update({f"{lv}번호": nums for lv, nums in _output_numbers(row).items()})
        for key, want in expected.items():
            if got[key] != want:
                problems.append(Field(label, f"{key}: 원본 {want!r} / 출력 {got[key]!r}"))
    return problems


# ── 대조 ─────────────────────────────────────────────────────────────────


def check(law_json: dict, rows: list[dict]) -> Check:
    src, out = source_fields(law_json), output_fields(rows)
    # 조문 번호까지 묶어서 센다. 텍스트만 세면 다른 조문으로 옮겨진 것을 못 잡는다
    src_n = Counter((f.where, f.text) for f in src)
    out_n = Counter((f.where, f.text) for f in out)

    def pick(fields: list[Field], budget: Counter) -> list[Field]:
        budget, picked = Counter(budget), []
        for f in fields:
            if budget[(f.where, f.text)] > 0:
                budget[(f.where, f.text)] -= 1
                picked.append(f)
        return picked

    surplus = pick(out, out_n - src_n)
    texts: dict[str, list[str]] = {}
    for f in src:
        texts.setdefault(f.where, []).append(f.text)
    expected_headings = source_headings(law_json)
    misplaced = []
    for r in rows:
        want = expected_headings.get(r["label"])
        got = (_norm(r["chapter"] or "") or None, _norm(r["section"] or "") or None)
        if want is not None and got != want:
            misplaced.append(Field(r["label"], f"원본 {want} / 출력 {got}"))
    return Check(
        missing=pick(src, src_n - out_n),
        duplicated=[f for f in surplus if (f.where, f.text) in src_n],
        extra=[f for f in surplus if (f.where, f.text) not in src_n],
        misplaced=misplaced,
        bad_meta=_meta_problems(law_json, rows, texts),
        source_counts=source_counts(law_json),
        output_counts=output_counts(rows),
        source_field_count=len(src),
        output_field_count=len(out),
    )


# ── 별표·부칙 (본문은 이번 범위 밖 — 개수와 제목만) ─────────────────────────


@dataclass
class Appendix:
    table_titles: list[str]  # `별표 1 가점제 …(제2조제8호 관련)`, `서식 3의2 주택청약 접수증`
    table_count: int  # 별표구분이 `별표`인 것
    form_count: int  # 별표구분이 `서식`인 것. 같은 `별표단위`로 오고 번호가 별표와 겹친다
    supplement_count: int


def _as_list(node) -> list:
    if node is None:
        return []
    return [node] if isinstance(node, dict) else node


def appendix_summary(law_json: dict) -> Appendix:
    law = law_json["법령"]
    units = _as_list(law.get("별표", {}).get("별표단위"))
    titles = []
    for t in units:
        branch = int(t.get("별표가지번호") or 0)
        no = f"{int(t['별표번호'])}" + (f"의{branch}" if branch else "")
        titles.append(f"{t['별표구분']} {no} {html.unescape(t['별표제목'])}")
    kinds = Counter(t["별표구분"] for t in units)
    return Appendix(
        titles, kinds["별표"], kinds["서식"], len(_as_list(law.get("부칙", {}).get("부칙단위")))
    )


# ── 실패 징후 4: #70 FAQ 인용 커버 ────────────────────────────────────────

ARTICLE_REF = re.compile(r"제(\d+)조(?:의(\d+))?")
CONTEXT_CHARS = 20  # 커버 안 된 조 앞에서 가져오는 글자 수. 법령 이름이 보이게 한다


@dataclass
class Uncovered:
    q_no: int
    label: str  # 현행에 없는 조
    before: str  # FAQ 본문에서 그 조 바로 앞 20자. 본문에 없으면 빈 문자열


@dataclass
class FaqCross:
    pair_count: int
    cutoff: str  # FAQ 기준일. 이보다 늦은 날짜가 붙은 개정만 참고로 센다
    cited_pairs: int  # 인용이 하나라도 있는 쌍. 커버 비율의 분모
    covered_pairs: int  # 인용한 조가 전부 현행에 있는 쌍
    uncovered: list[Uncovered]  # 쌍 × 없는 조. 법령 이름 때문에 조마다 한 줄이다
    cited_labels: int  # 인용된 조(가지 포함)의 종류 수
    current_labels: int  # 그중 현행에 있는 것
    covered_pairs_amended: int  # 참고용. 커버된 쌍 중 cutoff 뒤 개정일이 붙은 조를 인용한 쌍
    amended_labels: list[str]
    latest_amendment: dict[str, str]  # 인용된 현행 조의 최근 개정일. 참고용

    @property
    def uncovered_pairs(self) -> int:
        return self.cited_pairs - self.covered_pairs


def _label_key(label: str) -> tuple[int, int]:
    no, branch = ARTICLE_REF.fullmatch(label).groups()
    return int(no), int(branch or 0)


def _cited_labels(pair: dict) -> list[str]:
    """`제4조제1항`을 조 단위 `제4조`로 묶는다."""
    text = " ".join(pair["cited_articles"])
    found = [f"제{m[1]}조" + (f"의{m[2]}" if m[2] else "") for m in ARTICLE_REF.finditer(text)]
    return list(dict.fromkeys(found))


def _text_before(pair: dict, label: str) -> str:
    # `제7조`가 `제7조의2`에 걸리지 않게 뒤를 막는다. `제17조`는 `제7조`로 시작하지 않는다
    ref = re.compile(re.escape(label) + r"(?!\d|의\d)")
    for text in (pair.get("answer", ""), pair.get("question", "")):
        if m := ref.search(text):
            return " ".join(text[max(0, m.start() - CONTEXT_CHARS) : m.start()].split())
    return ""


def faq_cross(rows: list[dict], faq_rows: list[dict]) -> FaqCross:
    # 삭제된 조문은 행이 남아 있어도 현행 조문이 아니다
    amendments = {r["label"]: r["amendments"] for r in rows if not r["deleted"]}
    cutoff = max((p["as_of"] for p in faq_rows), default="")
    cited: set[str] = set()
    uncovered: list[Uncovered] = []
    amended: set[str] = set()
    cited_pairs = covered = covered_amended = 0
    for pair in faq_rows:
        labels = _cited_labels(pair)
        if not labels:
            continue
        cited_pairs += 1
        cited.update(labels)
        gone = [lb for lb in labels if lb not in amendments]
        uncovered += [Uncovered(pair["q_no"], lb, _text_before(pair, lb)) for lb in gone]
        if gone:
            continue
        covered += 1
        late = [lb for lb in labels if any(d > cutoff for d in amendments[lb])]
        amended.update(late)
        covered_amended += bool(late)
    current = cited & amendments.keys()
    return FaqCross(
        pair_count=len(faq_rows),
        cutoff=cutoff,
        cited_pairs=cited_pairs,
        covered_pairs=covered,
        uncovered=uncovered,
        cited_labels=len(cited),
        current_labels=len(current),
        covered_pairs_amended=covered_amended,
        amended_labels=sorted(amended, key=_label_key),
        latest_amendment={lb: max(amendments[lb], default="") for lb in current},
    )


# ── 리포트 ───────────────────────────────────────────────────────────────

# 2026-10-05에 현행 시행 2026-06-15 판본에서 센 값 (plan §실패 징후 1)
REFERENCE_COUNTS = {"조문": 90, "장절": 20, "항": 304, "호": 504, "목": 169}
REFERENCE_EFFECTIVE = "2026-06-15"
FAQ_HINT = (
    "이 항목은 건너뛴다. FAQ JSONL이 없으면 먼저 `python -m cheongyak_rag.ingest.faq`를 돌릴 것."
    " 파일이 있는데도 이 문구가 나오면 stderr의 오류를 볼 것"
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
        f"소속·속성 대조 (장·절 소속, 개정 날짜, 삭제 여부, 제목, 항·호·목 번호): "
        f"소속 어긋남 {len(c.misplaced)} · 속성 어긋남 {len(c.bad_meta)}",
    ]
    for label, fields in (
        ("누락", c.missing),
        ("중복", c.duplicated),
        ("바뀜", c.extra),
        ("소속", c.misplaced),
        ("속성", c.bad_meta),
    ):
        out += [f"  [{label}] {f.where}: {f.text[:120]!r}" for f in fields]
    out += [
        "",
        f"별표·서식 {len(appendix.table_titles)}개 (별표 {appendix.table_count}"
        f" · 서식 {appendix.form_count}) · 부칙 {appendix.supplement_count}개"
        " (본문은 이번 범위 밖)",
    ]
    out += [f"  {t}" for t in appendix.table_titles]
    out.append("")
    if cross is None:
        out.append(f"FAQ 인용 커버: {FAQ_HINT}")
    else:
        pct = 100 * cross.covered_pairs / cross.cited_pairs if cross.cited_pairs else 0
        out += [
            f"FAQ 인용 커버 (값만, 판정은 PR 게이트에서): FAQ {cross.pair_count}쌍 중"
            f" 인용 있는 쌍 {cross.cited_pairs} · 커버 {cross.covered_pairs} ({pct:.0f}%)"
            f" · 커버 안 됨 {cross.uncovered_pairs}",
            f"  인용된 조 {cross.cited_labels}종 중 현행에 있는 것 {cross.current_labels}종"
            " (삭제된 조는 현행에 없는 것으로 센다)",
            "  커버 = 쌍이 인용한 조(항·호는 뗀다)가 전부 현행 규칙에 있다. 개정 여부는 안 본다.",
            "  FAQ의 `제N조`는 규칙·법·시행령 중 어느 것인지 갈라져 있지 않다."
            " 다른 법령 인용도 분모에서 빼지 않았다. 다른 법령 조가 규칙에 없으면 커버 안 됨으로,"
            " 번호가 우연히 같으면 커버로 센다",
        ]
        if cross.uncovered:
            out.append("  커버 안 된 쌍 (Q번호 · 현행에 없는 조: 그 조 앞 20자):")
        out += [f"    Q{u.q_no} {u.label}: {u.before!r}" for u in cross.uncovered]
        recent = [f"{lb}({cross.latest_amendment[lb]})" for lb in cross.amended_labels]
        out.append(
            f"  참고 (커버 판정에 안 씀): 커버된 쌍 중 {cross.cutoff} 뒤에 개정 날짜가 붙은 조를"
            f" 인용한 쌍 {cross.covered_pairs_amended} (조 {len(recent)}종: {_listing(recent)})"
        )
    return "\n".join(out)
