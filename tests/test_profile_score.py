"""완전 프로필의 판정용 값과 항목 점수, 설계 §6 열린 질문 네 개의 고정 (#77 Task 4)."""

import random
from datetime import date

import pytest

from cheongyak_rag import profile

T = date(2026, 10, 23)

COMPLETE = dict(
    birth_date=date(1988, 3, 15),
    married=True,
    marriage_date=date(2016, 5, 20),  # 만 28세 — 30세 전 혼인이라 무주택 기산일이 된다
    homeless_now=True,
    ever_owned=False,
    is_household_head=True,
    children_unmarried=1,
    children_30plus_1y=0,
    ascendants_3y=1,
    ascendants_any_owner=False,
    savings_join_date=date(2012, 7, 1),
    spouse_has_savings=True,
    spouse_savings_join_date=date(2015, 2, 10),
)


def score(as_of=T, **over):
    return profile.score(profile.Profile(**{**COMPLETE, **over}), as_of)


def pair(r):
    return (r.lo, r.hi)


def test_complete_profile_items_and_total():
    """손으로 센 값. ① 2016-05-20~2026-10-23 = 10년5월4일 → 22.

    ② 배우자 1 + 자녀 1 + 직계존속 1 = 3명 → 20.
    ③ 14년3월23일 → 16 + 배우자 가산 3 = 19 → 17점 상한.
    """
    r = score()
    assert (pair(r.homeless), pair(r.dependents), pair(r.savings)) == ((22, 22), (20, 20), (17, 17))
    assert pair(r.total) == (59, 59)
    assert r.missing == ()


def test_complete_profile_judgement_values_carry_basis():
    """판정용 값마다 값과 근거 문자열이 같이 있다 — #79가 판정 프롬프트에 그대로 넘긴다."""
    v = score().values
    assert v["age"].value == 38
    assert v["homeless_start"].value == date(2016, 5, 20)
    assert str(v["homeless_period"].value) == "10년5월4일"
    assert v["dependents"].value == 3
    assert str(v["savings_period"].value) == "14년3월23일"
    assert v["spouse_bonus"].value == 3
    assert "별표1 1호가목3" in v["homeless_start"].basis
    assert "별표1 1호나목" in v["dependents"].basis
    assert "별표1 1호다목" in v["savings_period"].basis
    assert "별표1 비고2" in v["spouse_bonus"].basis
    assert all(x.basis for x in v.values())


def test_minor_cap_is_named_in_basis():
    """제10조⑥이 기간을 줄였으면 근거에 그 조문이 적힌다."""
    r = score(
        as_of=date(2026, 1, 1),
        birth_date=date(2007, 1, 1),
        marriage_date=None,
        married=False,
        spouse_has_savings=None,
        spouse_savings_join_date=None,
        savings_join_date=date(2019, 1, 1),
    )
    assert "제10조⑥" in r.values["savings_period"].basis
    assert "제10조⑥" not in score().values["savings_period"].basis


# ── 제10조⑥ 경계 ─────────────────────────────────────────────────────────

BIRTH_2007 = date(2007, 1, 1)  # 만 19세 되는 날 2026-01-01
BIRTH_2009 = date(2009, 1, 1)  # 만 19세 되는 날 2028-01-01


@pytest.mark.parametrize(
    ("join", "birth", "start"),
    [
        # 2023-12-31 이전 부분이 딱 2년이면 그대로, 하루라도 넘으면 2022-01-01부터 센다
        (date(2022, 1, 2), BIRTH_2007, date(2022, 1, 2)),
        (date(2022, 1, 1), BIRTH_2007, date(2022, 1, 1)),
        (date(2021, 12, 31), BIRTH_2007, date(2022, 1, 1)),
        # 이전 2년 + 이후 4년 = 6년이면 합계 5년 상한이 먼저 걸린다
        (date(2023, 1, 1), BIRTH_2009, date(2023, 1, 1)),
        (date(2022, 12, 31), BIRTH_2009, date(2023, 1, 1)),
        (date(2022, 1, 1), BIRTH_2009, date(2023, 1, 1)),
        # 성년 전에 전부 2024년 앞에 끝나면 2년만 인정 (2000-06-01생, 성년 2019-06-01)
        (date(2010, 1, 1), date(2000, 6, 1), date(2017, 6, 1)),
        # 2024년 뒤에 가입한 미성년은 상한이 5년 하나뿐이다 (실제 기간 2년3개월 — 안 걸린다)
        (date(2024, 3, 1), date(2007, 6, 1), date(2024, 3, 1)),
        # 성년 이후 가입은 그대로
        (date(2026, 1, 1), BIRTH_2007, date(2026, 1, 1)),
    ],
)
def test_minor_period_caps(join, birth, start):
    """제10조⑥: 2023-12-31 이전 미성년 기간은 2년까지, 2024-01-01 이후와 합쳐 5년까지."""
    assert profile.savings_start(join, birth) == start


def test_minor_cap_never_shortens_adult_join():
    assert profile.savings_start(date(2010, 3, 1), date(1980, 1, 1)) == date(2010, 3, 1)


# ── 배우자 가산 · ③ 합계 상한 ─────────────────────────────────────────────


def test_spouse_bonus_capped_at_three():
    """배우자 통장이 아무리 길어도 가산은 3점까지다."""
    assert profile.spouse_bonus(date(1995, 1, 1), T) == 3
    assert profile.spouse_bonus(date(2025, 10, 22), T) == 2  # 1년0월2일
    assert profile.spouse_bonus(date(2025, 10, 25), T) == 1  # 0년11월29일


def test_savings_total_capped_at_17():
    """③ 합계는 17점까지: 본인 15점 + 가산 3점 = 18 → 17. 17 아래에서는 그대로 더한다."""
    over = score(savings_join_date=date(2013, 8, 1))  # 13년2월23일 → 15점
    assert pair(over.savings) == (17, 17)
    none = score(savings_join_date=date(2013, 8, 1), spouse_has_savings=False,
                 spouse_savings_join_date=None)  # fmt: skip
    assert pair(none.savings) == (15, 15)
    under = score(savings_join_date=date(2018, 5, 1))  # 8년5월23일 → 10점 + 3
    assert pair(under.savings) == (13, 13)


def test_no_spouse_means_no_bonus():
    r = score(married=False, marriage_date=None, spouse_has_savings=None,
              spouse_savings_join_date=None)  # fmt: skip
    assert r.values["spouse_bonus"].value == 0
    assert pair(r.savings) == (16, 16)


# ── 설계 §6 열린 질문 ────────────────────────────────────────────────────

SINGLE = dict(
    married=False,
    marriage_date=None,
    spouse_has_savings=None,
    spouse_savings_join_date=None,
    homeless_now=True,
    ever_owned=False,
)


def test_open_q1_under_30_unmarried_scores_zero():
    """§6-1: 30세 미만 미혼 무주택자는 ① 0점 — 무주택기간이 아직 시작되지 않았다."""
    r = score(birth_date=date(2000, 1, 1), **SINGLE)
    assert pair(r.homeless) == (0, 0)
    assert str(r.values["homeless_period"].value) == "0년0월0일"
    assert r.values["homeless_start"].value == date(2030, 1, 1)


def test_open_q3_thirtieth_birthday_starts_the_count():
    """§6-3: 생일 당일부터 30세다. 30세 되는 날이 공고일이면 1일 → ① 2점, 그 전날은 0점."""
    on = score(birth_date=date(1996, 10, 23), **SINGLE)
    assert pair(on.homeless) == (2, 2)
    assert str(on.values["homeless_period"].value) == "0년0월1일"
    day_before = score(as_of=date(2026, 10, 22), birth_date=date(1996, 10, 23), **SINGLE)
    assert pair(day_before.homeless) == (0, 0)


def test_open_q2_feb29_birth_turns_30_on_feb28():
    """§6-2: 2월 29일 출생의 평년 생일은 2월 28일 — 2026-02-28에 30세가 된다."""
    born = date(1996, 2, 29)
    assert score(as_of=date(2026, 2, 28), birth_date=born, **SINGLE).homeless.lo == 2
    assert score(as_of=date(2026, 2, 27), birth_date=born, **SINGLE).homeless.lo == 0
    # 윤년에는 29일이다 (2028년에 만 32세)
    assert profile.add_years(born, 32) == date(2028, 2, 29)


def test_open_q4_spouse_savings_ignore_minor_cap():
    """§6-4: 배우자 통장에는 제10조⑥을 적용하지 않는다 — 가입일 그대로 센다.

    배우자 생년월일은 입력이 아니고, 신청자의 생년월일이 바뀌어도 가산은 같다.
    """
    a = score(birth_date=date(1988, 3, 15))
    b = score(birth_date=date(1996, 3, 15), marriage_date=date(2020, 1, 1))
    assert a.values["spouse_bonus"].value == b.values["spouse_bonus"].value == 3
    assert "가입일 그대로" in a.values["spouse_bonus"].basis


# ── 무주택 ① 그 밖의 경계 ────────────────────────────────────────────────


def test_homeless_zero_when_house_owned_even_if_everything_else_known():
    assert pair(score(homeless_now=False).homeless) == (0, 0)


def test_ever_owned_moves_start_to_later_of_two():
    r = score(ever_owned=True, homeless_since=date(2020, 1, 15))
    assert r.values["homeless_start"].value == date(2020, 1, 15)
    assert str(r.values["homeless_period"].value) == "6년9월9일"
    assert pair(r.homeless) == (14, 14)
    early = score(ever_owned=True, homeless_since=date(2010, 1, 1))
    assert early.values["homeless_start"].value == date(2016, 5, 20)  # 혼인신고일이 더 늦다


def test_marriage_after_30_does_not_move_start():
    r = score(birth_date=date(1980, 3, 1), marriage_date=date(2015, 6, 1))
    assert r.values["homeless_start"].value == date(2010, 3, 1)


# ── 부양가족 ② ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("count", "points"), [(0, 5), (1, 10), (2, 15), (3, 20), (4, 25), (5, 30)])
def test_dependents_points_by_count(count, points):
    r = score(married=False, marriage_date=None, spouse_has_savings=None,
              spouse_savings_join_date=None, ascendants_3y=0, children_unmarried=count)  # fmt: skip
    assert pair(r.dependents) == (points, points)


@pytest.mark.parametrize("count", [6, 7, 10, 25])
def test_dependents_six_or_more_is_35(count):
    r = score(children_unmarried=count - 2, children_30plus_1y=0)  # 배우자 1 + 직계존속 1 + 자녀
    assert pair(r.dependents) == (35, 35)


def test_ascendants_counted_only_for_household_head_without_owner():
    for head, owner, counted in ((True, False, True), (False, None, False), (True, True, False)):
        r = score(is_household_head=head, ascendants_any_owner=owner, ascendants_3y=2)
        assert r.values["dependents"].value == (4 if counted else 2)  # 배우자 + 자녀 (+ 직계존속 2)


# ── 입력 검증 · JSON ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "over",
    [
        dict(
            ever_owned=False, homeless_since=date(2020, 1, 1)
        ),  # 소유 이력 없는데 무주택자가 된 날
        dict(savings_join_date=date(1980, 1, 1)),  # 태어나기 전 가입
        dict(marriage_date=date(2000, 1, 1)),  # 만 18세 전 혼인
        dict(savings_join_date=date(2027, 1, 1)),  # 공고일 뒤 가입
        dict(birth_date=date(2020, 1, 1), marriage_date=None, savings_join_date=date(2021, 1, 1)),
        dict(children_unmarried=-1),
        dict(
            married=False, spouse_savings_join_date=date(2015, 2, 10)
        ),  # 배우자 없는데 배우자 통장
    ],
)
def test_contradictory_input_raises(over):
    with pytest.raises(profile.ProfileError):
        score(**over)


def test_profile_json_roundtrip_and_unknown_key():
    p = profile.Profile(**COMPLETE)
    assert profile.Profile.from_dict(p.to_dict()) == p
    assert p.to_dict()["birth_date"] == "1988-03-15"
    assert profile.Profile.from_dict({}) == profile.Profile()
    with pytest.raises(profile.ProfileError):
        profile.Profile.from_dict({"birth": "1988-03-15"})
    with pytest.raises(profile.ProfileError):
        profile.Profile.from_dict({"birth_date": "1988-13-45"})
    with pytest.raises(profile.ProfileError):
        profile.Profile.from_dict({"married": "yes"})


def test_spouse_bonus_same_with_or_without_minor_cap():
    """§6-4의 영향: 제10조⑥을 배우자 통장에 적용해도 가산점이 안 달라진다.

    상한은 기간을 2년 아래로 줄이지 못하고, 가산 3점은 2년이면 채워진다.
    """
    rng = random.Random(4)
    first, last = date(1990, 1, 1).toordinal(), date(2007, 6, 1).toordinal()
    for _ in range(3000):
        birth = date.fromordinal(rng.randint(first, last))
        join = date.fromordinal(rng.randint(birth.toordinal(), T.toordinal()))
        capped = profile.savings_start(join, birth)
        assert profile.spouse_bonus(capped, T) == profile.spouse_bonus(join, T), (birth, join)
