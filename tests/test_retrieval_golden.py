import json

import pytest

from cheongyak_rag.retrieval.golden import (
    FAQ_PATH,
    build_golden,
    extract_citations,
    has_article_in_question,
)

LABELS = {"제2조", "제4조", "제23조", "제53조", "제4조의2"}


def _kinds(answer: str) -> list[tuple[str, str]]:
    return [(c.label, c.kind) for c in extract_citations(answer)]


def test_other_law_name_before_citation():
    assert _kinds("「주택법」 제2조에 의하면 주택이란 건축물을 말한다.") == [("제2조", "other")]


def test_rule_name_before_citation():
    got = _kinds("「주택공급에 관한 규칙」 제23조 제4항에 따르면 기준일이 정해진다.")
    assert got == [("제23조", "rule")]


def test_name_binds_to_following_articles_in_list():
    # 「주택법」 하나가 뒤따르는 `제N조 및 제M조`에 다 걸린다
    assert _kinds("「주택법」 제2조 및 제4조에 따른다.") == [("제2조", "other"), ("제4조", "other")]


def test_closest_name_wins_within_sentence():
    got = _kinds("「주택법」에 따른 경우 「주택공급에 관한 규칙」 제53조를 적용한다.")
    assert got == [("제53조", "rule")]


def test_no_name_is_none():
    assert _kinds("제53조에 따라 청약할 수 있습니다.") == [("제53조", "none")]


def test_name_in_previous_sentence_does_not_count():
    assert _kinds("「주택법」을 따른다. 제4조에 따라 정한다.") == [("제4조", "none")]


@pytest.mark.parametrize(
    ("before", "kind"),
    [
        ("공급규칙", "rule"),
        ("주택공급규칙", "rule"),
        ("동 규칙", "rule"),
        ("이 규칙", "rule"),
        ("같은 규칙", "rule"),
        ("「주택공급에관한 규칙」", "rule"),
        ("｢주택공급규칙｣", "rule"),
        ("「주택공급에 관한 규칙(시행 2018.5.4, 국토교통부령 제512호)」", "rule"),
        ("동법", "other"),
        ("주택법 시행령", "other"),
        ("「주택법 시행규칙」", "other"),
        ("소득세법", "other"),
        ("법", "other"),
        ("영", "other"),
        ("「공동주택 분양가격의 산정 등에 관한 규칙」", "other"),
    ],
)
def test_name_forms(before, kind):
    assert _kinds(f"사업주체는 {before} 제4조를 본다.") == [("제4조", kind)]


def test_citation_split_across_line_break():
    assert _kinds("「주택법」 제2\n조에 따라 정한다.") == [("제2조", "other")]


def test_name_split_across_line_break():
    assert _kinds("「주택공급에\n관한 규칙」 제4조에 따른다.") == [("제4조", "rule")]


def test_branch_article_label_and_paragraph_stripped():
    assert _kinds("「주택공급에 관한 규칙」 제4조의2제1항제3호에 따른다.") == [("제4조의2", "rule")]


def test_list_item_starts_new_sentence():
    ans = "다음과 같다.\n     1. 「건축법 시행령」 별표 1\n     2. 제4조에 따른다"
    assert _kinds(ans) == [("제4조", "none")]


def test_unbracketed_rule_name_with_ministerial_order_note():
    # `국토교통부령 제512호`는 법령 이름이 아니라 시행 정보다
    ans = "주택공급에관한규칙[시행 2003.2.28., 건설교통부령 제353호) 제5조에 따른다."
    assert _kinds(ans) == [("제5조", "rule")]


def test_has_article_in_question():
    assert has_article_in_question("제23조에 따르면 어떻게 되나요?")
    assert not has_article_in_question("무주택기간은 어떻게 산정하나요?")


def _faq(q_no: int, answer: str, question: str = "질문?") -> dict:
    return {"q_no": q_no, "question": question, "answer": answer}


def test_build_golden_keeps_rule_and_none_drops_other():
    rows = [
        _faq(1, "「주택법」 제2조와 「주택공급에 관한 규칙」 제23조를 본다."),
        _faq(2, "제53조에 따른다."),
    ]
    res = build_golden(rows, LABELS)
    assert [(g["qid"], g["gold"]) for g in res.rows] == [
        ("faq-1", ["제23조"]),
        ("faq-2", ["제53조"]),
    ]


def test_question_with_only_other_law_is_dropped_with_reason():
    res = build_golden([_faq(66, "「주택법」 제2조에 의하면 정의한다.")], LABELS)
    assert res.rows == [] and res.dropped == {"다른 법령 인용뿐": 1}


def test_question_citing_article_absent_from_current_is_dropped():
    res = build_golden([_faq(7, "「주택공급에 관한 규칙」 제99조에 따른다.")], LABELS)
    assert res.rows == [] and res.dropped == {"현행에 없는 조를 인용": 1}


def test_question_without_citation_is_not_a_candidate():
    res = build_golden([_faq(9, "인용 없는 답변이다.")], LABELS)
    assert res.rows == [] and res.dropped == {}


def test_citation_counts_and_none_samples():
    rows = [
        _faq(1, "「주택법」 제2조를 본다. 제4조에 따른다. 「주택공급에 관한 규칙」 제53조를 본다.")
    ]
    res = build_golden(rows, LABELS)
    assert res.counts == {"rule": 1, "other": 1, "none": 1}
    assert res.none_samples[0].startswith("q1: ") and "제4조" in res.none_samples[0]


def test_row_has_question_flag():
    res = build_golden([_faq(3, "제4조에 따른다.", question="제4조란?")], LABELS)
    assert res.rows[0]["has_article_in_question"] is True
    assert set(res.rows[0]) == {"qid", "q_no", "question", "gold", "has_article_in_question"}


def test_real_faq_66_is_other_law_and_53_is_rule():
    if not FAQ_PATH.exists():
        pytest.fail(f"FAQ JSONL 없음: {FAQ_PATH}")
    faq = {r["q_no"]: r for r in map(json.loads, FAQ_PATH.read_text(encoding="utf-8").splitlines())}
    assert ("제2조", "other") in _kinds(faq[66]["answer"])
    assert _kinds(faq[53]["answer"]) == [("제23조", "rule")]
    res = build_golden([faq[53]], LABELS)
    assert res.rows[0]["gold"] == ["제23조"]
