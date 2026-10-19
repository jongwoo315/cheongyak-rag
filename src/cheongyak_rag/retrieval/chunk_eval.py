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
from functools import cache
from pathlib import Path
from typing import NamedTuple

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import (
    CANDIDATES,
    Chunk,
    faq_chunks,
    law_chunks,
    load_law_rows,
)
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.evaluate import K1, RRF_K, B, K, _commit, _dump, load_golden, metrics
from cheongyak_rag.retrieval.golden import RUNS_DIR, load_faq
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


class ArticleRanks(NamedTuple):
    rankings: dict[str, list[str]]  # bm25 · dense · hybrid 조 순위
    pos: dict[str, dict[str, int]]  # 순위 이름 → 조 → 순위(1부터)
    paths: dict[str, dict[str, str]]  # bm25 · dense → 조 → 그 조의 가장 높은 청크 path

    def best_path(self, label: str) -> str:
        """두 순위 중 그 조가 더 높이 오른 쪽의 청크 path. 같으면 BM25."""
        bm_r, dn_r = self.pos["bm25"][label], self.pos["dense"][label]
        return self.paths["bm25" if bm_r <= dn_r else "dense"][label]


def article_ranks(
    bm_chunks: list[Chunk], dn_chunks: list[Chunk], rrf_k: int = RRF_K
) -> ArticleRanks:
    """BM25·dense 청크 순위 → 조 순위 둘 + 그 둘을 RRF로 합친 hybrid 조 순위."""
    bm_labels, bm_paths = article_view(bm_chunks)
    dn_labels, dn_paths = article_view(dn_chunks)
    hybrid = [label for label, _ in rrf([bm_labels, dn_labels], k=rrf_k)]
    rankings = {"bm25": bm_labels, "dense": dn_labels, "hybrid": hybrid}
    pos = {name: {x: r for r, x in enumerate(rk, start=1)} for name, rk in rankings.items()}
    return ArticleRanks(rankings, pos, {"bm25": bm_paths, "dense": dn_paths})


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
        ar = article_ranks(
            [by_id[x] for x in bm25.rank(g["question"])],
            [by_id[x] for x in dense_rank(query_vecs[i], doc_vecs, ids)],
            rrf_k,
        )
        rankings, pos = ar.rankings, ar.pos
        detail = {
            label: {
                "bm25": pos["bm25"][label],
                "dense": pos["dense"][label],
                "hybrid": pos["hybrid"][label],
                "path": ar.best_path(label),
            }
            for label in g["gold"]
        }
        lines.append(
            {
                "qid": g["qid"],
                "q_no": g["q_no"],
                "question": g["question"],
                "gold": g["gold"],
                "has_article_in_question": g["has_article_in_question"],
                "top5": rankings["hybrid"][:K],
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


# ── FAQ (leave-self-out) ────────────────────────────────────────────────


@cache
def _tokens(text: str) -> tuple[str, ...]:
    return tuple(tokenize(text))


def _cached_tokenize(text: str) -> list[str]:
    """질문마다 BM25를 새로 세우므로 같은 청크를 다시 형태소 분석하지 않게 한다."""
    return list(_tokens(text))


def _question(c: Chunk) -> str:
    return c.text.partition("\n")[0]


def _faq_rankings(chunks: list[Chunk], golden: list[dict], embedder, leave_self_out: bool):
    """질문마다 (같은 질문 쌍 id 집합, {순위 이름: 청크 id 순위}).

    leave_self_out이면 그 집합을 색인에서도 뺀다(BM25 idf에 자기가 안 들어간다).
    """
    ids = [c.chunk_id for c in chunks]
    vecs = embedder.embed([c.text for c in chunks] + [g["question"] for g in golden])
    doc_vecs, query_vecs = vecs[: len(chunks)], vecs[len(chunks) :]
    docs = [_Doc(c.chunk_id, c.text) for c in chunks]
    shared: dict[frozenset, BM25] = {}
    for i, g in enumerate(golden):
        group = frozenset(c.chunk_id for c in chunks if _question(c) == g["question"])
        drop = group if leave_self_out else frozenset()
        keep = [j for j, x in enumerate(ids) if x not in drop]
        if drop not in shared:
            shared[drop] = BM25([docs[j] for j in keep], tokenizer=_cached_tokenize)
        bm = shared[drop].rank(g["question"])
        dn = dense_rank(query_vecs[i], doc_vecs[keep], [ids[j] for j in keep])
        hy = [x for x, _ in rrf([bm, dn])]
        yield g, group, {"bm25": bm, "dense": dn, "hybrid": hy}


def evaluate_faq(chunks: list[Chunk], golden: list[dict], embedder) -> list[dict]:
    """golden 문항마다 FAQ 청크를 검색한다. 자기 쌍과 같은 질문 쌍은 뺀다.

    faq_hit@k: 상위 k개 중 하나라도 `cited`가 정답 조와 겹치면 1.
    """
    by_id = {c.chunk_id: c for c in chunks}
    lines = []
    for g, group, rankings in _faq_rankings(chunks, golden, embedder, leave_self_out=True):
        line = {
            "qid": g["qid"],
            "q_no": g["q_no"],
            "question": g["question"],
            "gold": g["gold"],
            "excluded": sorted(by_id[x].meta["q_no"] for x in group),
        }
        for name, ranking in rankings.items():
            top = [by_id[x] for x in ranking[:K]]
            hits = [bool(set(c.meta["cited"]) & set(g["gold"])) for c in top]
            line[name] = {
                "top5": [c.meta["q_no"] for c in top],
                "faq_hit@1": int(hits[0]),
                "faq_hit@5": int(any(hits)),
            }
        lines.append(line)
    return lines


def leak_count(lines: list[dict]) -> int:
    """상위 5개에 자기 쌍·같은 질문 쌍이 들어온 횟수(순위 이름별로 센다). 0이어야 한다."""
    return sum(len(set(x[r]["top5"]) & set(x["excluded"])) for x in lines for r in RANKERS)


def self_check(chunks: list[Chunk], golden: list[dict], embedder) -> dict:
    """자기 쌍을 넣고 돌렸을 때 1위가 자기 쌍(또는 같은 질문 쌍)인 비율. 검색 버그 점검이다."""
    by_id = {c.chunk_id: c for c in chunks}
    hit = dict.fromkeys(RANKERS, 0)
    misses = []
    for g, group, rankings in _faq_rankings(chunks, golden, embedder, leave_self_out=False):
        for name, ranking in rankings.items():
            if ranking[0] in group:
                hit[name] += 1
            else:
                misses.append(
                    {"qid": g["qid"], "ranker": name, "top1_q_no": by_id[ranking[0]].meta["q_no"]}
                )
    n = len(golden)
    return {"n": n, "self_top1": {r: hit[r] / n for r in RANKERS}, "misses": misses}


def write_faq_run(
    runs_dir: Path, lines: list[dict], check: dict, chunks: list[Chunk], embedder, new_texts: int
) -> None:
    config = _config(
        embedder, len(chunks), new_texts, chunk_count=len(chunks), question_count=len(lines)
    )
    out = runs_dir / "faq"
    _write(out, dump_lines(lines), config)
    check = {**check, "leak_count": leak_count(lines)}
    (out / "self_check.json").write_text(
        json.dumps(check, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _mean(lines: list[dict], ranker: str, key: str) -> float:
    return sum(x[ranker][key] for x in lines) / len(lines)


def _faq_main(runs_dir: Path, embedder) -> int:
    rows = load_law_rows()
    chunks = faq_chunks(load_faq(), {r["label"] for r in rows if not r["deleted"]})
    golden = load_golden()
    cache_before = len(getattr(embedder, "cache", {}))
    lines = evaluate_faq(chunks, golden, embedder)
    check = self_check(chunks, golden, embedder)
    new_texts = len(getattr(embedder, "cache", {})) - cache_before
    write_faq_run(runs_dir, lines, check, chunks, embedder, new_texts)
    n = len(lines)
    for r in RANKERS:
        h1 = sum(x[r]["faq_hit@1"] for x in lines) / n
        h5 = sum(x[r]["faq_hit@5"] for x in lines) / n
        print(f"faq {r}: faq_hit@1 {h1:.3f} · faq_hit@5 {h5:.3f}")
    print(
        "자기 쌍 1위 비율 "
        + " · ".join(f"{r} {check['self_top1'][r]:.3f}" for r in RANKERS)
        + f" · 상위 5개에 자기·같은 질문 쌍 {leak_count(lines)}개"
    )
    print(
        f"OpenAI 호출 {embedder.api_calls}회 · 새로 임베딩한 텍스트 {new_texts}개"
        f" → {runs_dir / 'faq'}"
    )
    return 0


def main(
    argv: list[str] | None = None,
    runs_dir: Path = RUNS73,
    embedder=None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.chunk_eval")
    ap.add_argument("--candidate", choices=CANDIDATES)
    ap.add_argument("--faq", action="store_true")
    args = ap.parse_args(argv)
    if bool(args.candidate) == args.faq:
        ap.error("--candidate 와 --faq 중 하나만 준다")
    embedder = embedder or Embedder(settings.openai_embed_model)
    if args.faq:
        return _faq_main(runs_dir, embedder)
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
