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


def _rows(emb=None):
    return index_db.build_rows(
        emb or FakeEmbedder(dim=1536), "286965", "article", law_rows=LAW, faq_rows=FAQ
    )


def _state(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(
            text("SELECT chunk_id, embedding::text, tokens::text FROM chunks ORDER BY chunk_id")
        ).all()


def test_load_twice_gives_the_same_rows(pg_engine):
    rows = _rows()
    assert index_db.load(pg_engine, rows) == len(rows)
    first = _state(pg_engine)
    assert len(first) == len(rows)
    index_db.load(pg_engine, _rows())
    assert _state(pg_engine) == first


def test_load_has_no_empty_tokens(pg_engine):
    from sqlalchemy import text

    index_db.load(pg_engine, _rows())
    with pg_engine.connect() as conn:
        empty = conn.execute(text("SELECT count(*) FROM chunks WHERE tokens = ''")).scalar()
    assert empty == 0


def test_load_rejects_empty_input_and_keeps_previous_rows(pg_engine):
    import pytest

    rows = _rows()
    index_db.load(pg_engine, rows)
    before = _state(pg_engine)
    with pytest.raises(ValueError):
        index_db.load(pg_engine, [])
    assert _state(pg_engine) == before


def test_load_drops_rows_that_are_no_longer_in_the_input(pg_engine):
    rows = _rows()
    index_db.load(pg_engine, rows)
    index_db.load(pg_engine, rows[:2])
    assert [r[0] for r in _state(pg_engine)] == sorted(r["chunk_id"] for r in rows[:2])


def test_failed_load_keeps_previous_rows(pg_engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    rows = _rows()
    index_db.load(pg_engine, rows)
    before = _state(pg_engine)
    bad = [*rows[:3], {**rows[3], "source": "notice"}]  # CHECK에 걸려 마지막 행에서 실패한다
    with pytest.raises(IntegrityError):
        index_db.load(pg_engine, bad)
    assert _state(pg_engine) == before


def test_loaded_vector_matches_input_within_float4(pg_engine):
    import numpy as np
    from sqlalchemy import text

    rows = _rows()
    index_db.load(pg_engine, rows)
    with pg_engine.connect() as conn:
        got = conn.execute(
            text("SELECT embedding::text FROM chunks WHERE chunk_id = :i"),
            {"i": rows[0]["chunk_id"]},
        ).scalar()
    vec = np.array([float(x) for x in got.strip("[]").split(",")])
    assert np.abs(vec - np.array(rows[0]["embedding"])).max() < 1e-6


def _many_rows(n_law=12, n_faq=6):
    """vector(1536) 칸에 들어가는 합성 행. 청크 텍스트는 의미 없고 벡터만 다르다."""
    import numpy as np

    rng = np.random.default_rng(0)
    base = _rows()[0]
    rows = []
    for source, n in (("law", n_law), ("faq", n_faq)):
        for i in range(n):
            rows.append(
                {
                    **base,
                    "chunk_id": f"{source}:{i}",
                    "source": source,
                    "text": f"{source} {i}",
                    "embedding": list(rng.random(1536) + 0.01),
                }
            )
    return rows


def test_nearest_order_matches_numpy_cosine(pg_engine):
    import numpy as np

    from cheongyak_rag.retrieval.search import dense_rank

    rows = _many_rows()
    index_db.load(pg_engine, rows)
    q = np.random.default_rng(1).random(1536) + 0.01
    law = [r for r in rows if r["source"] == "law"]
    want = dense_rank(q, np.array([r["embedding"] for r in law]), [r["chunk_id"] for r in law])[:5]
    got = index_db.nearest(pg_engine, q, "law", 5, force_index=True)
    assert [cid for cid, _ in got] == want
    assert all(0 <= d <= 2 for _, d in got)
    assert [d for _, d in got] == sorted(d for _, d in got)


def test_nearest_filters_by_source_and_returns_k(pg_engine):
    index_db.load(pg_engine, _many_rows())
    q = [0.5] * 1536
    for source in ("law", "faq"):
        got = index_db.nearest(pg_engine, q, source, 5, force_index=True)
        assert len(got) == 5
        assert all(cid.startswith(f"{source}:") for cid, _ in got)
    assert len(index_db.nearest(pg_engine, q, "faq", 10, force_index=True)) == 6  # 행이 6개뿐이다


def test_nearest_returns_k_rows_even_when_k_exceeds_default_ef_search(pg_engine):
    index_db.load(pg_engine, _many_rows(n_law=60, n_faq=1))
    got = index_db.nearest(pg_engine, [0.5] * 1536, "law", 50, force_index=True)
    assert len(got) == 50  # ef_search 기본 40이면 40개에서 멈춘다


def test_nearest_rejects_unknown_source(pg_engine):
    import pytest

    with pytest.raises(ValueError):
        index_db.nearest(pg_engine, [0.5] * 1536, "notice", 3)


def test_nearest_applies_force_index_and_ef_search_inside_its_transaction(pg_engine, monkeypatch):
    from sqlalchemy import text

    index_db.load(pg_engine, _many_rows())
    seen = []
    real = index_db._session_settings

    def spy(conn, **kw):
        real(conn, **kw)
        seen.append(
            (
                conn.execute(text("SHOW enable_seqscan")).scalar(),
                conn.execute(text("SHOW hnsw.ef_search")).scalar(),
            )
        )

    monkeypatch.setattr(index_db, "_session_settings", spy)
    q = [0.5] * 1536
    index_db.nearest(pg_engine, q, "law", 5, ef_search=100, force_index=True)
    index_db.nearest(pg_engine, q, "law", 5)
    assert seen == [("off", "100"), ("on", "40")]


def test_explain_shows_the_partial_index_when_seqscan_is_off(pg_engine):
    index_db.load(pg_engine, _many_rows())
    q = [0.5] * 1536
    assert "chunks_embedding_law_hnsw" in index_db.explain(pg_engine, q, "law", 5, seqscan_off=True)
    assert "chunks_embedding_faq_hnsw" in index_db.explain(pg_engine, q, "faq", 3, seqscan_off=True)


def test_ef_search_is_set_per_transaction_only(pg_engine):
    from sqlalchemy import text

    index_db.load(pg_engine, _many_rows())
    index_db.nearest(pg_engine, [0.5] * 1536, "law", 5, ef_search=100)
    with pg_engine.connect() as conn:
        assert conn.execute(text("SHOW hnsw.ef_search")).scalar() == "40"


def test_explain_elides_the_query_vector_literal(pg_engine):
    index_db.load(pg_engine, _many_rows())
    plan = index_db.explain(pg_engine, [0.5] * 1536, "law", 5, seqscan_off=True)
    assert "'[…]'" in plan
    assert len(plan) < 2000


def test_load_refreshes_planner_statistics(pg_engine):
    from sqlalchemy import text

    rows = _many_rows()
    index_db.load(pg_engine, rows)
    with pg_engine.connect() as conn:
        reltuples = conn.execute(
            text("SELECT reltuples FROM pg_class WHERE relname = 'chunks'")
        ).scalar()
    assert reltuples == len(rows)  # ANALYZE가 돌았다. 안 돌면 -1이거나 이전 적재의 값이다


def _mst_rows(n_a=6, n_b=6):
    """조문 행 둘 묶음 — law_mst가 'A'인 것과 'B'인 것. FAQ 한 행은 law_mst가 null이다."""
    rows = _many_rows(n_law=n_a + n_b, n_faq=1)
    law = [r for r in rows if r["source"] == "law"]
    for i, r in enumerate(law):
        r["law_mst"] = "A" if i < n_a else "B"
    return rows


def test_nearest_law_mst_keeps_only_that_mst(pg_engine):
    index_db.load(pg_engine, _mst_rows())
    got = index_db.nearest(pg_engine, [0.5] * 1536, "law", 12, law_mst="B", force_index=True)
    assert len(got) == 6
    ids = {cid for cid, _ in got}
    assert ids == {f"law:{i}" for i in range(6, 12)}


def test_nearest_without_law_mst_is_unchanged(pg_engine):
    index_db.load(pg_engine, _mst_rows())
    got = index_db.nearest(pg_engine, [0.5] * 1536, "law", 12, force_index=True)
    assert len(got) == 12


def test_nearest_law_mst_is_a_bind_parameter():
    sql = index_db.nearest_sql("law", law_mst=True).text
    assert "law_mst = :mst" in sql
    assert "law_mst" not in index_db.nearest_sql("law").text


def test_nearest_law_mst_still_uses_the_partial_index(pg_engine):
    index_db.load(pg_engine, _mst_rows())
    plan = index_db.explain(pg_engine, [0.5] * 1536, "law", 5, seqscan_off=True, law_mst="A")
    assert "chunks_embedding_law_hnsw" in plan


def test_nearest_law_mst_returns_every_row_of_that_mst_through_the_index(pg_engine):
    """HNSW는 source 전체에서 후보를 고른 뒤 MST로 거른다 — 그래도 그 MST 행을 k개까지 채운다."""
    index_db.load(pg_engine, _mst_rows(n_a=100, n_b=100))
    got = index_db.nearest(pg_engine, [0.5] * 1536, "law", 100, law_mst="B", force_index=True)
    assert len(got) == 100
