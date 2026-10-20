"""#131 점검 run에서 놓친 조를 청킹 후보로 다시 보기 (#138).

    python -m cheongyak_rag.retrieval.miss

묶음 A — #131 점검 질문 20개를 후보 5개로 다시 넣는다(`sanity_by_candidate`).
묶음 B — #131 hybrid가 golden에서 hit@5 = 0이던 문항을 `runs/73/`에서 다시 읽는다(`golden_misses`).
원인 — `article` 후보에서 놓친 조의 점수·코사인·글자 수(`build_causes`).
새 검색 구조를 정하지 않는다. `runs/73/selected.json`과 #131 run은 읽기만 한다.
"""

import json
import statistics
from pathlib import Path

import numpy as np

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


# ── 원인 — `article` 후보에서 놓친 조 ────────────────────────────────────────

TOP_TERMS = 5  # 낱말별 기여 중 보여줄 상위 개수
SUM_TOLERANCE = 1e-9  # 실패 징후 4 — 낱말별 기여의 합과 BM25.scores의 차


def bm25_terms(bm25: BM25, query: str, label: str) -> dict[str, float]:
    """질문 낱말마다 그 문서의 BM25 점수 기여(idf × tf 항). 기여가 큰 순서.

    `BM25.scores`와 같은 식이다 — 질문 낱말은 집합으로 세고, 문서에 없는 낱말은 기여 0이라 뺀다.
    """
    i = bm25.labels.index(label)
    tf, length = bm25.tf[i], bm25.lengths[i]
    norm = bm25.k1 * (1 - bm25.b + bm25.b * length / bm25.avg_len)
    terms = set(bm25.tokenizer(query)) & bm25.idf.keys()
    contrib = {t: bm25.idf[t] * tf[t] * (bm25.k1 + 1) / (tf[t] + norm) for t in terms if t in tf}
    return dict(sorted(contrib.items(), key=lambda kv: (-kv[1], kv[0])))


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def _terms_text(terms: dict[str, float]) -> str:
    top = list(terms.items())[:TOP_TERMS]
    return ", ".join(f"{t} {v:.3f}" for t, v in top) or "없음"


def cites_number(cause: dict) -> bool:
    """원인 문장이 그 원인의 점수·코사인 값을 글자로 담고 있나(실패 징후 3)."""
    return any(
        f"{cause[k]:.3f}" in cause["sentence"] for k in ("own_score", "own_cos") if k in cause
    )


def build_causes(
    lines: list[dict], articles: list[Article], rows: list[dict], embedder
) -> list[dict]:
    """`article` 후보 점검 줄 중 자기 조가 1위가 아니던 (retriever, 조) 마다 원인 숫자와 문장."""
    misses = [
        (name, x)
        for x in lines
        if x["candidate"] == "article"
        for name in ("bm25", "dense")
        if x[f"{name}_rank"] != 1
    ]
    if not misses:
        return []
    by_label = {a.label: i for i, a in enumerate(articles)}
    chars = [len(a.text) for a in articles]
    median = statistics.median(chars)
    bm25 = BM25(articles)
    items = law_chunks(rows, "item")
    queries = list(dict.fromkeys(x["query"] for _, x in misses))
    vecs = embedder.embed([a.text for a in articles] + [c.text for c in items] + queries)
    art_vecs = vecs[: len(articles)]
    item_vecs = vecs[len(articles) : len(articles) + len(items)]
    query_vecs = dict(zip(queries, vecs[len(articles) + len(items) :], strict=True))
    out = []
    for name, x in misses:
        label, top1, q = x["label"], x[f"{name}_top1"], x["query"]
        own_i, top_i = by_label[label], by_label[top1]
        cause = {
            "retriever": name,
            "label": label,
            "query": q,
            "own_rank": x[f"{name}_rank"],
            "top1": top1,
            "own_chars": chars[own_i],
            "top1_chars": chars[top_i],
            "median_chars": median,
            "own_tokens": bm25.lengths[own_i],
            "top1_tokens": bm25.lengths[top_i],
            "avg_tokens": bm25.avg_len,
        }
        size = (
            f"자기 조 {chars[own_i]}자(조문 글자 수 중앙값 {median:g}자의"
            f" {chars[own_i] / median:.1f}배)·토큰 {bm25.lengths[own_i]}개,"
            f" 1위 {top1} {chars[top_i]}자·토큰 {bm25.lengths[top_i]}개"
        )
        if name == "bm25":
            own_t, top_t = bm25_terms(bm25, q, label), bm25_terms(bm25, q, top1)
            scores = bm25.scores(q)
            cause |= {
                "own_score": scores[own_i],
                "top1_score": scores[top_i],
                "own_terms": own_t,
                "top1_terms": top_t,
                "own_terms_gap": abs(sum(own_t.values()) - scores[own_i]),
                "top1_terms_gap": abs(sum(top_t.values()) - scores[top_i]),
            }
            cause["sentence"] = (
                f"{label}: BM25 점수 {scores[own_i]:.3f}로 {x['bm25_rank']}위,"
                f" 1위 {top1} {scores[top_i]:.3f}."
                f" 낱말별 기여 — 자기 조 {_terms_text(own_t)} / 1위 조 {_terms_text(top_t)}."
                f" {size}(토큰 평균 {bm25.avg_len:.1f}개)."
            )
        else:
            qv = query_vecs[q]
            own_cos, top_cos = _cos(qv, art_vecs[own_i]), _cos(qv, art_vecs[top_i])
            own_items = [
                (c.path, _cos(qv, v))
                for c, v in zip(items, item_vecs, strict=True)
                if c.label == label
            ]
            best_path, best_cos = max(own_items, key=lambda kv: kv[1])
            cause |= {
                "own_cos": own_cos,
                "top1_cos": top_cos,
                "item_best_path": best_path,
                "item_best_cos": best_cos,
            }
            cause["sentence"] = (
                f"{label}: 질문과의 코사인 {own_cos:.3f}로 {x['dense_rank']}위,"
                f" 1위 {top1} {top_cos:.3f}. {size}."
                f" `item` 후보에서 자기 조 청크 중 질문과 가장 가까운 {best_path}의"
                f" 코사인은 {best_cos:.3f}."
            )
        out.append(cause)
    return out
