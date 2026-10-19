import json

import pytest

from cheongyak_rag.retrieval import chunk as ck
from cheongyak_rag.retrieval.corpus import LAW_PATH, load_articles


def _row(label, title, rest="", paragraphs=(), deleted=False):
    head = f"{label}({title})"
    return {
        "label": label,
        "title": title,
        "deleted": deleted,
        "text": f"{head} {rest}".strip(),
        "paragraphs": list(paragraphs),
    }


def _para(no, text, items=()):
    return {"no": no, "text": text, "items": list(items)}


def _item(no, text, subs=()):
    return {"no": no, "text": text, "subitems": [{"no": n, "text": t} for n, t in subs]}


@pytest.fixture
def rows():
    return [
        _row("제1조", "목적", "이 규칙은 목적이다. <개정 2016.8.12>"),
        _row(
            "제2조",
            "정의",
            "다음과 같다.",
            [
                _para(
                    "",
                    "",
                    [
                        _item("1", "1. 공급이란"),
                        _item("2의2", "2의2. 세대란", [("가", "가. 본인")]),
                    ],
                )
            ],
        ),
        _row(
            "제3조",
            "적용",
            "",
            [
                _para(
                    "①",
                    "① 첫째 항",
                    [_item("1", "1. 호", [("가", "가. 목"), ("나", "나. 목둘")])],
                ),
                _para("②", "② 둘째 항"),
            ],
        ),
        _row("제4조", "삭제", "삭제", deleted=True),
    ]


@pytest.fixture(scope="module")
def real_rows():
    return [json.loads(x) for x in LAW_PATH.read_text(encoding="utf-8").splitlines() if x]


def _by_path(chunks):
    return {c.path: c for c in chunks}


def test_candidates_are_the_five_fixed_by_design():
    assert ck.CANDIDATES == ("article", "paragraph", "paragraph+head", "item", "item+head")


def test_article_candidate_one_chunk_per_article_and_deleted_dropped(rows):
    chunks = ck.law_chunks(rows, "article")
    assert [c.path for c in chunks] == ["제1조", "제2조", "제3조"]
    assert all(c.source == "law" for c in chunks)
    assert chunks[0].text == "제1조(목적)\n이 규칙은 목적이다."  # 개정 이력은 뗀다


def test_paragraph_candidate_splits_by_paragraph_with_items_and_subitems(rows):
    got = _by_path(ck.law_chunks(rows, "paragraph"))
    assert list(got) == ["제1조", "제2조", "제3조제1항", "제3조제2항"]
    assert got["제3조제1항"].text == "① 첫째 항\n1. 호\n가. 목\n나. 목둘"
    assert got["제3조제1항"].label == "제3조"


def test_paragraph_candidate_article_without_paragraph_is_one_chunk(rows):
    got = ck.law_chunks(rows, "paragraph")
    assert [c.path for c in got].count("제1조") == 1
    assert _by_path(got)["제1조"].text == "이 규칙은 목적이다."


def test_paragraph_candidate_unnamed_wrapper_keeps_intro_and_items_together(rows):
    assert _by_path(ck.law_chunks(rows, "paragraph"))["제2조"].text == (
        "다음과 같다.\n1. 공급이란\n2의2. 세대란\n가. 본인"
    )


def test_item_candidate_one_line_each_with_paths(rows):
    got = _by_path(ck.law_chunks(rows, "item"))
    assert list(got) == [
        "제1조",
        "제2조",
        "제2조제1호",
        "제2조제2호의2",
        "제2조제2호의2가목",
        "제3조제1항",
        "제3조제1항제1호",
        "제3조제1항제1호가목",
        "제3조제1항제1호나목",
        "제3조제2항",
    ]
    assert got["제2조제2호의2가목"].text == "가. 본인"


def test_head_variants_prefix_every_chunk(rows):
    for cand in ("paragraph+head", "item+head"):
        chunks = ck.law_chunks(rows, cand)
        for c in chunks:
            title = {"제1조": "목적", "제2조": "정의", "제3조": "적용"}[c.label]
            assert c.text.startswith(f"{c.label}({title})\n"), (cand, c.path)


def test_head_variant_has_same_paths_as_plain(rows):
    assert [c.path for c in ck.law_chunks(rows, "item+head")] == [
        c.path for c in ck.law_chunks(rows, "item")
    ]


def test_chunk_ids_unique(rows):
    for cand in ck.CANDIDATES:
        ids = [c.chunk_id for c in ck.law_chunks(rows, cand)]
        assert len(ids) == len(set(ids))


def test_unknown_candidate_raises(rows):
    with pytest.raises(ValueError):
        ck.law_chunks(rows, "sentence")


# ── 실제 데이터 ─────────────────────────────────────────────────────────


def test_article_candidate_text_equals_corpus_load_articles(real_rows):
    chunks = ck.law_chunks(real_rows, "article")
    arts = load_articles()
    assert [(c.label, c.text) for c in chunks] == [(a.label, a.text) for a in arts]


def test_item_candidate_has_article_2_item_4_with_definition(real_rows):
    got = _by_path(ck.law_chunks(real_rows, "item"))
    assert "무주택세대구성원" in got["제2조제4호"].text


def test_head_variants_start_with_head_on_real_data(real_rows):
    titles = {a.label: a.title for a in load_articles()}
    for cand in ("paragraph+head", "item+head"):
        for c in ck.law_chunks(real_rows, cand):
            assert c.text.startswith(f"{c.label}({titles[c.label]})\n")


@pytest.mark.parametrize("cand", ck.CANDIDATES)
def test_preservation_on_real_data(real_rows, cand):
    """실패 징후 3 — 머리를 뗀 청크를 이으면 조 본문 줄과 같다."""
    assert ck.check_preservation(real_rows, cand) == []


@pytest.mark.parametrize("cand", ck.CANDIDATES)
def test_real_chunk_ids_unique(real_rows, cand):
    ids = [c.chunk_id for c in ck.law_chunks(real_rows, cand)]
    assert len(ids) == len(set(ids))


def test_check_preservation_reports_missing_and_duplicate(rows, monkeypatch):
    real = ck.law_chunks

    def lossy(r, cand):
        out = real(r, cand)
        return out[:-1] + out[-2:-1]  # 마지막을 빼고 그 앞 청크를 중복

    monkeypatch.setattr(ck, "law_chunks", lossy)
    assert ck.check_preservation(rows, "item")


def test_short_chunk_ratio():
    mk = lambda t: ck.Chunk("i", "제1조", "제1조", t, "law", {})  # noqa: E731
    assert ck.short_ratio([mk("가" * 9), mk("가" * 10), mk("나" * 50), mk("다" * 100)]) == 0.25


# ── FAQ ─────────────────────────────────────────────────────────────────


def _faq(q_no, question, answer, cites=()):
    return {
        "q_no": q_no,
        "major": "Ⅰ. 청약자격",
        "middle": "1. 가",
        "minor": "나",
        "question": question,
        "answer": answer + "".join(f" 규칙 제{c}조" for c in cites),
    }


def test_faq_chunk_is_question_newline_answer_with_meta():
    faq = [_faq(1, "질문?", "답이다.", cites=[2]), _faq(2, "다른 질문?", "답 둘")]
    got = ck.faq_chunks(faq, {"제2조", "제3조"})
    assert [c.text for c in got] == ["질문?\n답이다. 규칙 제2조", "다른 질문?\n답 둘"]
    assert got[0].source == "faq"
    assert got[0].meta == {
        "q_no": 1,
        "major": "Ⅰ. 청약자격",
        "middle": "1. 가",
        "minor": "나",
        "cited": ["제2조"],
    }
    assert got[1].meta["cited"] == []


def test_faq_cited_drops_other_law_and_unknown_labels():
    faq = [_faq(1, "q", "「주택법」 제54조에 따라 규칙 제3조 그리고 규칙 제99조")]
    got = ck.faq_chunks(faq, {"제3조", "제54조"})
    assert got[0].meta["cited"] == ["제3조"]


def test_faq_chunk_ids_unique_and_path_is_q_no():
    faq = [_faq(1, "q", "a"), _faq(2, "q", "a")]
    got = ck.faq_chunks(faq, set())
    assert len({c.chunk_id for c in got}) == 2
    assert got[0].path == "Q1"
