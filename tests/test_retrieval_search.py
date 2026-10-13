import math

import numpy as np
import pytest

from cheongyak_rag.retrieval.corpus import Article
from cheongyak_rag.retrieval.search import BM25, dense_rank, rrf, tokenize


def test_josa_attached_forms_become_same_token():
    assert tokenize("주택을 취득")[0] == tokenize("주택은 소유")[0] == "주택"


def test_tokenize_keeps_digits_and_drops_josa_and_nnb():
    toks = tokenize("제23조 제4항에 따르면 청약통장 1순위")
    assert "23" in toks and "4" in toks and "1" in toks
    assert "에" not in toks and "조" not in toks  # 조사·NNB는 뺀다
    assert "청약" in toks and "통장" in toks


def test_tokenize_keeps_foreign_word():
    assert "SNS" in tokenize("SNS 계정")


WS = str.split  # 손계산용 공백 토크나이저
DOCS = [
    Article("A", "a", "x x y"),  # 길이 3
    Article("B", "b", "x z"),  # 길이 2
    Article("C", "c", "z z z z"),  # 길이 4, 평균 길이 3
]


def _idf(n: int, df: int) -> float:
    return math.log((n - df + 0.5) / (df + 0.5) + 1)


def test_bm25_matches_hand_calculation():
    bm = BM25(DOCS, tokenizer=WS, k1=1.2, b=0.75)
    # 질의 `x`: df=2, N=3. 문서 A는 tf=2 길이 3(평균과 같음), B는 tf=1 길이 2
    idf = _idf(3, 2)
    a = idf * 2 * 2.2 / (2 + 1.2 * (1 - 0.75 + 0.75 * 3 / 3))
    b = idf * 1 * 2.2 / (1 + 1.2 * (1 - 0.75 + 0.75 * 2 / 3))
    got = bm.scores("x")
    assert got[0] == pytest.approx(a)
    assert got[1] == pytest.approx(b)
    assert got[2] == 0.0


def test_bm25_rank_covers_all_docs_and_breaks_ties_by_order():
    bm = BM25(DOCS, tokenizer=WS)
    assert bm.rank("x") == ["A", "B", "C"]
    assert bm.rank("없는말") == ["A", "B", "C"]  # 점수가 전부 0이면 문서 순서


def test_bm25_unknown_and_repeated_query_terms():
    bm = BM25(DOCS, tokenizer=WS)
    assert bm.rank("z")[0] == "C"  # tf 4 > tf 1
    # 질의에 같은 낱말이 두 번 나와도 점수가 두 배가 되지 않는다(집합으로 센다)
    assert bm.scores("x x") == bm.scores("x")


def test_dense_rank_orders_by_cosine():
    docs = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    assert dense_rank(np.array([0.0, 1.0]), docs, ["a", "b", "c"]) == ["b", "c", "a"]


def test_dense_rank_is_scale_invariant():
    docs = np.array([[2.0, 0.0], [0.0, 0.5]])
    assert dense_rank(np.array([10.0, 1.0]), docs, ["a", "b"]) == ["a", "b"]


def test_rrf_hand_calculation():
    out = dict(rrf([["a", "b", "c"], ["b", "a", "c"]], k=60))
    assert out["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert out["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out["c"] == pytest.approx(2 / 63)


def test_rrf_sorted_desc_and_tie_follows_first_ranking():
    got = rrf([["a", "b", "c"], ["b", "a", "c"]])
    assert [label for label, _ in got] == ["a", "b", "c"]  # a·b 동점 → 첫 순위 순서
    assert got[0][1] >= got[1][1] >= got[2][1]
