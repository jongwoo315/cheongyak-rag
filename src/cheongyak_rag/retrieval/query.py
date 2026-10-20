"""질문 한 줄 검색 — 고른 청킹 구조로 조문 상위 k개와 FAQ 상위 n개 (#73).

    python -m cheongyak_rag.retrieval.query "무주택 세대구성원 기준이 뭔가요?"

고른 후보는 `runs/73/selected.json`(`chunk_report`가 쓴다). 조문은 조 단위로 중복 없이 상위 k개를
돌려주고, 각 조에서는 가장 높이 오른 청크를 준다. #139가 이 함수를 generator 입력으로 쓴다.
"""

import argparse
import json
import sys
from pathlib import Path

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import Chunk, faq_chunks, law_chunks, load_law_rows
from cheongyak_rag.retrieval.chunk_eval import RUNS73, _Doc, article_ranks
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.golden import load_faq
from cheongyak_rag.retrieval.search import BM25, dense_rank, rrf

SHOW_CHARS = 80


class Index:
    """후보 하나의 조문·FAQ 청크 색인. 메모리에서 전수 계산한다."""

    def __init__(self, candidate: str, embedder, *, law_rows=None, faq_rows=None):
        law_rows = load_law_rows() if law_rows is None else law_rows
        faq_rows = load_faq() if faq_rows is None else faq_rows
        self.embedder = embedder
        self.law = law_chunks(law_rows, candidate)
        self.faq = faq_chunks(faq_rows, {r["label"] for r in law_rows if not r["deleted"]})
        vecs = embedder.embed([c.text for c in self.law + self.faq])
        self.law_vecs, self.faq_vecs = vecs[: len(self.law)], vecs[len(self.law) :]
        self.law_bm25 = BM25([_Doc(c.chunk_id, c.text) for c in self.law])
        self.faq_bm25 = BM25([_Doc(c.chunk_id, c.text) for c in self.faq])
        self.law_by_id = {c.chunk_id: c for c in self.law}
        self.faq_by_id = {c.chunk_id: c for c in self.faq}
        self.law_by_path = {c.path: c for c in self.law}

    def search(
        self, question: str, k: int = 5, *, faq_k: int = 3, exclude_same_question: bool = False
    ) -> dict[str, list[Chunk]]:
        qv = self.embedder.embed([question])[0]
        ar = article_ranks(
            [self.law_by_id[x] for x in self.law_bm25.rank(question)],
            [
                self.law_by_id[x]
                for x in dense_rank(qv, self.law_vecs, [c.chunk_id for c in self.law])
            ],
        )
        law = [self.law_by_path[ar.best_path(label)] for label in ar.rankings["hybrid"][:k]]
        bm = self.faq_bm25.rank(question)
        dn = dense_rank(qv, self.faq_vecs, [c.chunk_id for c in self.faq])
        hy = [x for x, _ in rrf([bm, dn])]
        faq = [self.faq_by_id[x] for x in hy]
        if exclude_same_question:
            faq = [c for c in faq if c.text.partition("\n")[0] != question]
        return {"law": law, "faq": faq[:faq_k]}


def format_result(result: dict[str, list[Chunk]]) -> str:
    """조문은 `조 · 위치 · 본문 앞 80자`, FAQ는 `Q번호 · 질문`."""
    out = [f"조문 상위 {len(result['law'])}개"]
    for i, c in enumerate(result["law"], start=1):
        text = " ".join(c.text.split())[:SHOW_CHARS]
        out.append(f"{i}. {c.label} · {c.path} · {text}")
    out.append(f"FAQ 상위 {len(result['faq'])}개")
    for i, c in enumerate(result["faq"], start=1):
        out.append(f"{i}. {c.path} · {c.text.partition(chr(10))[0]}")
    return "\n".join(out)


def selected_candidate(runs_dir: Path = RUNS73) -> str:
    path = runs_dir / "selected.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음. 먼저 python -m cheongyak_rag.retrieval.chunk_report")
    return json.loads(path.read_text(encoding="utf-8"))["candidate"]


def search(question: str, k: int = 5, *, faq_k: int = 3, runs_dir: Path = RUNS73, embedder=None):
    """고른 후보로 검색한다. 호출마다 색인을 다시 만든다 — 반복해 부르면 `Index`를 직접 쓴다."""
    index = Index(selected_candidate(runs_dir), embedder or Embedder(settings.openai_embed_model))
    return index.search(question, k, faq_k=faq_k)


def main(
    argv: list[str] | None = None,
    runs_dir: Path = RUNS73,
    embedder=None,
    law_rows=None,
    faq_rows=None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.query")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5, help="조문 개수")
    ap.add_argument("--faq-k", type=int, default=3, help="FAQ 개수")
    args = ap.parse_args(argv)
    try:
        candidate = selected_candidate(runs_dir)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    embedder = embedder or Embedder(settings.openai_embed_model)
    index = Index(candidate, embedder, law_rows=law_rows, faq_rows=faq_rows)
    print(f"구조: {candidate}")
    print(format_result(index.search(args.question, args.k, faq_k=args.faq_k)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
