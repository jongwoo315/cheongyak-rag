"""검색 세 가지의 순위 계산 — BM25 · dense(코사인) · RRF (#131).

문서가 88개라 DB 없이 메모리에서 전수 계산한다. 순위는 전부 88개 전체를 돌려준다.
"""

import math
from collections import Counter
from collections.abc import Callable, Sequence
from functools import cache
from typing import Protocol

import numpy as np
from kiwipiepy import Kiwi

# 체언(NNG·NNP, NNB 제외) · 용언 어간 · 어근 · 외국어 · 한자 · 숫자
KEEP_TAGS = {"NNG", "NNP", "VV", "VA", "XR", "SL", "SH", "SN"}


@cache
def _kiwi() -> Kiwi:
    return Kiwi()


def tokenize(text: str) -> list[str]:
    # Kiwi는 `VV-R` `VA-I` 같은 변이 태그도 낸다. `-` 앞 기본 태그로 본다
    return [t.form for t in _kiwi().tokenize(text) if t.tag.split("-")[0] in KEEP_TAGS]


class HasText(Protocol):
    label: str
    text: str


class BM25:
    """Okapi BM25. idf = ln((N - df + 0.5) / (df + 0.5) + 1), 질의 낱말은 집합으로 센다."""

    def __init__(
        self,
        docs: Sequence[HasText],
        tokenizer: Callable[[str], list[str]] = tokenize,
        k1: float = 1.2,
        b: float = 0.75,
    ):
        self.labels = [d.label for d in docs]
        self.tokenizer, self.k1, self.b = tokenizer, k1, b
        self.tf = [Counter(tokenizer(d.text)) for d in docs]
        self.lengths = [sum(c.values()) for c in self.tf]
        self.avg_len = sum(self.lengths) / len(docs)
        df = Counter(term for c in self.tf for term in c)
        n = len(docs)
        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1) for t, d in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(self.tokenizer(query)) & self.idf.keys()
        out = []
        for tf, length in zip(self.tf, self.lengths, strict=True):
            norm = self.k1 * (1 - self.b + self.b * length / self.avg_len)
            out.append(
                sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in terms if t in tf)
            )
        return out

    def rank(self, query: str) -> list[str]:
        """점수 내림차순. 동점은 문서 순서."""
        scores = self.scores(query)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [self.labels[i] for i in order]


def dense_rank(query_vec: np.ndarray, doc_vecs: np.ndarray, labels: Sequence[str]) -> list[str]:
    """코사인 유사도 내림차순. 동점은 문서 순서."""
    sims = (doc_vecs @ query_vec) / (np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(query_vec))
    return [labels[i] for i in np.argsort(-sims, kind="stable")]


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. 점수 = Σ 1/(k + 순위). 동점은 첫 순위에 먼저 나온 쪽."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, label in enumerate(ranking, start=1):
            scores[label] = scores.get(label, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])  # sorted는 안정 정렬 → 삽입 순서 유지
