"""청킹 후보 — 조문 5개와 FAQ (#73).

    python -m cheongyak_rag.retrieval.chunk

법령 jsonl의 구조(조 → 항 → 호 → 목)로 자른다. 줄을 문자열로 쪼개지 않는다.
청크 jsonl은 `data/processed/chunks-<후보>.jsonl` (gitignore 범위).
"""

import json
import re
import statistics
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cheongyak_rag.retrieval.corpus import DATA_DIR, LAW_PATH, _body, _clean
from cheongyak_rag.retrieval.golden import extract_citations, load_faq

CANDIDATES = ("article", "paragraph", "paragraph+head", "item", "item+head")
SHORT_CHARS = 10  # 실패 징후 4 — 이보다 짧은 청크


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    label: str  # 조 (`제2조`). FAQ는 `Q47`
    path: str  # 위치 (`제2조제1항제2호가목`). FAQ는 `Q47`
    text: str
    source: str  # law | faq
    meta: dict = field(default_factory=dict)


# ── 조문 ────────────────────────────────────────────────────────────────


def _head(row: dict) -> str:
    return f"{row['label']}({row['title']})"


def _rest(row: dict) -> str:
    """머리 줄 뒤의 조 본문. `corpus._body`와 같은 규칙."""
    head, text = _head(row), _clean(row["text"])
    return (text[len(head) :] if text.startswith(head) else text).strip()


def _para_path(label: str, no: str) -> str:
    if no == "":  # 항 번호가 없는 조는 호가 조에 바로 달린다
        return label
    try:
        return f"{label}제{int(unicodedata.numeric(no[0]))}항"
    except (TypeError, ValueError):
        return f"{label}제{no}항"


def _item_path(base: str, no: str) -> str:
    m = re.fullmatch(r"(\d+)(의\d+)?", no)
    return f"{base}제{m[1]}호{m[2] or ''}" if m else f"{base}제{no}호"


def _lines(row: dict) -> list[tuple[str, str]]:
    """(path, 줄) — 본문·항 본문·호·목 한 줄씩, 문서 순서. 빈 줄은 없다."""
    label = row["label"]
    out = []
    if rest := _rest(row):
        out.append((label, rest))
    for para in row["paragraphs"]:
        ppath = _para_path(label, para["no"])
        if text := _clean(para["text"]):
            out.append((ppath, text))
        for item in para["items"]:
            ipath = _item_path(ppath, item["no"])
            out.append((ipath, _clean(item["text"])))
            out += [(f"{ipath}{s['no']}목", _clean(s["text"])) for s in item["subitems"]]
    return out


def _paragraph_groups(row: dict) -> list[tuple[str, list[str]]]:
    """(path, 줄들) — 항 하나 + 그 항의 호·목. 조 본문은 첫 항에 붙고, 항이 없으면 조 전체 하나."""
    label, rest = row["label"], _rest(row)
    if not row["paragraphs"]:
        return [(label, [rest])]
    groups = []
    for i, para in enumerate(row["paragraphs"]):
        lines = [rest] if i == 0 and rest else []
        if text := _clean(para["text"]):
            lines.append(text)
        for item in para["items"]:
            lines.append(_clean(item["text"]))
            lines += [_clean(s["text"]) for s in item["subitems"]]
        groups.append((_para_path(label, para["no"]), lines))
    return groups


def law_chunks(rows: list[dict], candidate: str) -> list[Chunk]:
    """삭제 조문을 뺀 현행 조문을 후보 방식으로 자른다."""
    if candidate not in CANDIDATES:
        raise ValueError(f"후보 {candidate!r} 없음. {CANDIDATES} 중 하나")
    with_head = candidate.endswith("+head")
    kind = candidate.removesuffix("+head")
    out = []
    for row in rows:
        if row["deleted"]:
            continue
        head = _head(row)
        if kind == "article":
            pieces = [(row["label"], _body(row))]
        elif kind == "paragraph":
            pieces = [(path, "\n".join(lines)) for path, lines in _paragraph_groups(row)]
        else:
            pieces = _lines(row)
        for path, text in pieces:
            if with_head:
                text = f"{head}\n{text}"
            out.append(
                Chunk(f"law:{path}", row["label"], path, text, "law", {"title": row["title"]})
            )
    dups = [p for p, n in Counter(c.path for c in out).items() if n > 1]
    if dups:  # path가 chunk_id·조회 키라 겹치면 청크가 조용히 합쳐진다
        raise ValueError(f"{candidate}: path가 겹친다 {dups[:3]}")
    return out


def strip_head(c: Chunk) -> str:
    """머리 줄(`제N조(제목)`)을 뗀 본문. 머리가 없으면 그대로."""
    head = f"{c.label}({c.meta.get('title')})"
    if c.text == head:
        return ""
    return c.text.removeprefix(head + "\n")


def check_preservation(rows: list[dict], candidate: str) -> list[str]:
    """실패 징후 3 — 조의 청크들에서 머리를 뗀 텍스트를 이으면 그 조의 본문 줄과 같은가.

    문제가 없으면 빈 목록. 누락·중복·순서를 조 단위로 적는다.
    """
    chunks = law_chunks(rows, candidate)
    by_label: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_label.setdefault(c.label, []).append(c)
    problems = []
    for row in rows:
        if row["deleted"]:
            continue
        want = _body(row).split("\n")[1:]  # 머리 줄을 뗀 본문 줄
        got = [ln for c in by_label.get(row["label"], []) for ln in strip_head(c).split("\n")]
        if got == want:
            continue
        missing, dup = Counter(want) - Counter(got), Counter(got) - Counter(want)
        why = (
            f"누락 {sum(missing.values())}줄, 중복 {sum(dup.values())}줄"
            if missing or dup
            else "줄 순서가 다르다"
        )
        problems.append(f"{row['label']}: {why}")
    return problems


def short_ratio(chunks: list[Chunk], limit: int = SHORT_CHARS) -> float:
    """머리를 뗀 본문이 limit자 미만인 청크 비율. 머리를 붙인 후보도 같은 줄로 잰다."""
    return sum(len(strip_head(c)) < limit for c in chunks) / len(chunks)


# ── FAQ ─────────────────────────────────────────────────────────────────


def faq_chunks(faq_rows: list[dict], golden_labels: set[str]) -> list[Chunk]:
    """쌍 하나 = 청크 하나. 텍스트는 질문 + 줄바꿈 + 답변.

    meta.cited = golden 규칙(`golden.extract_citations`)으로 뽑은 현행 규칙 조.
    다른 법령 인용은 뺀다. 이름 없는 인용은 규칙으로 본다.
    """
    out = []
    for r in faq_rows:
        cited = list(
            dict.fromkeys(
                c.label
                for c in extract_citations(r["answer"])
                if c.kind != "other" and c.label in golden_labels
            )
        )
        meta = {k: r[k] for k in ("q_no", "major", "middle", "minor")} | {"cited": cited}
        out.append(
            Chunk(
                f"faq:{r['q_no']}",
                f"Q{r['q_no']}",
                f"Q{r['q_no']}",
                f"{r['question']}\n{r['answer']}",
                "faq",
                meta,
            )
        )
    return out


# ── CLI ─────────────────────────────────────────────────────────────────


def chunks_path(candidate: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"chunks-{candidate}.jsonl"


def write_chunks(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        json.dumps(
            {
                "chunk_id": c.chunk_id,
                "label": c.label,
                "path": c.path,
                "text": c.text,
                "source": c.source,
                **c.meta,
            },
            ensure_ascii=False,
        )
        + "\n"
        for c in chunks
    )
    path.write_text("".join(lines), encoding="utf-8")


def load_law_rows(path: Path = LAW_PATH) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _size_line(name: str, chunks: list[Chunk]) -> str:
    sizes = [len(c.text) for c in chunks]
    return (
        f"{name}: 청크 {len(chunks)}개 · 글자 수 중앙값 {statistics.median(sizes):g}"
        f" · 최대 {max(sizes)}"
    )


def main(data_dir: Path = DATA_DIR, law_path: Path = LAW_PATH) -> int:
    rows = load_law_rows(law_path)
    labels = {r["label"] for r in rows if not r["deleted"]}
    for cand in CANDIDATES:
        chunks = law_chunks(rows, cand)
        write_chunks(chunks, chunks_path(cand, data_dir))
        problems = check_preservation(rows, cand)
        ratio = short_ratio(chunks)
        print(_size_line(cand, chunks))
        print(
            f"  보존 검사: {'누락 0·중복 0' if not problems else f'{len(problems)}개 조에 문제'}"
            f" · {SHORT_CHARS}자 미만 청크 {ratio:.1%}"
        )
        for p in problems:
            print(f"  ✗ {p}")
    faq = faq_chunks(load_faq(), labels)
    write_chunks(faq, chunks_path("faq", data_dir))
    print(_size_line("faq", faq))
    print(f"→ {data_dir}/chunks-*.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
