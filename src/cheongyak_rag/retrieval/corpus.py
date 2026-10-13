"""검색 대상 문서 — 「주택공급에 관한 규칙」 현행 조문. 조 하나 = 문서 하나 (#131)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"
LAW_PATH = DATA_DIR / "law-008243-20260615.jsonl"

# `<개정 2016.8.12, 2019.8.16>` 같은 개정 이력.
# 날짜 숫자가 BM25 토큰·임베딩 입력에 섞이는 것을 막는다
# `삭제<2024.12.18>`처럼 접두어 없이 날짜만 든 것과 제10조의 `<img>` 태그도 같이 뺀다
AMENDMENT = re.compile(
    r"\s*<(?:(?:전문개정|개정|신설|본조신설|삭제)[^>]*|\d{4}\.[\d.,\s]*|img\b[^>]*)>(?:</img>)?"
)


@dataclass(frozen=True)
class Article:
    label: str  # 제4조 · 제4조의2
    title: str
    text: str


def _clean(text: str) -> str:
    return AMENDMENT.sub("", text).strip()


def _body(row: dict) -> str:
    head = f"{row['label']}({row['title']})"
    text = _clean(row["text"])
    lines = [head]
    rest = text[len(head) :].strip() if text.startswith(head) else text
    if rest:
        lines.append(rest)
    for para in row["paragraphs"]:
        if para["text"]:
            lines.append(_clean(para["text"]))
        for item in para["items"]:
            lines.append(_clean(item["text"]))
            lines.extend(_clean(sub["text"]) for sub in item["subitems"])
    return "\n".join(lines)


def load_articles(path: Path = LAW_PATH) -> list[Article]:
    """삭제 조문을 뺀 현행 조문. text = 머리 줄 + 본문 + 항·호·목을 줄바꿈으로 이은 것."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [Article(r["label"], r["title"], _body(r)) for r in rows if not r["deleted"]]
