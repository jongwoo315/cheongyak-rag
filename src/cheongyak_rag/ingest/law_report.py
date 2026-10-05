"""법령 JSONL을 원본 JSON과 맞대는 대조 코드 (#69).

파서(`law.py`)를 부르지 않는다. 같은 코드로 세면 같은 버그가 양쪽에 들어가서 대조가 항상 통과한다.
원본 쪽은 JSON을 재귀로 훑고, 출력 쪽은 JSONL 줄(dict)만 읽는다.
"""

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
    )
