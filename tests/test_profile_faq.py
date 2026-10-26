"""국토부 FAQ(2024-05-29) 사례를 계산이 그대로 재현하는지 본다 (#77 통과 기준 3).

기대값은 `data/processed/faq-20240529.jsonl` 답 문장의 숫자에서만 왔다.
이 파일은 구현보다 먼저 커밋한다 — 기대값이 구현을 보고 정해지지 않았다는 증거다.
"""

import dataclasses
from datetime import date

import pytest

from cheongyak_rag import profile

AS_OF = date(2026, 10, 23)


def _dependents(**fields):
    """②만 읽는다. 배우자·자녀·직계존속 입력을 전부 채워 ②가 한 점으로 정해지게 한다."""
    base = dict(
        married=False,
        children_unmarried=0,
        children_30plus_1y=0,
        ascendants_3y=0,
    )
    return profile.score(profile.Profile(**{**base, **fields}), AS_OF).dependents


def test_faq46_minor_period_credited_four_years():
    """FAQ 46: 2024-01-01 전 미성년 가입 5년 + 이후 2년 → 미성년 기간 인정 4년.

    성년이 2026-01-01인 사람(2007-01-01생)이 2019-01-01에 가입했다.
    2023-12-31 이전 5년은 2년까지만, 2024-01-01~2025-12-31의 2년은 그대로 쳐서 4년이다.
    """
    start = profile.savings_start(date(2019, 1, 1), date(2007, 1, 1))
    assert str(profile.period(start, date(2025, 12, 31))) == "4년0월0일"


def test_faq46_cap_enters_the_savings_score():
    """FAQ 46: 위 사례의 공고일(2026-01-01) 통장 가입기간은 4년이라 ③ 6점(4년 이상~5년 미만)이다."""
    p = profile.Profile(
        birth_date=date(2007, 1, 1),
        married=False,
        savings_join_date=date(2019, 1, 1),
    )
    s = profile.score(p, date(2026, 1, 1)).savings
    assert (s.lo, s.hi) == (6, 6)


def test_faq46_total_minor_period_capped_at_five_years():
    """제10조⑥(FAQ 46의 근거): 미성년 기간이 2023-12-31 이전 2년 + 이후 4년이면 5년만 인정."""
    # 성년이 2028-01-01인 사람이 2018-01-01 가입, 공고일 2027-12-31
    start = profile.savings_start(date(2018, 1, 1), date(2009, 1, 1))
    assert str(profile.period(start, date(2027, 12, 31))) == "5년0월0일"


def test_faq151_naturalized_age_35_applies_at_40():
    """FAQ 151: 35세 귀화, 40세 청약, 무주택 → 무주택기간 만 30세부터 10년 → ① 22점.

    1986-05-01생, 공고일 2026-05-01. 만 30세 되는 날(2016-05-01)부터 센다.
    """
    p = profile.Profile(
        birth_date=date(1986, 5, 1),
        married=False,
        ever_married=False,  # 미혼 — 혼인한 적이 없다
        homeless_now=True,
        ever_owned=False,
    )
    r = profile.score(p, date(2026, 5, 1))
    assert r.values["homeless_start"].value == date(2016, 5, 1)
    assert r.values["homeless_period"].value.years == 10
    assert (r.homeless.lo, r.homeless.hi) == (22, 22)


@pytest.mark.parametrize(
    ("married_before_30", "owned", "expected"),
    [
        (False, False, date(2010, 3, 1)),  # 청약신청자가 만 30세가 된 날
        (True, False, date(2008, 6, 1)),  # 혼인신고일
        (False, True, date(2014, 9, 1)),  # 만 30세가 된 날과 무주택자가 된 날 중 늦은 날
        (True, True, date(2014, 9, 1)),  # 혼인신고일과 무주택자가 된 날 중 늦은 날
    ],
)
def test_faq153_start_date_four_cells(married_before_30, owned, expected):
    """FAQ 153: 소유 이력 없음 → 30세 된 날(30세 전 혼인이면 혼인신고일).

    소유 이력 있음 → 그 날과 무주택자가 된 날 중 늦은 날.

    1980-03-01생(만 30세 2010-03-01), 혼인신고일 2008-06-01, 무주택자가 된 날 2014-09-01.
    """
    start = profile.homeless_start(
        birth_date=date(1980, 3, 1),
        marriage_date=date(2008, 6, 1) if married_before_30 else None,
        ever_owned=owned,
        homeless_since=date(2014, 9, 1) if owned else None,
    )
    assert start == expected


def test_faq153_owned_before_start_does_not_move_it_earlier():
    """FAQ 153: 무주택자가 된 날이 30세 된 날보다 빠르면 30세 된 날부터다 (늦은 날)."""
    start = profile.homeless_start(date(1980, 3, 1), None, True, date(2005, 1, 1))
    assert start == date(2010, 3, 1)


def test_faq154_owning_a_house_gives_zero():
    """FAQ 154: 세대 내 1주택 소유 → 무주택기간 점수 0. 다른 입력이 비어 있어도 0이다."""
    r = profile.score(profile.Profile(homeless_now=False), AS_OF)
    assert (r.homeless.lo, r.homeless.hi) == (0, 0)


def test_faq156_divorce_remarriage_counts_from_latest_homeless_day():
    """FAQ 156: 이혼·재혼 → 가장 최근에 무주택자가 된 날부터. 없으면 최초 혼인신고일부터.

    1990-01-01생, 최초 혼인신고일 2012-03-01(만 22세). 소유 이력이 없으면 2012-03-01,
    이혼·재혼 뒤 2018-06-01에 가장 최근 무주택자가 됐다고 입력하면 2018-06-01이다.
    """
    base = dict(
        birth_date=date(1990, 1, 1),
        married=True,
        marriage_date=date(2012, 3, 1),
        homeless_now=True,
    )
    clean = profile.score(profile.Profile(**base, ever_owned=False), AS_OF)
    assert clean.values["homeless_start"].value == date(2012, 3, 1)
    remarried = profile.score(
        profile.Profile(**base, ever_owned=True, homeless_since=date(2018, 6, 1)), AS_OF
    )
    assert remarried.values["homeless_start"].value == date(2018, 6, 1)


def test_faq157_applicant_is_not_a_dependent():
    """FAQ 157: 본인은 부양가족에 안 들어간다 → 세대원이 없으면 0명, ② 5점."""
    s = _dependents()
    assert (s.lo, s.hi) == (5, 5)


def test_faq158_spouse_counts_one():
    """FAQ 158: 배우자는 같은 주민등록표에 없어도 부양가족 → 배우자 있음이면 1명, ② 10점."""
    s = _dependents(married=True)
    assert (s.lo, s.hi) == (10, 10)


def test_faq159_only_unmarried_children_are_inputs():
    """FAQ 159: 혼인했거나 이혼한 자녀는 부양가족이 아니다. 미혼 2 + 30세 이상 미혼 1 = 3명, ② 20점.

    입력 필드에 혼인한 자녀를 받는 칸이 없다.
    """
    names = {f.name for f in dataclasses.fields(profile.Profile)}
    assert {"children_unmarried", "children_30plus_1y"} <= names
    assert not any(n.startswith("children_married") for n in names)
    s = _dependents(children_unmarried=2, children_30plus_1y=1)
    assert (s.lo, s.hi) == (20, 20)


def test_faq161_owner_among_ascendants_excludes_all():
    """FAQ 161: 직계존속과 그 배우자 중 한 명이라도 주택 소유 → 둘 다 제외. 0명, ② 5점.

    소유자가 없으면 같은 직계존속 2명이 부양가족이라 ② 15점이다.
    """
    held = _dependents(is_household_head=True, ascendants_3y=2, ascendants_any_owner=True)
    assert (held.lo, held.hi) == (5, 5)
    free = _dependents(is_household_head=True, ascendants_3y=2, ascendants_any_owner=False)
    assert (free.lo, free.hi) == (15, 15)


def test_faq162_ascendants_need_household_head():
    """FAQ 162·163: 직계존속은 공고일 현재 세대주일 때만. 아니면 0명 ② 5점, 맞으면 2명 ② 15점.

    세대주로서 3년을 채울 필요는 없다(163) — 입력은 세대주 여부와 3년 이상 같은 등본인 수뿐이다.
    """
    off = _dependents(is_household_head=False, ascendants_3y=2)
    assert (off.lo, off.hi) == (5, 5)
    on = _dependents(is_household_head=True, ascendants_3y=2, ascendants_any_owner=False)
    assert (on.lo, on.hi) == (15, 15)


# FAQ 170 기간 산정 예시 6행: (가입일, 공고일, 기간, 청약통장점수)
FAQ170_ROWS = [
    (date(2001, 1, 15), date(2003, 5, 14), "2년4월0일", 3),
    (date(2006, 7, 7), date(2014, 8, 31), "8년1월25일", 3),
    (date(2014, 9, 1), date(2015, 10, 31), "1년2월0일", 2),
    (date(2015, 4, 1), date(2019, 4, 21), "4년0월21일", 3),
    (date(2019, 4, 22), date(2019, 8, 31), "0년4월10일", 1),
    (date(2019, 9, 1), date(2020, 6, 30), "0년10월0일", 1),
]


@pytest.mark.parametrize(("join", "notice", "text", "points"), FAQ170_ROWS)
def test_faq170_period_examples(join, notice, text, points):
    """FAQ 170 기간 산정 예시: (가입일, 공고일) → 기간 문자열과 점수. 가입일 당일을 1일로 센다."""
    assert str(profile.period(join, notice)) == text
    assert profile.spouse_bonus(join, notice) == points


def test_faq170_spouse_table_boundaries():
    """FAQ 170 배우자 통장 점수표: 미가입 0 · 1년 미만 1 · 1년 이상~2년 미만 2 · 2년 이상 3."""
    join = date(2020, 3, 15)
    assert profile.spouse_bonus(None, AS_OF) == 0
    assert profile.spouse_bonus(join, date(2021, 3, 13)) == 1  # 0년11월30일
    assert profile.spouse_bonus(join, date(2021, 3, 14)) == 2  # 1년0월0일
    assert profile.spouse_bonus(join, date(2022, 3, 13)) == 2  # 1년11월30일
    assert profile.spouse_bonus(join, date(2022, 3, 14)) == 3  # 2년0월0일
