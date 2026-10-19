import json

import numpy as np
import pytest

from cheongyak_rag.ingest.faq import FaqPair, TocEntry
from cheongyak_rag.retrieval import chunk_spacing as sp


class FakeEmbedder:
    model = "fake"
    api_calls = 0

    def __init__(self, vecs=None):
        self.vecs = vecs or {}
        self.cache = {}

    def embed(self, texts):
        for t in texts:
            self.cache.setdefault(t, self.vecs.get(t, [1.0, 0.0, float(len(t) % 7 + 1)]))
        return np.array([self.cache[t] for t in texts], dtype=np.float64)


def test_jaccard_same_sentence_is_one():
    assert sp.jaccard(["주택", "소유"], ["소유", "주택"]) == 1.0
    assert sp.jaccard([], []) == 1.0


def test_jaccard_hand_computed():
    assert sp.jaccard(["a", "b", "c"], ["b", "c", "d"]) == pytest.approx(2 / 4)


def test_cosine_same_vector_is_one_and_orthogonal_is_zero():
    assert sp.cosine(np.array([1.0, 2.0]), np.array([2.0, 4.0])) == pytest.approx(1.0)
    assert sp.cosine(np.array([1.0, 0.0]), np.array([0.0, 3.0])) == pytest.approx(0.0)


def test_measure_same_text_gives_one_one():
    out = sp.measure(
        [(1, "주택을 소유한 것으로 본다", "주택을 소유한 것으로 본다")], FakeEmbedder()
    )
    assert out["pairs"][0]["jaccard"] == 1.0
    assert out["pairs"][0]["cosine"] == pytest.approx(1.0)
    assert out["mean_jaccard"] == 1.0
    assert out["band"] == "영향 없음"


@pytest.mark.parametrize(
    ("jac", "cos", "band"),
    [
        (0.95, 0.98, "영향 없음"),
        (0.99, 0.97, "쌍별 값을 리포트에 목록"),
        (0.92, 0.99, "쌍별 값을 리포트에 목록"),
        (0.89, 0.99, "공백 복원을 별도 티켓으로"),
        (0.99, 0.94, "공백 복원을 별도 티켓으로"),
    ],
)
def test_band_thresholds(jac, cos, band):
    assert sp.band(jac, cos) == band


def test_measure_means_and_spacing_difference_lowers_jaccard():
    toc, body = "무주택 세대 구성원", "무주택세대구성원"
    out = sp.measure([(7, toc, body)], FakeEmbedder())
    p = out["pairs"][0]
    assert p["q_no"] == 7 and (p["toc"], p["body"]) == (toc, body)
    assert 0 <= p["jaccard"] <= 1
    assert out["mean_cosine"] == pytest.approx(p["cosine"])


def test_spacing_pairs_takes_only_spacing_only_differences():
    toc = [
        TocEntry(1, "Ⅰ. 가", "", "", "소유한 것으로 본다"),
        TocEntry(2, "Ⅰ. 가", "", "", "완전히 다른 질문"),
        TocEntry(3, "Ⅰ. 가", "", "", "똑같은 질문"),
    ]
    pairs = [
        FaqPair(1, "Ⅰ. 가", "", "", "소유한것으로 본다", "a", 1, "d", []),
        FaqPair(2, "Ⅰ. 가", "", "", "전혀 다른 문장", "a", 1, "d", []),
        FaqPair(3, "Ⅰ. 가", "", "", "똑같은 질문", "a", 1, "d", []),
    ]
    assert sp.spacing_pairs(toc, pairs) == [(1, "소유한 것으로 본다", "소유한것으로 본다")]


def test_spacing_pairs_real_data_is_32(toc, pairs):
    got = sp.spacing_pairs(toc, pairs)
    assert len(got) == 32
    assert all(" ".join(t.split()) != " ".join(b.split()) for _, t, b in got)


def test_write_spacing_json(tmp_path):
    out = sp.measure([(1, "가 나", "가나")], FakeEmbedder())
    sp.write_spacing(tmp_path, out, FakeEmbedder())
    data = json.loads((tmp_path / "spacing.json").read_text())
    assert data["pairs"][0]["q_no"] == 1
    assert {"mean_jaccard", "mean_cosine", "band", "model"} <= set(data)
