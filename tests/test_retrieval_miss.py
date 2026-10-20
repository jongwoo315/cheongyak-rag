import json

import pytest

from cheongyak_rag.retrieval import miss
from cheongyak_rag.retrieval.chunk import CANDIDATES, law_chunks
from cheongyak_rag.retrieval.corpus import Article, _body
from cheongyak_rag.retrieval.evaluate import first_sentence, run_sanity
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
