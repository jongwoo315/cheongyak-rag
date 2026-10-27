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
