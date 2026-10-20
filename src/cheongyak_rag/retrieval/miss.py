"""#131 점검 run에서 놓친 조를 청킹 후보로 다시 보기 (#138).

    python -m cheongyak_rag.retrieval.miss

묶음 A — #131 점검 질문 20개를 후보 5개로 다시 넣는다(`sanity_by_candidate`).
묶음 B — #131 hybrid가 golden에서 hit@5 = 0이던 문항을 `runs/73/`에서 다시 읽는다(`golden_misses`).
원인 — `article` 후보에서 놓친 조의 점수·코사인·글자 수(`build_causes`).
새 검색 구조를 정하지 않는다. `runs/73/selected.json`과 #131 run은 읽기만 한다.
"""

import json
from pathlib import Path

from cheongyak_rag.retrieval import chunk_eval
from cheongyak_rag.retrieval.chunk import CANDIDATES, law_chunks
from cheongyak_rag.retrieval.corpus import Article
from cheongyak_rag.retrieval.evaluate import SANITY_N, first_sentence, pick_sanity
from cheongyak_rag.retrieval.golden import RUNS_DIR
from cheongyak_rag.retrieval.search import BM25, dense_rank


def sanity_by_candidate(
    rows: list[dict],
    articles: list[Article],
    embedder,
    candidates: tuple[str, ...] = CANDIDATES,
    n: int = SANITY_N,
) -> list[dict]:
    """후보 × 점검 질문 한 줄씩. 질문은 #131 `run_sanity`와 같은 `pick_sanity`·`first_sentence`."""
    picked = pick_sanity(articles, n)
    queries = [first_sentence(a) for a in picked]
    out = []
    for cand in candidates:
        chunks = law_chunks(rows, cand)
        by_id = {c.chunk_id: c for c in chunks}
        ids = list(by_id)
        bm25 = BM25([chunk_eval._Doc(c.chunk_id, c.text) for c in chunks])
        vecs = embedder.embed([c.text for c in chunks] + queries)
        doc_vecs, query_vecs = vecs[: len(chunks)], vecs[len(chunks) :]
        for art, q, qv in zip(picked, queries, query_vecs, strict=True):
            ar = chunk_eval.article_ranks(
                [by_id[x] for x in bm25.rank(q)], [by_id[x] for x in dense_rank(qv, doc_vecs, ids)]
            )
            line = {"candidate": cand, "label": art.label, "query": q, "query_chars": len(q)}
            for name in chunk_eval.RANKERS:
                line[f"{name}_rank"] = ar.pos[name][art.label]
                line[f"{name}_top1"] = ar.rankings[name][0]
            for name in ("bm25", "dense"):
                own = by_id[f"law:{ar.paths[name][art.label]}"]
                line[f"{name}_own_path"] = own.path
                line[f"{name}_own_chars"] = len(own.text)
                line[f"{name}_own_has_query"] = q in own.text
            out.append(line)
    return out


# ── 묶음 B — golden에서 #131 hybrid가 놓친 문항 ─────────────────────────────

GAP = 3  # 실패 징후 1 B — F − L이 이 값 이상이면 찾은 쪽, 이 값 이하(음수)면 놓친 쪽


def golden_band(found: int, lost: int) -> str:
    diff = found - lost
    if diff >= GAP:
        return "찾은 것이 더 많다"
    if diff <= -GAP:
        return "놓친 것이 더 많다"
    return "차이 없음"


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def compare_golden(base: list[dict], cand: list[dict]) -> dict:
    """#131 hybrid 줄(`base`)과 후보 run 줄(`cand`)을 같은 질문끼리 대조한다.

    found = #131이 놓쳤는데 후보가 맞힌 문항, lost = #131이 맞혔는데 후보가 놓친 문항.
    순위는 정답 조 중 가장 높은 것.
    """
    if [x["qid"] for x in base] != [x["qid"] for x in cand]:
        raise ValueError("두 run의 질문(qid)과 순서가 다르다")
    found, lost = [], []
    for b, c in zip(base, cand, strict=True):
        ch = c["hybrid"]
        if b["hit@5"] == ch["hit@5"]:
            continue
        row = {
            "qid": b["qid"],
            "question": b["question"],
            "gold": b["gold"],
            "base_rank": min(b["gold_rank"].values()),
            "cand_rank": min(ch["gold_rank"].values()),
        }
        (found if b["hit@5"] == 0 else lost).append(row)
    return {
        "found_count": len(found),
        "lost_count": len(lost),
        "band": golden_band(len(found), len(lost)),
        "found": found,
        "lost": lost,
    }


def golden_misses(
    runs_dir: Path = RUNS_DIR,
    runs73: Path | None = None,
    candidates: tuple[str, ...] = CANDIDATES,
) -> dict:
    """{"missed": #131 hybrid hit@5 = 0인 qid, "candidates": {후보: compare_golden 결과}}."""
    base = _read_lines(runs_dir / "hybrid" / "results.jsonl")
    runs73 = runs73 or runs_dir / "73"
    return {
        "missed": [x["qid"] for x in base if x["hit@5"] == 0],
        "candidates": {
            cand: compare_golden(base, _read_lines(runs73 / cand / "results.jsonl"))
            for cand in candidates
        },
    }
