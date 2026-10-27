import json

import numpy as np
import pytest
from sqlalchemy import text

from cheongyak_rag.retrieval import index_db
from cheongyak_rag.retrieval import index_db_report as rep
from tests.conftest import alembic
from tests.fakes import FakeEmbedder
from tests.test_retrieval_query import FAQ, _row
from tests.test_retrieval_query import LAW as LAW3

# 조문 k=5가 채워지려면 조문이 5개 넘게 필요하다
LAW = LAW3 + [_row(f"제{n}조", f"제목{n}", f"{n}번째 규정을 정한다.") for n in range(4, 9)]
GOLDEN = [{"qid": f"faq-{r['q_no']}", "question": r["question"]} for r in FAQ[:3]] + [
    {"qid": "q-x", "question": "나이 기준이 어떻게 되나요?"}
]


@pytest.mark.parametrize(
    ("n", "want"), [(0, "통과"), (1, "다시 잰다"), (3, "다시 잰다"), (4, "미완")]
)
def test_count_zone_for_short_results_and_empty_tokens(n, want):
    assert rep.zone_count(n, retry_max=3) == want


@pytest.mark.parametrize(("n", "want"), [(0, "통과"), (5, "다시 잰다"), (6, "미완")])
def test_count_zone_for_cache_misses(n, want):
    assert rep.zone_count(n, retry_max=5) == want


@pytest.mark.parametrize(
    ("ratio", "want"),
    [(1.0, "통과"), (0.98, "통과"), (0.97, "다시 잰다"), (0.90, "다시 잰다"), (0.89, "미완")],
)
def test_topk_zone(ratio, want):
    assert rep.zone_topk(ratio) == want


def test_load_zone_incomplete_when_any_row_or_index_is_off():
    ok = dict(rows=568, expected=568, missing=0, extra=0, text_diff=0, vec_diff=0, no_index=[])
    assert rep.zone_load(**ok, uses_index=True) == "통과"
    assert rep.zone_load(**ok, uses_index=False) == "다시 잰다"
    assert rep.zone_load(**{**ok, "vec_diff": 1}, uses_index=True) == "미완"
    assert rep.zone_load(**{**ok, "rows": 567, "missing": 1}, uses_index=True) == "미완"
    assert rep.zone_load(**{**ok, "no_index": ["chunks_tokens_gin"]}, uses_index=True) == "미완"
    assert rep.zone_load(**{**ok, "text_diff": 2}, uses_index=False) == "미완"


def _run(pg_engine, tmp_path, *argv, embedder=None, runs=None):
    runs = runs or tmp_path
    (runs / "selected.json").write_text(json.dumps({"candidate": "article"}))
    golden = tmp_path / "golden.jsonl"
    golden.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in GOLDEN))
    code = index_db.main(
        list(argv),
        engine=pg_engine,
        embedder=embedder or FakeEmbedder(dim=1536),
        law_rows=LAW,
        faq_rows=FAQ,
        runs_dir=runs,
        golden_path=golden,
        out_md=tmp_path / "docs" / "74.md",
        out_json=tmp_path / "runs" / "74" / "last_run.json",
    )
    return code


def test_main_without_report_loads_and_prints_summary(pg_engine, tmp_path, capsys):
    assert _run(pg_engine, tmp_path) == 0
    out = capsys.readouterr().out
    with pg_engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
    want = len(index_db.build_rows(FakeEmbedder(), None, "article", law_rows=LAW, faq_rows=FAQ))
    assert n == want
    assert f"{n}행" in out
    assert not (tmp_path / "docs").exists()  # --report가 없으면 리포트를 안 쓴다


def test_main_exits_2_when_chunks_table_is_missing(pg_test_url, pg_engine, tmp_path, capsys):
    alembic(pg_test_url, "downgrade", "0003")
    try:
        assert _run(pg_engine, tmp_path) == 2
        assert "alembic upgrade head" in capsys.readouterr().err
    finally:
        alembic(pg_test_url, "upgrade", "head")


def test_report_writes_markdown_and_json_with_all_six_measures(pg_engine, tmp_path):
    assert _run(pg_engine, tmp_path, "--report") == 0
    md = (tmp_path / "docs" / "74.md").read_text(encoding="utf-8")
    run = json.loads((tmp_path / "runs" / "74" / "last_run.json").read_text(encoding="utf-8"))
    first = md.splitlines()[0]
    assert first.endswith(".") and "행" in first
    for key in ("load", "topk", "short", "cache", "rerun", "tokens"):
        assert key in run
    assert run["load"]["zone"] == "통과"
    assert run["load"]["vec_diff"] == 0 and run["load"]["text_diff"] == 0
    assert set(run["load"]["indexes"]) >= index_db_indexes()
    assert run["topk"]["default"]["law"]["ratio"] == 1.0
    assert run["short"]["count"] == 0
    assert run["rerun"]["changed"] == 0
    assert run["tokens"]["empty"] == 0
    for heading in ("EXPLAIN", "enable_seqscan"):
        assert heading in md


def index_db_indexes():
    return {"chunks_embedding_law_hnsw", "chunks_embedding_faq_hnsw", "chunks_tokens_gin"}


class _DriftingEmbedder(FakeEmbedder):
    """같은 텍스트를 두 번째 부르면 다른 벡터를 준다 — 캐시와 DB가 어긋나는 상황."""

    def embed(self, texts):
        out = super().embed(texts)
        if len(self.calls) > 1:
            out = out + 1e-3
        return out


def test_report_exits_1_after_writing_when_vectors_do_not_match_cache(pg_engine, tmp_path):
    assert _run(pg_engine, tmp_path, "--report", embedder=_DriftingEmbedder(dim=1536)) == 1
    run = json.loads((tmp_path / "runs" / "74" / "last_run.json").read_text(encoding="utf-8"))
    assert run["load"]["zone"] == "미완" and run["load"]["vec_diff"] > 0


def test_cache_miss_count_uses_the_cache_before_this_run(pg_engine, tmp_path):
    emb = FakeEmbedder(dim=1536)
    warm = index_db.build_rows(emb, None, "article", law_rows=LAW, faq_rows=FAQ)
    emb.cache.pop(warm[0]["text_sha256"])  # 한 청크만 캐시에 없다
    assert _run(pg_engine, tmp_path, "--report", embedder=emb) == 0
    run = json.loads((tmp_path / "runs" / "74" / "last_run.json").read_text(encoding="utf-8"))
    assert run["cache"]["missing_chunks"] == 1
    assert run["cache"]["missing_ids"] == [warm[0]["chunk_id"]]
    assert np.isclose(run["cache"]["golden_misses"], 4)  # golden 질문 4개는 캐시에 없었다


def test_main_exits_3_without_selected_json(pg_engine, tmp_path, capsys):
    code = index_db.main([], engine=pg_engine, embedder=FakeEmbedder(dim=1536), runs_dir=tmp_path)
    assert code == 3
    assert "selected.json" in capsys.readouterr().err


def test_lexemes_reads_tsvector_text():
    assert rep.lexemes("'가':1 '나':2,3 'it''s':4") == {"가", "나", "it's"}


def test_kiwi_forms_ignores_trailing_dot_but_not_split_tokens(monkeypatch):
    monkeypatch.setattr(rep, "tokenize", lambda _: ["2.", "시·도", "Abc"])
    assert rep.kiwi_forms("x") == {"2", "시·도", "abc"}
    assert rep.kiwi_forms("x") != rep.lexemes("'2':1 '시':2 '도':3 'abc':4")


def test_tokens_resplit_is_zero_for_plain_words(pg_engine, tmp_path):
    assert _run(pg_engine, tmp_path, "--report") == 0
    run = json.loads((tmp_path / "runs" / "74" / "last_run.json").read_text(encoding="utf-8"))
    assert run["tokens"]["resplit"] == 0


def test_render_covers_retry_and_problem_branches(pg_engine, tmp_path):
    assert _run(pg_engine, tmp_path, "--report") == 0
    run = json.loads((tmp_path / "runs" / "74" / "last_run.json").read_text(encoding="utf-8"))
    ratio = {"same": 118, "n": 123, "ratio": 118 / 123}
    run["topk"]["default"] = {"law": ratio, "faq": ratio}
    run["topk"]["zone"] = "다시 잰다"
    run["topk"]["ef100"] = {"law": ratio, "faq": ratio}
    run["topk"]["zone_ef100"] = "다시 잰다"
    run["topk"]["diffs"] = [
        {
            "qid": "faq-1",
            "question": "q|질문",
            "source": "law",
            "missing": ["law:제1조"],
            "extra": [],
        }
    ]
    run["short"].update(count=2, law=2, qids=["faq-1", "faq-2"], zone="다시 잰다")
    run["load"].update(missing=["law:제9조"], vec_diff=1, vec_diff_ids=["law:제1조"])
    run["cache"].update(missing_chunks=1, missing_ids=["faq:1"])
    md = rep.render(run)
    assert "hnsw.ef_search = 100" in md
    assert "law:제1조" in md and "q\\|질문" in md
    assert "k개보다 적게 돌아온 문항" in md and "캐시에 없던 청크" in md


def test_nearest_default_path_works_without_forcing_the_index(pg_engine):
    rows = index_db.build_rows(FakeEmbedder(dim=1536), None, "article", law_rows=LAW, faq_rows=FAQ)
    index_db.load(pg_engine, rows)
    got = index_db.nearest(pg_engine, rows[0]["embedding"], "law", 3)
    assert got[0][0] == rows[0]["chunk_id"] and len(got) == 3


def _loaded(pg_engine):
    from cheongyak_rag.retrieval.query import Index

    emb = FakeEmbedder(dim=1536)
    rows = index_db.build_rows(emb, None, "article", law_rows=LAW, faq_rows=FAQ)
    index_db.load(pg_engine, rows)
    index = Index("article", emb, law_rows=LAW, faq_rows=FAQ)
    return emb, rows, index.law + index.faq


def test_measure_load_counts_what_is_missing_changed_or_unindexed(pg_engine):
    emb, rows, chunks = _loaded(pg_engine)
    probe = rows[0]["embedding"]
    assert rep.measure_load(pg_engine, emb, chunks, probe)["zone"] == "통과"

    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM chunks WHERE chunk_id = :i"), {"i": rows[0]["chunk_id"]})
        conn.execute(
            text("UPDATE chunks SET text = 'x' WHERE chunk_id = :i"), {"i": rows[1]["chunk_id"]}
        )
        conn.execute(
            text("INSERT INTO chunks SELECT 'law:없음', source, label, path, title, text,"
                 " text_sha256, law_mst, embed_model, embedding, tokens FROM chunks"
                 " WHERE chunk_id = :i"),
            {"i": rows[2]["chunk_id"]},
        )  # fmt: skip
        conn.execute(text("DROP INDEX chunks_embedding_law_hnsw"))
    try:
        got = rep.measure_load(pg_engine, emb, chunks, probe)
    finally:  # 세션 공용 DB라 지운 인덱스를 되돌린다
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX chunks_embedding_law_hnsw ON chunks"
                    " USING hnsw (embedding vector_cosine_ops) WHERE source = 'law'"
                )
            )
    assert got["missing"] == [rows[0]["chunk_id"]]
    assert got["extra"] == ["law:없음"]
    assert got["text_diff"] == 1 and got["text_diff_ids"] == [rows[1]["chunk_id"]]
    assert got["no_index"] == ["chunks_embedding_law_hnsw"]
    assert got["uses_index"]["law"] is False
    assert got["zone"] == "미완"


def test_measure_topk_retry_zone_and_short_results(monkeypatch):
    from cheongyak_rag.retrieval.query import Index
    from cheongyak_rag.retrieval.search import dense_rank

    emb = FakeEmbedder()
    index = Index("article", emb, law_rows=LAW, faq_rows=FAQ)
    golden = [{"qid": f"q{i}", "question": f"질문 {i}"} for i in range(50)]
    qvecs = emb.embed([g["question"] for g in golden])
    law_calls = []

    def fake_nearest(engine, qv, source, k, *, ef_search=None, force_index=False):
        chunks, vecs = (
            (index.law, index.law_vecs) if source == "law" else (index.faq, index.faq_vecs)
        )
        got = dense_rank(qv, vecs, [c.chunk_id for c in chunks])[:k]
        if source == "law" and ef_search is None:
            law_calls.append(1)
            if len(law_calls) <= 3:  # 앞 세 문항: 한 개가 다른 청크로 바뀐다
                got = [*got[:-1], "law:없음"]
            if len(law_calls) == 1:  # 첫 문항은 k개보다 적게 돌아온다
                got = got[:-1]
        return [(c, 0.0) for c in got]

    monkeypatch.setattr(index_db, "nearest", fake_nearest)
    topk, short = rep.measure_topk(None, index, golden, qvecs)

    assert topk["default"]["law"]["same"] == 47 and topk["zone"] == "다시 잰다"
    assert topk["ef100"]["law"]["ratio"] == 1.0 and topk["zone_ef100"] == "통과"
    assert [d["qid"] for d in topk["diffs"]] == ["q0", "q1", "q2"]
    assert [d["extra"] for d in topk["diffs"]] == [[], ["law:없음"], ["law:없음"]]
    assert all(len(d["missing"]) == 1 for d in topk["diffs"])
    assert short["count"] == 1 and short["qids"] == ["q0"] and short["zone"] == "다시 잰다"
