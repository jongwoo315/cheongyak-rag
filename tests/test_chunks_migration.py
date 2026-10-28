from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic

INDEXES = {"chunks_embedding_law_hnsw", "chunks_embedding_faq_hnsw", "chunks_tokens_gin"}
COLUMNS = [
    "chunk_id",
    "source",
    "label",
    "path",
    "title",
    "text",
    "text_sha256",
    "law_mst",
    "embed_model",
    "embedding",
    "tokens",
]


def _indexdefs(url: str) -> dict[str, str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'")
            )
            return {r[0]: r[1] for r in rows}
    finally:
        engine.dispose()


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_table_with_design_columns(pg_test_url):
    engine = create_engine(pg_test_url)
    try:
        with engine.connect() as conn:
            cols = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'chunks' ORDER BY ordinal_position"
                )
            ).scalars()
            assert list(cols) == COLUMNS
        assert inspect(engine).get_pk_constraint("chunks")["constrained_columns"] == ["chunk_id"]
    finally:
        engine.dispose()


def test_three_indexes_have_the_designed_shape(pg_test_url):
    defs = _indexdefs(pg_test_url)
    assert INDEXES <= defs.keys()
    for name, source in (
        ("chunks_embedding_law_hnsw", "law"),
        ("chunks_embedding_faq_hnsw", "faq"),
    ):
        d = defs[name]
        assert "USING hnsw" in d and "vector_cosine_ops" in d
        assert f"source = '{source}'" in d
    assert "USING gin" in defs["chunks_tokens_gin"] and "(tokens)" in defs["chunks_tokens_gin"]


def test_source_check_rejects_other_values(pg_engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO chunks (chunk_id, source, label, path, text, text_sha256,"
                " embed_model, embedding, tokens) VALUES ('x', 'notice', 'l', 'p', 't', 's', 'm',"
                " array_fill(0.1::real, ARRAY[1536])::vector, to_tsvector('simple', 'a'))"
            )
        )


def test_downgrade_removes_table_and_indexes_and_upgrade_restores(pg_test_url):
    alembic(pg_test_url, "downgrade", "0003")
    try:
        assert "chunks" not in _tables(pg_test_url)
        assert _indexdefs(pg_test_url) == {}
        assert "law_versions" in _tables(pg_test_url)  # 0003은 그대로다
    finally:
        # 실패해도 세션 공용 DB를 head로 돌려놓는다
        alembic(pg_test_url, "upgrade", "head")
    assert "chunks" in _tables(pg_test_url)
    assert INDEXES <= _indexdefs(pg_test_url).keys()
