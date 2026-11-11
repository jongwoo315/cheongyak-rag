"""PDF 쪽 글자와 조문 본문을 꺼내고 구절이 거기 있는지 공백만 합쳐 비교한다 (#75)."""

import re
from pathlib import Path

import pymupdf
import sqlalchemy as sa
from sqlalchemy.engine import Engine

_WS = re.compile(r"\s+")


def pdf_pages(path: str | Path) -> list[str]:
    """PDF의 쪽마다 글자 하나씩. 0번째가 1쪽이다."""
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def norm(s: str) -> str:
    """공백 묶음(줄바꿈·탭 포함)을 한 칸으로 줄이고 양끝을 자른다."""
    return _WS.sub(" ", s).strip()


def _squash(s: str) -> str:
    return _WS.sub("", s)


def quote_in(quote: str, text: str) -> bool:
    """구절이 글자에 그대로 있다. 공백은 있고 없고를 따지지 않는다(PDF는 줄 끝에서 갈린다)."""
    q = _squash(quote)
    return bool(q) and q in _squash(text)


def article_text(engine: Engine, mst: str, label: str) -> str | None:
    """`chunks`에서 법령 버전 `mst`의 조 `label` 본문. 없으면 None."""
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT text FROM chunks WHERE source = 'law' AND law_mst = :m AND label = :l"),
            {"m": mst, "l": label},
        ).scalar()
