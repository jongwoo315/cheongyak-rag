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
