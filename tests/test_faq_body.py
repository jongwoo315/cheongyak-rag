import pytest

from cheongyak_rag.ingest.faq import cite_articles


def test_480_pairs_contiguous(pairs):
    assert [p.q_no for p in pairs] == list(range(1, 481))


def test_q1(pairs):
    p = pairs[0]
    assert (p.major, p.middle, p.minor) == (
        "Ⅰ. 청약자격(공통)",
        "1. 청약신청지역",
        "나. 청약신청지역 및 우선공급",
    )
    assert p.question == "경기도 과천시에서 공급되는 주택의 해당 주택건설지역의 범위는?"
    assert p.answer.startswith(
        "해당 주택건설지역이란 특별시ㆍ광역시ㆍ특별자치시ㆍ특별자치도(관할 구역 안에 지방"
    )
    assert p.answer.endswith("전역이 해당 주택건설지역에 해당됩니다.")
    assert (p.page_start, p.as_of, p.cited_articles) == (39, "2024-05-29", [])


def test_q3_two_line_question(pairs):
    p = pairs[2]
    assert p.question == (
        "해당 지역에 거주하고 있으나, 우선공급을 위한 거주기간을 충족하지 못하는 경우 "
        "청약신청 지역은?"
    )
    assert p.answer.startswith("입주자모집공고일 현재 해당지역에 거주하고 있으나")
    assert p.answer.endswith("유의하여 주시기 바랍니다.")


def test_q6_cites_article(pairs):
    assert "제34조" in pairs[5].cited_articles


@pytest.mark.parametrize(
    ("q_no", "major", "middle", "minor", "question_head"),
    [
        (149, "Ⅱ. 일반공급", "1. 공통사항", "", "외국인이 투기과열지구"),
        (180, "Ⅲ. 특별공급 및 우선공급", "1. 공통사항", "", "국가유공자 및 장애인 기관추천"),
        (282, "Ⅳ. 소득산정", "1. 공공주택", "", "공공주택의 소득기준 확인 방법은?"),
        (
            360,
            "Ⅴ. 주택공급절차",
            "1. 「주택공급에 관한 규칙」 적용대상 주택",
            "",
            "｢주택법｣ 제54조제1항에 따라",
        ),
        (426, "Ⅵ. 전매제한", "", "", "주택의 전매제한이 무엇인가요?"),
        (463, "Ⅶ. 거주의무", "", "", "거주의무자가 근무 등의 사유로"),
        (480, "Ⅶ. 거주의무", "", "", "거주의무자의 배우자나 직계 존‧비속 등이"),
    ],
)
def test_first_question_of_each_major(pairs, q_no, major, middle, minor, question_head):
    p = pairs[q_no - 1]
    assert p.q_no == q_no
    assert (p.major, p.middle, p.minor) == (major, middle, minor)
    assert p.question.startswith(question_head)
    assert p.answer


def test_no_page_header_or_number_lines_in_answer(pairs):
    majors = {p.major for p in pairs}
    for p in pairs:
        lines = p.answer.splitlines()
        assert not majors & set(lines), p.q_no
        assert p.answer.count("\n") == len(lines) - 1


def test_cite_articles_dedupes_and_keeps_order():
    # 줄바꿈으로 갈라진 `제25조\n제3항제2호`는 앞에서 나온 `제25조제3항제2호`와 같은 인용이다
    text = "제4조제1항, 제25조제3항제2호 및 제4조제1항, 제53조의2 그리고 제25조\n제3항제2호"
    assert cite_articles(text) == ["제4조제1항", "제25조제3항제2호", "제53조의2"]


def test_mid_word_line_break_gets_no_space(pairs):
    # 본문에서 `청년` / `주택드림청약통장에`로 단어 중간에서 접힌다
    assert "청년주택드림청약통장에" in pairs[25].question


def test_every_question_and_answer_is_non_empty(pairs):
    assert [p.q_no for p in pairs if not p.question.strip() or not p.answer.strip()] == []


def test_sections_match_toc_and_answers_do_not_leak(toc, pairs):
    # jw 기준(섹션에 맞게 분리)과 실패 징후 3을 실제 PDF로 지킨다. 값이 아니라 0이어야 통과다
    from cheongyak_rag.ingest.faq import BodyStats
    from cheongyak_rag.ingest.faq_report import build_report

    r = build_report(toc, pairs, BodyStats(), warnings=0)
    assert len(toc) == len(pairs) == 480
    assert r.mismatches == []
    assert r.leaks == []
