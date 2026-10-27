"""조문·FAQ 청크와 임베딩을 Postgres `chunks` 테이블에 적재한다 (#74).

    python -m cheongyak_rag.retrieval.index_db [--report]

청크는 `query.Index`와 같은 함수(`law_chunks`·`faq_chunks`)로 만든다. 벡터는 `Embedder`의 캐시에서
가져오므로 캐시에 있는 텍스트는 API를 부르지 않는다. 적재는 한 트랜잭션에서 비우고 다시 넣는다.
"""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.asof import LAW_ID
from cheongyak_rag.retrieval.chunk import faq_chunks, law_chunks, load_law_rows
from cheongyak_rag.retrieval.embed import text_key
from cheongyak_rag.retrieval.golden import load_faq
from cheongyak_rag.retrieval.search import tokenize

# data/processed/law-008243-20260615.jsonl이 가리키는 버전의 시행일
LAW_EFFECTIVE = date(2026, 6, 15)


def law_mst(engine: Engine) -> str | None:
    """`law_versions`에서 위 시행일 행의 MST. 행이 없으면 None(설계 §5-2).

    같은 시행일에 MST가 둘이면 view `notice_law_versions`와 같은 규칙으로 하나를 고른다.
    """
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT mst FROM law_versions WHERE law_id = :l AND effective_date = :d"
                " ORDER BY promulgation_date DESC NULLS LAST, length(mst) DESC, mst DESC LIMIT 1"
            ),
            {"l": LAW_ID, "d": LAW_EFFECTIVE},
        ).scalar()


def build_rows(
    embedder,
    mst: str | None,
    candidate: str,
    *,
    law_rows: list[dict] | None = None,
    faq_rows: list[dict] | None = None,
) -> list[dict]:
    """조문 청크 + FAQ 청크를 `chunks` 한 행씩의 dict로. 벡터는 한 번의 `embed`로 가져온다.

    `tokens`는 형태소 토큰을 공백으로 이은 문자열이다. tsvector로 바꾸는 것은 SQL이 한다.
    """
    law_rows = load_law_rows() if law_rows is None else law_rows
    faq_rows = load_faq() if faq_rows is None else faq_rows
    law = law_chunks(law_rows, candidate)
    faq = faq_chunks(faq_rows, {r["label"] for r in law_rows if not r["deleted"]})
    chunks = law + faq
    vecs = embedder.embed([c.text for c in chunks])
    return [
        {
            "chunk_id": c.chunk_id,
            "source": c.source,
            "label": c.label,
            "path": c.path,
            "title": c.meta.get("title") if c.source == "law" else None,
            "text": c.text,
            "text_sha256": text_key(c.text),
            "law_mst": mst if c.source == "law" else None,
            "embed_model": embedder.model,
            "embedding": [float(x) for x in vec],
            "tokens": " ".join(tokenize(c.text)),
        }
        for c, vec in zip(chunks, vecs, strict=True)
    ]
