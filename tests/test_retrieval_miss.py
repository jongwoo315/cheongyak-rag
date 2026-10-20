import json
import math
import statistics

import numpy as np
import pytest

from cheongyak_rag.retrieval import miss
from cheongyak_rag.retrieval.chunk import CANDIDATES, law_chunks
from cheongyak_rag.retrieval.corpus import Article, _body
from cheongyak_rag.retrieval.evaluate import first_sentence, run_sanity
from cheongyak_rag.retrieval.search import BM25
from tests.fakes import FakeEmbedder


def _row(label, title, rest="", paragraphs=()):
    return {
        "label": label,
        "title": title,
        "deleted": False,
        "text": f"{label}({title}) {rest}".strip(),
        "paragraphs": list(paragraphs),
    }


def _para(no, text, items=()):
    return {"no": no, "text": text, "items": list(items)}


def _item(no, text):
    return {"no": no, "text": text, "subitems": []}


ROWS = [
    _row("제1조", "목적", "이 규칙은 주택 공급 조건을 정한다."),
    _row("제2조", "정의", "용어의 뜻은 다음과 같다.", [_para("", "", [_item("1", "1. 공급이란")])]),
    _row("제3조", "자격", "청약 자격은 나이와 소득으로 정한다. 추가 요건도 있다."),
    _row(
        "제4조",
        "순위",
        "순위는 가입 기간으로 정한다.",
        [_para("①", "① 첫째", [_item("1", "1. 호")])],
    ),
    _row("제5조", "당첨", "당첨자는 추첨으로 정한다."),
    _row("제6조", "취소", "취소 사유는 다음과 같다.", [_para("①", "① 거짓 신청")]),
]
ARTICLES = [Article(r["label"], r["title"], _body(r)) for r in ROWS]
N = 4  # 6개 중 4개(제1·3·4·6조)


@pytest.fixture(scope="module")
def lines():
    return miss.sanity_by_candidate(ROWS, ARTICLES, FakeEmbedder(), n=N)


# ── Task 1 — 후보별 점검 run ────────────────────────────────────────────


def test_one_line_per_candidate_and_question(lines):
    assert len(lines) == len(CANDIDATES) * N
    assert [x["candidate"] for x in lines[:N]] == ["article"] * N
    assert {x["candidate"] for x in lines} == set(CANDIDATES)


def test_article_candidate_ranks_equal_run_sanity(lines, tmp_path):
    run_sanity(tmp_path, ARTICLES, FakeEmbedder(), n=N)
    want = [json.loads(x) for x in (tmp_path / "sanity/results.jsonl").read_text().splitlines()]
    got = [x for x in lines if x["candidate"] == "article"]
    for g, w in zip(got, want, strict=True):
        for key in ("label", "query", "bm25_rank", "bm25_top1", "dense_rank", "dense_top1"):
            assert g[key] == w[key], key


def test_own_has_query_is_true_when_question_sits_in_chunk(lines):
    for x in lines:
        if x["candidate"] == "article":
            assert x["bm25_own_has_query"] and x["dense_own_has_query"]  # 질문 = 조문 첫 문장
            assert x["query"] == first_sentence(next(a for a in ARTICLES if a.label == x["label"]))
    for x in lines:  # 후보마다 own 청크 글자 수·포함 여부가 그 청크 텍스트와 맞는다
        by_path = {c.path: c for c in law_chunks(ROWS, x["candidate"])}
        for name in ("bm25", "dense"):
            c = by_path[x[f"{name}_own_path"]]
            assert x[f"{name}_own_chars"] == len(c.text)
            assert x[f"{name}_own_has_query"] == (x["query"] in c.text)
            assert x["query_chars"] == len(x["query"])


# ── Task 2 — golden 놓친 문항 ───────────────────────────────────────────


def _base(qid, hit, rank):
    return {
        "qid": qid, "question": f"질문 {qid}", "gold": ["제1조"],
        "hit@5": hit, "gold_rank": {"제1조": rank},
    }  # fmt: skip


def _cand(qid, hit, rank):
    return {"qid": qid, "hybrid": {"hit@5": hit, "gold_rank": {"제1조": rank}}}


def _pair(spec):
    """spec: [(#131 hit, #131 순위, 후보 hit, 후보 순위)]"""
    base = [_base(f"faq-{i}", b, br) for i, (b, br, _, _) in enumerate(spec)]
    cand = [_cand(f"faq-{i}", c, cr) for i, (_, _, c, cr) in enumerate(spec)]
    return base, cand


def test_compare_golden_counts_found_and_lost_with_ranks():
    base, cand = _pair([(0, 9, 1, 2), (0, 8, 0, 7), (1, 1, 0, 6), (1, 2, 1, 1)])
    got = miss.compare_golden(base, cand)
    assert (got["found_count"], got["lost_count"]) == (1, 1)
    assert got["found"] == [
        {
            "qid": "faq-0",
            "question": "질문 faq-0",
            "gold": ["제1조"],
            "base_rank": 9,
            "cand_rank": 2,
        }
    ]
    assert [(x["qid"], x["base_rank"], x["cand_rank"]) for x in got["lost"]] == [("faq-2", 1, 6)]


@pytest.mark.parametrize(
    ("found", "lost", "band"),
    [
        (3, 0, "찾은 것이 더 많다"),
        (5, 2, "찾은 것이 더 많다"),
        (2, 0, "차이 없음"),
        (0, 2, "차이 없음"),
        (0, 3, "놓친 것이 더 많다"),
        (4, 7, "놓친 것이 더 많다"),
    ],
)
def test_golden_band_boundaries(found, lost, band):
    assert miss.golden_band(found, lost) == band


def test_compare_golden_band_comes_from_f_minus_l():
    spec = [(0, 9, 1, 1)] * 3 + [(1, 1, 1, 1)]
    assert miss.compare_golden(*_pair(spec))["band"] == "찾은 것이 더 많다"  # F−L = 3
    spec = [(1, 1, 0, 9)] * 3 + [(0, 9, 0, 9)]
    assert miss.compare_golden(*_pair(spec))["band"] == "놓친 것이 더 많다"  # F−L = −3
    spec = [(0, 9, 1, 1)] * 2 + [(1, 1, 0, 9)] * 0
    assert miss.compare_golden(*_pair(spec))["band"] == "차이 없음"  # F−L = 2


def test_compare_golden_rejects_different_questions():
    base, cand = _pair([(0, 9, 1, 1), (1, 1, 1, 1)])
    with pytest.raises(ValueError, match="qid"):
        miss.compare_golden(base, cand[::-1])


def test_golden_misses_reads_run_files(tmp_path):
    base, cand = _pair([(0, 9, 1, 1), (1, 1, 0, 5), (0, 4, 0, 4)])
    (tmp_path / "hybrid").mkdir()
    (tmp_path / "hybrid/results.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in base), encoding="utf-8"
    )
    (tmp_path / "73/article").mkdir(parents=True)
    (tmp_path / "73/article/results.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cand), encoding="utf-8"
    )
    got = miss.golden_misses(tmp_path, candidates=("article",))
    assert got["missed"] == ["faq-0", "faq-2"]
    art = got["candidates"]["article"]
    assert (art["found_count"], art["lost_count"]) == (1, 1)


# ── Task 3 — 원인 ───────────────────────────────────────────────────────


def test_bm25_terms_matches_hand_calculation():
    docs = [Article("가", "", "a b b"), Article("나", "", "c d")]
    bm = BM25(docs, tokenizer=str.split)
    got = miss.bm25_terms(bm, "a b x", "가")
    idf = math.log((2 - 1 + 0.5) / (1 + 0.5) + 1)
    norm = 1.2 * (1 - 0.75 + 0.75 * 3 / 2.5)
    assert set(got) == {"a", "b"}  # x는 어느 문서에도 없다
    assert got["a"] == pytest.approx(idf * 1 * 2.2 / (1 + norm))
    assert got["b"] == pytest.approx(idf * 2 * 2.2 / (2 + norm))
    assert list(got) == ["b", "a"]  # 기여가 큰 순서
    assert miss.bm25_terms(bm, "a", "나") == {}  # 그 문서에 없는 낱말은 기여 0


def test_bm25_term_contributions_sum_to_scores():
    bm = BM25(ARTICLES)
    for q in ("청약 자격은 나이와 소득으로 정한다.", "순위는 가입 기간 추첨", "없는낱말"):
        scores = bm.scores(q)
        for a in ARTICLES:
            total = sum(miss.bm25_terms(bm, q, a.label).values())
            assert abs(total - scores[bm.labels.index(a.label)]) < miss.SUM_TOLERANCE


def _fake_miss(name, label, top1, rank):
    """`article` 점검 줄 하나. 자기 순위·1위만 채운 합성 줄 — build_causes가 읽는 값이다."""
    q = first_sentence(next(a for a in ARTICLES if a.label == label))
    line = {"candidate": "article", "label": label, "query": q}
    for r in ("bm25", "dense", "hybrid"):
        line[f"{r}_rank"] = 1
        line[f"{r}_top1"] = label
    line[f"{name}_rank"], line[f"{name}_top1"] = rank, top1
    return line


def test_causes_cover_only_missed_retrievers_of_article_candidate():
    lines = [_fake_miss("bm25", "제3조", "제4조", 2), _fake_miss("dense", "제6조", "제1조", 4)]
    lines += [{**lines[0], "candidate": "item"}]  # article 외 후보는 원인 대상이 아니다
    got = miss.build_causes(lines, ARTICLES, ROWS, FakeEmbedder())
    assert [(c["retriever"], c["label"], c["top1"]) for c in got] == [
        ("bm25", "제3조", "제4조"),
        ("dense", "제6조", "제1조"),
    ]
    assert (
        miss.build_causes([_fake_miss("bm25", "제3조", "제3조", 1)], ARTICLES, ROWS, FakeEmbedder())
        == []
    )


def test_bm25_cause_numbers_match_scores_and_sentence_cites_them():
    bm = BM25(ARTICLES)
    (c,) = miss.build_causes(
        [_fake_miss("bm25", "제3조", "제4조", 2)], ARTICLES, ROWS, FakeEmbedder()
    )
    scores = bm.scores(c["query"])
    assert c["own_score"] == pytest.approx(scores[2]) and c["top1_score"] == pytest.approx(
        scores[3]
    )
    assert c["own_terms_gap"] < miss.SUM_TOLERANCE and c["top1_terms_gap"] < miss.SUM_TOLERANCE
    assert c["own_chars"] == len(ARTICLES[2].text) and c["top1_tokens"] == bm.lengths[3]
    assert c["median_chars"] == statistics.median(len(a.text) for a in ARTICLES)
    assert miss.cites_number(c) and f"{c['own_score']:.3f}" in c["sentence"]


def test_dense_cause_cosines_and_best_item_chunk():
    emb = FakeEmbedder()
    (c,) = miss.build_causes([_fake_miss("dense", "제4조", "제1조", 3)], ARTICLES, ROWS, emb)
    qv = emb.embed([c["query"]])[0]
    cos = lambda t: float(  # noqa: E731
        (v := emb.embed([t])[0]) @ qv / (np.linalg.norm(v) * np.linalg.norm(qv))
    )
    assert c["own_cos"] == pytest.approx(cos(ARTICLES[3].text))
    assert c["top1_cos"] == pytest.approx(cos(ARTICLES[0].text))
    own_items = [ch for ch in law_chunks(ROWS, "item") if ch.label == "제4조"]
    assert c["item_best_cos"] == pytest.approx(max(cos(ch.text) for ch in own_items))
    assert c["item_best_path"] in {ch.path for ch in own_items}
    assert miss.cites_number(c)
