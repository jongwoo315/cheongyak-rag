"""청킹 후보별 검색 run (#73).

    python -m cheongyak_rag.retrieval.chunk_eval --candidate <후보>
    python -m cheongyak_rag.retrieval.chunk_eval --faq

청크 순위를 조 순위로 바꿔(조의 가장 높은 청크만 남긴다) #131과 같은 지표로 잰다.
hybrid = 조 순위끼리 RRF. `results.jsonl`에는 시각을 넣지 않는다 — 같은 입력이면 바이트까지 같다.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import CANDIDATES, Chunk, law_chunks, load_law_rows
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.evaluate import K1, RRF_K, B, K, _commit, _dump, load_golden, metrics
from cheongyak_rag.retrieval.golden import RUNS_DIR
from cheongyak_rag.retrieval.search import BM25, KEEP_TAGS, dense_rank, rrf, tokenize

RUNS73 = RUNS_DIR / "73"
RANKERS = ("bm25", "dense", "hybrid")


class _Doc(NamedTuple):
    """BM25는 `label`로 문서를 가른다. 청크는 조가 겹치므로 청크 id를 label로 준다."""

    label: str
    text: str


def article_view(chunk_ranking: list[Chunk]) -> tuple[list[str], dict[str, str]]:
    """청크 순위 → (조 순위, 조 → 그 조에서 가장 높이 오른 청크의 path)."""
    paths: dict[str, str] = {}
    for c in chunk_ranking:
        paths.setdefault(c.label, c.path)  # 첫(가장 높은) 청크만 남긴다
    return list(paths), paths


def article_ranking(chunk_ranking: list[Chunk]) -> list[str]:
    return article_view(chunk_ranking)[0]


def evaluate_candidate(
    chunks: list[Chunk],
    golden: list[dict],
    embedder,
    *,
    tokenizer=tokenize,
    k1: float = K1,
    b: float = B,
    rrf_k: int = RRF_K,
) -> list[dict]:
    """질문 한 줄에 bm25·dense·hybrid 지표와 정답 조별 순위·path."""
    by_id = {c.chunk_id: c for c in chunks}
    ids = [c.chunk_id for c in chunks]
    questions = [g["question"] for g in golden]
    bm25 = BM25([_Doc(c.chunk_id, c.text) for c in chunks], tokenizer=tokenizer, k1=k1, b=b)
    vecs = embedder.embed([c.text for c in chunks] + questions)  # 한 요청에 묶는다
    doc_vecs, query_vecs = vecs[: len(chunks)], vecs[len(chunks) :]
    lines = []
    for i, g in enumerate(golden):
        bm_labels, bm_paths = article_view([by_id[x] for x in bm25.rank(g["question"])])
        dn_labels, dn_paths = article_view(
            [by_id[x] for x in dense_rank(query_vecs[i], doc_vecs, ids)]
        )
        hy_labels = [label for label, _ in rrf([bm_labels, dn_labels], k=rrf_k)]
        rankings = {"bm25": bm_labels, "dense": dn_labels, "hybrid": hy_labels}
        pos = {name: {x: r for r, x in enumerate(rk, start=1)} for name, rk in rankings.items()}
        detail = {}
        for label in g["gold"]:
            bm_r, dn_r = pos["bm25"][label], pos["dense"][label]
            # 두 순위 중 더 높이 오른 쪽의 청크. 같으면 BM25
            path = bm_paths[label] if bm_r <= dn_r else dn_paths[label]
            detail[label] = {
                "bm25": bm_r,
                "dense": dn_r,
                "hybrid": pos["hybrid"][label],
                "path": path,
            }
        lines.append(
            {
                "qid": g["qid"],
                "q_no": g["q_no"],
                "question": g["question"],
                "gold": g["gold"],
                "has_article_in_question": g["has_article_in_question"],
                "top5": hy_labels[:K],
                **{name: metrics(rk, g["gold"]) for name, rk in rankings.items()},
                "gold_detail": detail,
            }
        )
    return lines


def dump_lines(rows: list[dict]) -> str:
    return _dump(rows)


def _config(embedder, count: int, new_texts: int, **extra) -> dict:
    return {
        "model": getattr(embedder, "model", None),
        "k1": K1,
        "b": B,
        "rrf_k": RRF_K,
        "bm25_tags": sorted(KEEP_TAGS),
        **extra,
        "embedding_api_calls": embedder.api_calls,
        "new_embedded_texts": new_texts,
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": _commit(),
    }


def _write(out: Path, results: str, config: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text(results, encoding="utf-8")
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_candidate_run(
    runs_dir: Path, candidate: str, lines: list[dict], chunks: list[Chunk], embedder, new_texts: int
) -> None:
    config = _config(
        embedder,
        len(chunks),
        new_texts,
        candidate=candidate,
        chunk_count=len(chunks),
        question_count=len(lines),
    )
    _write(runs_dir / candidate, dump_lines(lines), config)


def _mean(lines: list[dict], ranker: str, key: str) -> float:
    return sum(x[ranker][key] for x in lines) / len(lines)


def main(
    argv: list[str] | None = None,
    runs_dir: Path = RUNS73,
    embedder=None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.chunk_eval")
    ap.add_argument("--candidate", choices=CANDIDATES)
    args = ap.parse_args(argv)
    if not args.candidate:
        ap.error("--candidate 를 준다")
    embedder = embedder or Embedder(settings.openai_embed_model)
    cache_before = len(getattr(embedder, "cache", {}))
    chunks = law_chunks(load_law_rows(), args.candidate)
    lines = evaluate_candidate(chunks, load_golden(), embedder)
    new_texts = len(getattr(embedder, "cache", {})) - cache_before
    write_candidate_run(runs_dir, args.candidate, lines, chunks, embedder, new_texts)
    stats = " · ".join(f"{r} recall@5 {_mean(lines, r, 'recall@5'):.3f}" for r in RANKERS)
    print(f"{args.candidate}: 청크 {len(chunks)}개 · 질문 {len(lines)}개 · {stats}")
    print(
        f"OpenAI 호출 {embedder.api_calls}회 · 새로 임베딩한 텍스트 {new_texts}개"
        f" → {runs_dir / args.candidate}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
