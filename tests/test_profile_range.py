"""부분 프로필 범위 (#77 통과 기준 5, 설계 §4)."""

import dataclasses
import random
from datetime import date

import pytest

from cheongyak_rag import profile
from cheongyak_rag import profile_check as check

T = date(2026, 10, 23)
FIELDS = [f.name for f in dataclasses.fields(profile.Profile)]


def pair(r):
    return (r.lo, r.hi)


def test_empty_profile_range():
    """빈 프로필: ① 0~32 · ② 5~35 · ③ 1~17, 합계 (0 + 5 + 1) ~ (32 + 35 + 17)."""
    r = profile.score(profile.Profile(), T)
    assert pair(r.homeless) == (0, 32)
    assert pair(r.dependents) == (5, 35)
    assert pair(r.savings) == (1, 17)
    assert pair(r.total) == (6, 84)
    # ever_married는 married가 False라고 답한 뒤에야 묻는다
    assert r.missing == tuple(f for f in FIELDS if f != "ever_married")


def test_complete_profiles_are_exact_and_match_the_oracle():
    """완전 프로필이면 lo == hi이고, 범위 엔진을 거치지 않고 센 값과 같다."""
    rng = random.Random(1)
    for i in range(300):
        full = check.random_complete(rng, T, minimal=i % 2 == 0)
        r = profile.score(full, T)
        assert r.missing == ()
        actual = check.exact(full, T)
        assert (r.homeless.lo, r.dependents.lo, r.savings.lo) == tuple(actual.values())
        assert r.homeless.exact and r.dependents.exact and r.savings.exact and r.total.exact


def test_soundness_2000_random_partial_profiles():
    """무작위 완전 프로필 2000개에서 필드를 지운 프로필의 범위가 실제 점수를 놓친 건수는 0이다."""
    result = check.soundness(2000, seed=77)
    assert result["n"] == 2000
    assert result["violations"] == 0, result["examples"]


def test_soundness_check_is_not_vacuous():
    """같은 측정이 일부러 좁힌 범위는 잡는다 — 지운 칸이 많아야 범위가 의미를 갖는다."""
    result = check.soundness(300, seed=5, shrink=True)
    assert result["violations"] > 0
    erased = check.soundness(300, seed=5)["avg_erased"]
    assert erased >= 3


def test_tightness_is_measured_per_field_and_item():
    """필드 하나만 모를 때 범위 lo·hi가 전수 대입의 실제 최소·최대와 같은 비율이 0.95 이상이다."""
    result = check.tightness(bases=3, seed=77, as_of=T)
    assert result["measured"] >= 15  # 측정이 공허하지 않다
    assert result["ratio"] >= 0.95, result["loose"]


# ── 설계 §4 항목별 바닥값 ────────────────────────────────────────────────


def test_homeless_unknown_now_lo_zero_hi_from_age_18():
    """① homeless_now를 모르면 lo=0. hi는 만 18세 되는 날 혼인했다고 보고 센 값이다."""
    r = profile.score(profile.Profile(birth_date=date(1999, 5, 10)), T)
    assert pair(r.homeless) == (0, 20)  # 2017-05-10부터 9년5월 → 20점


def test_homeless_hi_respects_homeless_since():
    """무주택자가 된 날을 알면 그 날과 만 18세 되는 날 중 늦은 날부터 센다."""
    p = profile.Profile(birth_date=date(1999, 5, 10), homeless_since=date(2022, 1, 1))
    r = profile.score(p, T)
    assert pair(r.homeless) == (0, 10)  # 2022-01-01부터 4년9월 → 10점


def test_homeless_known_inputs_give_one_value():
    p = profile.Profile(
        birth_date=date(1999, 5, 10),
        married=False,
        ever_married=False,
        homeless_now=True,
        ever_owned=False,
    )
    assert pair(profile.score(p, T).homeless) == (0, 0)  # 만 30세가 2029년이다


def test_savings_unknown_join_lo_is_one_and_hi_is_birth_day_join():
    """③ 가입일을 모르면 lo=1(가입은 했다고 본다). hi는 출생일 가입에 제10조⑥을 적용해 센 값이다."""
    p = profile.Profile(birth_date=date(1990, 1, 1), married=False)
    r = profile.score(p, T)
    # 성년 2009-01-01. 출생일(1990-01-01) 가입은 성년 전 2년만 인정 → 2007-01-01부터 센다
    assert r.savings.lo == 1
    assert r.savings.hi == profile.savings_points(
        profile.period_months(profile.savings_start(date(1990, 1, 1), date(1990, 1, 1)), T)
    )
    assert r.savings.hi == 17  # 2007-01-01부터 19년9월 → 15년 이상


def test_savings_unknown_spouse_adds_zero_to_three():
    p = profile.Profile(
        birth_date=date(1990, 1, 1), married=True, savings_join_date=date(2018, 5, 1)
    )
    r = profile.score(p, T)
    own = 10  # 8년5월
    assert pair(r.savings) == (own, own + 3)


def test_dependents_unknown_counts_span_to_35():
    p = profile.Profile(married=True, children_unmarried=1)
    r = profile.score(p, T)
    # 배우자 1 + 자녀 1 = 2명(15점)에서, 모르는 자녀·직계존속이 더해지면 6명 이상(35점)
    assert pair(r.dependents) == (15, 35)


def test_spouse_join_date_implies_married_and_savings():
    """배우자 통장 가입일을 적었으면 배우자가 있고 통장이 있다."""
    p = profile.Profile(spouse_savings_join_date=date(2015, 2, 10))
    r = profile.score(p, T)
    assert r.dependents.lo == 10  # 배우자 1명은 확정
    assert r.values["spouse_bonus"].value == 3


def test_homeless_since_implies_ever_owned():
    p = profile.Profile(homeless_since=date(2020, 1, 1))
    assert "ever_owned" not in profile.score(p, T).missing


# ── missing ──────────────────────────────────────────────────────────────


def test_missing_skips_fields_that_cannot_change_the_score():
    """점수를 못 바꾸는 칸은 missing에 넣지 않는다 (#82가 읽는다)."""
    base = {f: None for f in FIELDS}
    owner = profile.Profile(**{**base, "homeless_now": False, "married": False,
                               "ascendants_3y": 0})  # fmt: skip
    m = profile.score(owner, T).missing
    assert "ever_owned" not in m and "homeless_since" not in m and "marriage_date" not in m
    assert "is_household_head" not in m and "ascendants_any_owner" not in m  # 직계존속 0명
    assert "spouse_has_savings" not in m and "spouse_savings_join_date" not in m  # 배우자 없음
    assert {"birth_date", "savings_join_date", "children_unmarried"} <= set(m)


def test_missing_skips_ascendant_fields_when_ascendants_count_as_zero():
    """리뷰 지적: 세대주가 아니거나 소유자가 있으면 직계존속은 몇 명이든 0명이다.

    그때 ascendants_3y(와 소유자 있음 답 뒤의 is_household_head)는 ②를 바꾸지 못하므로 묻지 않는다.
    """
    not_head = profile.score(profile.Profile(is_household_head=False), T)
    assert "ascendants_3y" not in not_head.missing
    assert "ascendants_any_owner" not in not_head.missing

    owned = profile.score(profile.Profile(ascendants_any_owner=True), T)
    assert "ascendants_3y" not in owned.missing
    assert "is_household_head" not in owned.missing


@pytest.mark.parametrize("field", ["birth_date", "savings_join_date"])
def test_missing_lists_the_blank_field(field):
    full = check.random_complete(random.Random(3), T)
    blank = dataclasses.replace(full, **{field: None})
    assert profile.score(blank, T).missing == (field,)


# ── 이혼·사별: married=False만으로는 혼인 이력을 모른다 ───────────────────────

DIVORCEE = dict(birth_date=date(1990, 1, 1), married=False, homeless_now=True, ever_owned=False)


def test_unmarried_without_history_answer_is_a_range_not_a_wrong_exact_value():
    """리뷰 지적: 지금 배우자가 없다는 답만으로는 ①이 한 값으로 정해지지 않는다.

    1990-01-01생이 2012-03-01(만 22세)에 혼인했다가 이혼했으면 ① 30점, 혼인한 적이 없으면 14점이다.
    """
    r = profile.score(profile.Profile(**DIVORCEE), T)
    assert pair(r.homeless) == (14, 32)  # hi: 만 18세(2008-01-01)에 혼인했다면
    assert r.missing == (
        "ever_married",
        "is_household_head",
        "children_unmarried",
        "children_30plus_1y",
        "ascendants_3y",
        "ascendants_any_owner",
        "savings_join_date",
    )


def test_never_married_and_divorced_are_each_exact():
    never = profile.score(profile.Profile(**DIVORCEE, ever_married=False), T)
    assert pair(never.homeless) == (14, 14) and "ever_married" not in never.missing
    divorced = profile.score(
        profile.Profile(**DIVORCEE, ever_married=True, marriage_date=date(2012, 3, 1)), T
    )
    assert pair(divorced.homeless) == (30, 30) and "marriage_date" not in divorced.missing


def test_divorced_without_date_asks_for_the_date():
    r = profile.score(profile.Profile(**DIVORCEE, ever_married=True), T)
    assert "marriage_date" in r.missing and "ever_married" not in r.missing


@pytest.mark.parametrize(
    "over",
    [
        dict(ever_married=False, marriage_date=date(2012, 3, 1)),
        dict(ever_married=False, married=True),
    ],
)
def test_ever_married_false_contradicts_marriage(over):
    with pytest.raises(profile.ProfileError):
        profile.score(profile.Profile(**{**DIVORCEE, **over}), T)


def test_married_implies_ever_married():
    p = profile.Profile(birth_date=date(1990, 1, 1), married=True)
    assert profile.score(p, T).missing[0:2] == ("marriage_date", "homeless_now")
