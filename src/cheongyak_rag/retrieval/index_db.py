"""조문·FAQ 청크와 임베딩을 Postgres `chunks` 테이블에 적재한다 (#74).

    python -m cheongyak_rag.retrieval.index_db [--report]

청크는 `query.Index`와 같은 함수(`law_chunks`·`faq_chunks`)로 만든다. 벡터는 `Embedder`의 캐시에서
가져오므로 캐시에 있는 텍스트는 API를 부르지 않는다. 적재는 한 트랜잭션에서 비우고 다시 넣는다.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from cheongyak_rag.asof import LAW_ID
from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import faq_chunks, law_chunks, load_law_rows
from cheongyak_rag.retrieval.chunk_eval import RUNS73
from cheongyak_rag.retrieval.embed import Embedder, text_key
from cheongyak_rag.retrieval.evaluate import load_golden
from cheongyak_rag.retrieval.golden import GOLDEN_PATH, load_faq
from cheongyak_rag.retrieval.query import Index, selected_candidate
from cheongyak_rag.retrieval.search import tokenize

OUT_MD = Path("docs/74-pg-index.md")
OUT_JSON = Path("runs/74/last_run.json")

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


def vec_literal(vec) -> str:
    """pgvector 텍스트 형식 `[0.1,0.2,…]`. SQL에서 `CAST(… AS vector)`로 받는다."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


INSERT = sa.text(
    "INSERT INTO chunks (chunk_id, source, label, path, title, text, text_sha256, law_mst,"
    " embed_model, embedding, tokens) VALUES (:chunk_id, :source, :label, :path, :title, :text,"
    " :text_sha256, :law_mst, :embed_model, CAST(:embedding AS vector),"
    " to_tsvector('simple', :tokens))"
)


def load(engine: Engine, rows: list[dict]) -> int:
    """한 트랜잭션에서 `chunks`를 비우고 rows를 전부 넣는다 → 넣은 행 수.

    중간에 실패하면 롤백되어 이전 행이 그대로 남는다.
    """
    params = [{**r, "embedding": vec_literal(r["embedding"])} for r in rows]
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM chunks"))
        if params:
            conn.execute(INSERT, params)
    return len(rows)


SOURCES = ("law", "faq")


def nearest_sql(source: str) -> sa.TextClause:
    """코사인 거리 순 상위 k개. `WHERE source = '…'`는 부분 인덱스 조건과 글자 그대로 같아야 한다.

    인덱스를 타려면 planner가 조건을 증명해야 해서 값을 바인드 변수가 아니라 리터럴로 쓴다.
    그래서 source는 허용 목록에서만 받는다.
    """
    if source not in SOURCES:
        raise ValueError(f"source {source!r} 없음. {SOURCES} 중 하나")
    return sa.text(
        f"SELECT chunk_id, embedding <=> CAST(:q AS vector) AS dist FROM chunks"
        f" WHERE source = '{source}' ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
    )


def _session_settings(conn, *, ef_search: int | None, seqscan_off: bool) -> None:
    """트랜잭션 안에서만 적용된다(`SET LOCAL`)."""
    if ef_search is not None:
        conn.execute(sa.text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    if seqscan_off:
        conn.execute(sa.text("SET LOCAL enable_seqscan = off"))


def nearest(
    engine: Engine,
    query_vec,
    source: str,
    k: int,
    *,
    ef_search: int | None = None,
    force_index: bool = False,
) -> list[tuple[str, float]]:
    """source의 청크 중 질문 벡터와 코사인 거리가 가까운 k개 → (chunk_id, 거리). #79가 쓴다.

    행이 568개면 planner가 인덱스 대신 전수 스캔을 고를 수 있다. `force_index`는 HNSW를 쓰게 한다.
    """
    params = {"q": vec_literal(query_vec), "k": k}
    with engine.begin() as conn:
        _session_settings(conn, ef_search=ef_search, seqscan_off=force_index)
        return [(r.chunk_id, float(r.dist)) for r in conn.execute(nearest_sql(source), params)]


def explain(
    engine: Engine,
    query_vec,
    source: str,
    k: int,
    *,
    seqscan_off: bool = False,
    ef_search: int | None = None,
) -> str:
    """`nearest`와 같은 쿼리의 EXPLAIN 원문."""
    sql = sa.text("EXPLAIN " + nearest_sql(source).text)
    with engine.begin() as conn:
        _session_settings(conn, ef_search=ef_search, seqscan_off=seqscan_off)
        rows = conn.execute(sql, {"q": vec_literal(query_vec), "k": k}).scalars()
        return "\n".join(rows)


def _table_ready(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT to_regclass('chunks')")).scalar() is not None


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    embedder=None,
    law_rows=None,
    faq_rows=None,
    runs_dir: Path = RUNS73,
    golden_path: Path = GOLDEN_PATH,
    out_md: Path = OUT_MD,
    out_json: Path = OUT_JSON,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.index_db")
    ap.add_argument(
        "--report", action="store_true", help="적재 뒤 실패 징후 1~6을 재서 리포트를 쓴다"
    )
    args = ap.parse_args(argv)

    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        return _run(
            args, engine, embedder, law_rows, faq_rows, runs_dir, golden_path, out_md, out_json
        )
    except OperationalError as e:
        print(f"DB에 연결할 수 없다: {type(e).__name__}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


def _run(args, engine, embedder, law_rows, faq_rows, runs_dir, golden_path, out_md, out_json):
    from cheongyak_rag.retrieval import index_db_report as rep

    if not _table_ready(engine):
        print("chunks 테이블이 없다. 먼저 uv run alembic upgrade head", file=sys.stderr)
        return 2
    try:
        candidate = selected_candidate(runs_dir)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    embedder = embedder or Embedder(settings.openai_embed_model)
    mst = law_mst(engine)
    cache_before = set(embedder.cache)

    def build():
        return build_rows(embedder, mst, candidate, law_rows=law_rows, faq_rows=faq_rows)

    rows = build()
    load(engine, rows)
    missing = sum(r["text_sha256"] not in cache_before for r in rows)
    n_law = sum(r["source"] == "law" for r in rows)
    print(
        f"적재: {len(rows)}행 (조문 {n_law} · FAQ {len(rows) - n_law}) · 청킹 {candidate}"
        f" · law_mst {mst or 'null'} · 캐시에 없던 청크 {missing}개"
        f" · 임베딩 API 호출 {embedder.api_calls}회"
    )
    if not args.report:
        return 0

    # 실패 징후 5 — 같은 입력으로 한 번 더 적재해 바뀐 것이 있는지 본다
    first = rep.snapshot(engine)
    load(engine, build())
    second = rep.snapshot(engine)

    index = Index(candidate, embedder, law_rows=law_rows, faq_rows=faq_rows)
    golden = load_golden(golden_path)
    qvecs = embedder.embed([g["question"] for g in golden])
    topk, short = rep.measure_topk(engine, index, golden, qvecs)
    run = {
        "run_at": rep.now(),
        "candidate": candidate,
        "embed_model": embedder.model,
        "law_mst": mst,
        "load": rep.measure_load(engine, embedder, index.law + index.faq, qvecs[0]),
        "topk": topk,
        "short": short,
        "cache": rep.measure_cache(rows, cache_before, golden, embedder.api_calls),
        "rerun": rep.measure_rerun(first, second),
        "tokens": rep.measure_tokens(engine),
        "versions": rep.versions(engine),
    }
    rep.write(out_md, rep.render(run))
    rep.write(out_json, rep.dump(run))
    print(rep.summary_line(run))
    zones = {k: run[k]["zone"] for k in ("load", "topk", "short", "cache", "rerun", "tokens")}
    print("구간: " + " · ".join(f"{k} {z}" for k, z in zones.items()))
    print(f"→ {out_md} · {out_json}")
    return 1 if run["load"]["zone"] == "미완" else 0


if __name__ == "__main__":
    sys.exit(main())
