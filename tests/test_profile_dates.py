"""기간 계산과 만 나이의 경계 (#77 통과 기준 4의 날짜 부분, 설계 §6-2·§6-3)."""

from datetime import date, timedelta

import pytest

from cheongyak_rag import profile
from cheongyak_rag.profile_check import RAW_LAW, load_raw_rows

# 월말 가입(31일 · 2월 29일)이 경계를 어긋나게 하는지 보려고 일부러 넣었다
STARTS = [date(2000, 1, 31), date(2000, 2, 29), date(2019, 3, 15), date(2024, 2, 29)]


def test_start_day_counts_as_day_one():
    """가입일 당일을 1일로 센다(FAQ 170). 하루짜리 기간이 0년0월1일이다."""
    assert profile.period(date(2020, 1, 1), date(2020, 1, 1)) == (0, 0, 1)
    assert profile.period(date(2020, 1, 1), date(2020, 12, 31)) == (1, 0, 0)  # 윤년 366일


def test_end_before_start_is_empty_period():
    """공고일이 시작일보다 앞서면 기간이 없다."""
    assert profile.period(date(2020, 1, 2), date(2020, 1, 1)) == (0, 0, 0)


def test_month_end_start_clamps_to_month_length():
    """31일 시작은 짧은 달 말일로 맞춘다 — 1개월 경계가 2월 말일이다."""
    start = date(2000, 1, 31)
    assert profile.period(start, date(2000, 2, 27)) == (0, 0, 28)
    assert profile.period(start, date(2000, 2, 28)) == (0, 1, 0)  # 1월 31일 + 1개월 = 2월 29일


def test_period_text():
    assert str(profile.Period(4, 0, 21)) == "4년0월21일"


@pytest.mark.parametrize("start", STARTS)
def test_table_thresholds_start_day_and_day_before(start):
    """원문 표의 구간 시작일에 구간 점수가 붙고, 그 전날은 앞 구간 점수다 (① · ③)."""
    for key, points in (("homeless", profile.homeless_points), ("savings", profile.savings_points)):
        rows = sorted((r for r in load_raw_rows(RAW_LAW) if r[0] == key), key=lambda r: r[1])
        for prev, row in zip(rows, rows[1:], strict=False):
            lo, score = row[1], row[3]
            last_day = profile.add_months(start, lo) - timedelta(
                days=1
            )  # 기간이 막 lo개월이 되는 날
            assert profile.period_months(start, last_day) == lo, (key, lo)
            assert points(profile.period_months(start, last_day)) == score
            before = profile.period_months(start, last_day - timedelta(days=1))
            assert before == lo - 1, (key, lo)
            assert points(before) == prev[3]


def test_age_turns_on_birthday():
    """만 나이는 생일 당일에 올라간다 (설계 §6-3: 생일 당일부터 30세)."""
    birth = date(1990, 5, 1)
    assert profile.age_on(birth, date(2020, 4, 30)) == 29
    assert profile.age_on(birth, date(2020, 5, 1)) == 30
    assert profile.add_years(birth, 30) == date(2020, 5, 1)


def test_feb29_birthday_is_feb28_in_common_years():
    """2월 29일 출생자의 평년 생일은 2월 28일이다 (설계 §6-2). 윤년이면 29일이다."""
    birth = date(2000, 2, 29)
    assert profile.add_years(birth, 1) == date(2001, 2, 28)
    assert profile.add_years(birth, 4) == date(2004, 2, 29)
    assert profile.age_on(birth, date(2001, 2, 27)) == 0
    assert profile.age_on(birth, date(2001, 2, 28)) == 1
    assert profile.age_on(birth, date(2004, 2, 28)) == 3
    assert profile.age_on(birth, date(2004, 2, 29)) == 4


def test_add_months_clamps():
    assert profile.add_months(date(2020, 1, 31), 1) == date(2020, 2, 29)
    assert profile.add_months(date(2021, 1, 31), 1) == date(2021, 2, 28)
    assert profile.add_months(date(2020, 11, 30), 3) == date(2021, 2, 28)
