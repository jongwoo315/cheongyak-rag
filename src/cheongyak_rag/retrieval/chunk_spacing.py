"""붙은 단어 측정 (#73, 실패 징후 6).

    python -m cheongyak_rag.retrieval.chunk_spacing

FAQ 본문 질문에는 공백이 빠진 곳이 있다. 목차의 띄어 쓴 질문과 공백만 다른 쌍
(#70 `spacing_diffs`)에서 형태소 토큰 Jaccard와 임베딩 코사인을 재서
공백 복원이 검색에 영향을 주는지 본다.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pymupdf

from cheongyak_rag.config import settings
from cheongyak_rag.ingest.faq import PDF_PATH, FaqPair, TocEntry, parse_body, parse_toc
from cheongyak_rag.ingest.faq_report import _compare
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.search import tokenize

BAND_OK = "영향 없음"
BAND_LIST = "쌍별 값을 리포트에 목록"
BAND_FIX = "공백 복원을 별도 티켓으로"


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def cosine(u: np.ndarray, v: np.ndarray) -> float:
    return float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v)))


def band(mean_jaccard: float, mean_cosine: float) -> str:
    """토큰 ≥ 0.95 이고 코사인 ≥ 0.98 이면 영향 없음, 토큰 < 0.90 이거나 코사인 < 0.95 이면 복원."""
    if mean_jaccard >= 0.95 and mean_cosine >= 0.98:
        return BAND_OK
    if mean_jaccard < 0.90 or mean_cosine < 0.95:
        return BAND_FIX
    return BAND_LIST


def spacing_pairs(toc: list[TocEntry], pairs: list[FaqPair]) -> list[tuple[int, str, str]]:
    """(q_no, 목차 질문, 본문 질문) — 공백만 다른 질문 쌍. #70 `_compare`를 그대로 쓴다."""
    _, spacing = _compare(toc, pairs)
    return [(m.q_no, m.toc, m.body) for m in spacing if m.field == "question"]


def measure(pairs: list[tuple[int, str, str]], embedder) -> dict:
    vecs = embedder.embed([t for _, toc, body in pairs for t in (toc, body)])
    rows = []
    for i, (q_no, toc, body) in enumerate(pairs):
        rows.append(
            {
                "q_no": q_no,
                "toc": toc,
                "body": body,
                "jaccard": jaccard(tokenize(toc), tokenize(body)),
                "cosine": cosine(vecs[2 * i], vecs[2 * i + 1]),
            }
        )
    mj = float(np.mean([r["jaccard"] for r in rows]))
    mc = float(np.mean([r["cosine"] for r in rows]))
    return {"pairs": rows, "mean_jaccard": mj, "mean_cosine": mc, "band": band(mj, mc)}


def write_spacing(runs_dir: Path, result: dict, embedder) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    out = {
        **result,
        "model": getattr(embedder, "model", None),
        "embedding_api_calls": embedder.api_calls,
    }
    (runs_dir / "spacing.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(runs_dir: Path | None = None, embedder=None, pdf: Path = PDF_PATH) -> int:
    from cheongyak_rag.retrieval.chunk_eval import RUNS73

    runs_dir = runs_dir or RUNS73
    embedder = embedder or Embedder(settings.openai_embed_model)
    with pymupdf.open(pdf) as doc:  # PDF는 다시 받지 않는다
        pairs = spacing_pairs(parse_toc(doc), parse_body(doc))
    result = measure(pairs, embedder)
    write_spacing(runs_dir, result, embedder)
    print(
        f"붙은 단어 {len(pairs)}쌍: 토큰 Jaccard 평균 {result['mean_jaccard']:.3f}"
        f" · 코사인 평균 {result['mean_cosine']:.3f} → {result['band']}"
    )
    print(f"OpenAI 호출 {embedder.api_calls}회 → {runs_dir / 'spacing.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
