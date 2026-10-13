"""검색 run 실행과 지표 (#131).

    python -m cheongyak_rag.retrieval.evaluate --run bm25|dense|hybrid
    python -m cheongyak_rag.retrieval.evaluate --sanity     # 검색 버그 점검 (조문 첫 문장 → 그 조)

질문마다 잰다. 평균만 남기면 같은 질문에서의 차이를 못 구한다.
`results.jsonl`에는 시각을 넣지 않는다 — 같은 입력이면 바이트까지 같아야 한다(재현성).
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.corpus import LAW_PATH, Article, load_articles
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.golden import GOLDEN_PATH, RUNS_DIR
from cheongyak_rag.retrieval.search import BM25, KEEP_TAGS, dense_rank, rrf, tokenize

K = 5
K1, B, RRF_K = 1.2, 0.75, 60
RUNS = ("bm25", "dense", "hybrid")
SANITY_N = 20
SENTENCE_END = re.compile(r"(?<=[다요])\.(?=\s|$)")


def metrics(ranking: list[str], gold: list[str]) -> dict:
    """ranking은 전체 순위(1위가 앞). gold는 정답 조."""
    rank = {label: i for i, label in enumerate(ranking, start=1)}
    gold_rank = {g: rank[g] for g in gold}
    top = set(ranking[:K])
    return {
        "recall@5": len(top & set(gold)) / len(gold),
        "hit@1": int(ranking[0] in gold),
        "hit@5": int(bool(top & set(gold))),
        "mrr": 1 / min(gold_rank.values()),
        "gold_rank": gold_rank,
    }


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음. 먼저 python -m cheongyak_rag.retrieval.golden")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def evaluate_run(
    run: str,
    golden: list[dict],
    articles: list[Article],
    embedder,
    *,
    tokenizer=tokenize,
    k1: float = K1,
    b: float = B,
    rrf_k: int = RRF_K,
) -> list[dict]:
    labels = [a.label for a in articles]
    questions = [g["question"] for g in golden]
    bm25 = BM25(articles, tokenizer=tokenizer, k1=k1, b=b) if run != "dense" else None
    if run != "bm25":
        vecs = embedder.embed([a.text for a in articles] + questions)  # 한 요청에 묶는다
        doc_vecs, query_vecs = vecs[: len(articles)], vecs[len(articles) :]
    lines = []
    for i, g in enumerate(golden):
        bm_rank = bm25.rank(g["question"]) if bm25 else None
        dn_rank = dense_rank(query_vecs[i], doc_vecs, labels) if run != "bm25" else None
        extra = {}
        if run == "bm25":
            ranking = bm_rank
        elif run == "dense":
            ranking = dn_rank
        else:
            fused = rrf([bm_rank, dn_rank], k=rrf_k)
            ranking = [label for label, _ in fused]
            score = dict(fused)
            bm_pos = {x: r for r, x in enumerate(bm_rank, start=1)}
            dn_pos = {x: r for r, x in enumerate(dn_rank, start=1)}
            extra["gold_detail"] = {
                x: {"bm25": bm_pos[x], "dense": dn_pos[x], "rrf": score[x]} for x in g["gold"]
            }
        lines.append(
            {
                "qid": g["qid"],
                "q_no": g["q_no"],
                "question": g["question"],
                "gold": g["gold"],
                "has_article_in_question": g["has_article_in_question"],
                "top5": ranking[:K],
                **metrics(ranking, g["gold"]),
                **extra,
            }
        )
    return lines


def _dump(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def write_run(runs_dir: Path, run: str, lines: list[dict], articles: list[Article], embedder):
    out = runs_dir / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text(_dump(lines), encoding="utf-8")
    config = {
        "run": run,
        "model": getattr(embedder, "model", None) if run != "bm25" else None,
        "k1": K1 if run != "dense" else None,
        "b": B if run != "dense" else None,
        "rrf_k": RRF_K if run == "hybrid" else None,
        "bm25_tags": sorted(KEEP_TAGS) if run != "dense" else None,
        "doc_count": len(articles),
        "question_count": len(lines),
        "embedding_api_calls": embedder.api_calls if run != "bm25" else 0,
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": _commit(),
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def first_sentence(article: Article) -> str:
    """머리 줄 다음 첫 줄의 첫 문장. 조 문장이 머리뿐이면 첫 항이 그 줄이다."""
    body = article.text.split("\n")[1]
    m = SENTENCE_END.search(body)
    return body[: m.end()] if m else body


def pick_sanity(articles: list[Article], n: int = SANITY_N) -> list[Article]:
    """조 번호 순으로 고르게 n개. 첫 조와 끝 조를 포함한다."""
    return [articles[round(i * (len(articles) - 1) / (n - 1))] for i in range(n)]


def run_sanity(runs_dir: Path, articles: list[Article], embedder, n: int = SANITY_N) -> dict:
    """현행 조문 n개의 첫 문장을 질문으로 넣어 그 조가 1위인지 본다. 검색 버그 점검이다."""
    picked = pick_sanity(articles, n)
    queries = [first_sentence(a) for a in picked]
    bm25 = BM25(articles)
    labels = [a.label for a in articles]
    vecs = embedder.embed([a.text for a in articles] + queries)
    doc_vecs, query_vecs = vecs[: len(articles)], vecs[len(articles) :]
    rows = []
    for art, q, qv in zip(picked, queries, query_vecs, strict=True):
        bm, dn = bm25.rank(q), dense_rank(qv, doc_vecs, labels)
        rows.append(
            {
                "label": art.label,
                "query": q,
                "bm25_rank": bm.index(art.label) + 1,
                "bm25_top1": bm[0],
                "dense_rank": dn.index(art.label) + 1,
                "dense_top1": dn[0],
            }
        )
    out = runs_dir / "sanity"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text(_dump(rows), encoding="utf-8")
    return {
        "n": len(rows),
        "bm25_top1": sum(r["bm25_rank"] == 1 for r in rows),
        "dense_top1": sum(r["dense_rank"] == 1 for r in rows),
        "bm25_misses": [r for r in rows if r["bm25_rank"] != 1],
        "dense_misses": [r for r in rows if r["dense_rank"] != 1],
    }


def main(argv: list[str] | None = None, runs_dir: Path = RUNS_DIR) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.evaluate")
    ap.add_argument("--run", choices=RUNS)
    ap.add_argument("--sanity", action="store_true")
    args = ap.parse_args(argv)
    if bool(args.run) == args.sanity:
        ap.error("--run 과 --sanity 중 하나만 준다")
    articles = load_articles(LAW_PATH)
    embedder = Embedder(settings.openai_embed_model)
    if args.sanity:
        res = run_sanity(runs_dir, articles, embedder)
        n = res["n"]
        print(f"점검: BM25 {res['bm25_top1']}/{n}개 1위 · dense {res['dense_top1']}/{n}개 1위")
        for name in ("bm25", "dense"):
            for r in res[f"{name}_misses"]:
                top1, own = r[f"{name}_top1"], r[f"{name}_rank"]
                q = r["query"][:50]
                print(f"  {name} 놓침: {r['label']} 「{q}」 → 1위 {top1} (자기 {own}위)")
        print(f"OpenAI 호출 {embedder.api_calls}회")
        return 0
    lines = evaluate_run(args.run, load_golden(), articles, embedder)
    write_run(runs_dir, args.run, lines, articles, embedder)
    n = len(lines)
    mean = lambda k: sum(x[k] for x in lines) / n  # noqa: E731
    print(
        f"{args.run}: 질문 {n}개 · recall@5 {mean('recall@5'):.3f} · hit@1 {mean('hit@1'):.3f}"
        f" · hit@5 {mean('hit@5'):.3f} · mrr {mean('mrr'):.3f}"
    )
    print(
        f"OpenAI 호출 {embedder.api_calls if args.run != 'bm25' else 0}회 → {runs_dir / args.run}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
