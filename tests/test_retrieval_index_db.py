from cheongyak_rag.retrieval import index_db
from cheongyak_rag.retrieval.chunk import faq_chunks, law_chunks
from cheongyak_rag.retrieval.embed import text_key
from cheongyak_rag.retrieval.search import tokenize
from tests.fakes import FakeEmbedder
from tests.test_retrieval_query import FAQ, LAW


def test_build_rows_uses_the_same_chunk_functions_as_query_index():
    law = law_chunks(LAW, "article")
    faq = faq_chunks(FAQ, {r["label"] for r in LAW})
    rows = index_db.build_rows(FakeEmbedder(), "286965", "article", law_rows=LAW, faq_rows=FAQ)
    assert len(rows) == len(law) + len(faq)
    assert [r["chunk_id"] for r in rows] == [c.chunk_id for c in law + faq]
    assert len({r["chunk_id"] for r in rows}) == len(rows)
    assert {r["source"] for r in rows} == {"law", "faq"}


def test_row_fields_follow_the_design():
    emb = FakeEmbedder()
    rows = {
        r["chunk_id"]: r
        for r in index_db.build_rows(emb, "286965", "article", law_rows=LAW, faq_rows=FAQ)
    }
    law, faq = rows["law:제1조"], rows["faq:1"]
    assert law["label"] == "제1조" and law["path"] == "제1조" and law["title"] == "목적"
    assert law["law_mst"] == "286965"
    assert faq["law_mst"] is None and faq["title"] is None
    assert faq["label"] == "Q1"
    for r in (law, faq):
        assert r["text_sha256"] == text_key(r["text"])
        assert r["embed_model"] == "fake"
        assert len(r["embedding"]) == emb.dim
        assert r["tokens"] == " ".join(tokenize(r["text"]))


def test_law_mst_none_leaves_law_rows_null():
    rows = index_db.build_rows(FakeEmbedder(), None, "article", law_rows=LAW, faq_rows=FAQ)
    assert all(r["law_mst"] is None for r in rows)


def test_embed_is_one_call_over_all_chunk_texts():
    emb = FakeEmbedder()
    rows = index_db.build_rows(emb, None, "article", law_rows=LAW, faq_rows=FAQ)
    assert emb.calls == [len(rows)]


def _insert_version(engine, mst, effective, promulgated=None):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO law_versions (law_id, mst, effective_date, promulgation_date, raw)"
                " VALUES ('008243', :m, :e, :p, '{}')"
            ),
            {"m": mst, "e": effective, "p": promulgated},
        )


def test_law_mst_reads_the_row_with_the_corpus_effective_date(pg_engine):
    _insert_version(pg_engine, "100", "2026-01-01")
    _insert_version(pg_engine, "286965", "2026-06-15")
    assert index_db.law_mst(pg_engine) == "286965"


def test_law_mst_is_none_without_that_row(pg_engine):
    _insert_version(pg_engine, "100", "2026-01-01")
    assert index_db.law_mst(pg_engine) is None


def test_law_mst_same_day_picks_later_promulgation(pg_engine):
    _insert_version(pg_engine, "111", "2026-06-15", "2026-05-01")
    _insert_version(pg_engine, "222", "2026-06-15", "2026-06-01")
    assert index_db.law_mst(pg_engine) == "222"
