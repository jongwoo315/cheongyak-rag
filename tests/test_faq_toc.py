def test_480_entries_contiguous(toc):
    assert [e.q_no for e in toc] == list(range(1, 481))


def test_q1(toc):
    e = toc[0]
    assert (e.major, e.middle, e.minor) == (
        "Ⅰ. 청약자격(공통)",
        "1. 청약신청지역",
        "나. 청약신청지역 및 우선공급",
    )
    assert e.question == "경기도 과천시에서 공급되는 주택의 해당 주택건설지역의 범위는?"


def test_q3_two_line_question_joined(toc):
    e = toc[2]
    assert e.question == (
        "해당 지역에 거주하고 있으나, 우선공급을 위한 거주기간을 충족하지 못하는 경우 "
        "청약신청 지역은?"
    )
    assert e.minor == "나. 청약신청지역 및 우선공급"


def test_q480_section_without_middle(toc):
    e = toc[479]
    assert (e.major, e.middle, e.minor) == ("Ⅶ. 거주의무", "", "")
    assert e.question == "거주의무자의 배우자나 직계 존‧비속 등이 의무를 대신 이행할 수 있나요?"


def test_major_without_dot_is_normalized(toc):
    # 목차에 `Ⅳ`처럼 점 없이 인쇄된 대분류도 `Ⅳ. 소득산정` 꼴로 맞춘다
    majors = {e.major for e in toc}
    assert majors == {
        "Ⅰ. 청약자격(공통)",
        "Ⅱ. 일반공급",
        "Ⅲ. 특별공급 및 우선공급",
        "Ⅳ. 소득산정",
        "Ⅴ. 주택공급절차",
        "Ⅵ. 전매제한",
        "Ⅶ. 거주의무",
    }


def test_no_leader_dots_left(toc):
    assert all("···" not in e.question for e in toc)


def test_reference_items_do_not_leak_into_question(toc):
    # 목차의 `∙ 참고 …` 항목(Q221·Q325 등 뒤)은 질문이 아니다
    assert all("참고" not in e.question for e in toc)
