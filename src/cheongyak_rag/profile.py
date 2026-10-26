"""프로필 입력을 판정용 값과 가점(부분 입력이면 범위)으로 바꾼다 (#77).

기준일은 입주자모집공고일이다. LLM·네트워크 호출이 없고 날짜 연산은 `datetime.date`만 쓴다.
점수표는 「주택공급에 관한 규칙」 별표 1(MST 286965)이다. 상수는 코드에 적고,
`profile_check`가 원문 표를 파싱한 결과와 테스트로 대조한다.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import NamedTuple

# (하한, 상한 미포함 | None, 점수). 무주택기간·통장 가입기간은 개월, 부양가족은 명이다.
# 별표 1 제2호나목 ① 무주택기간 (상한 32점)
HOMELESS_TABLE = (
    (0, 12, 2),
    (12, 24, 4),
    (24, 36, 6),
    (36, 48, 8),
    (48, 60, 10),
    (60, 72, 12),
    (72, 84, 14),
    (84, 96, 16),
    (96, 108, 18),
    (108, 120, 20),
    (120, 132, 22),
    (132, 144, 24),
    (144, 156, 26),
    (156, 168, 28),
    (168, 180, 30),
    (180, None, 32),
)
# ② 부양가족 수 (상한 35점)
DEPENDENTS_TABLE = (
    (0, 1, 5),
    (1, 2, 10),
    (2, 3, 15),
    (3, 4, 20),
    (4, 5, 25),
    (5, 6, 30),
    (6, None, 35),
)
# ③ 주택청약종합저축 가입기간 (상한 17점)
SAVINGS_TABLE = (
    (0, 6, 1),
    (6, 12, 2),
    (12, 24, 3),
    (24, 36, 4),
    (36, 48, 5),
    (48, 60, 6),
    (60, 72, 7),
    (72, 84, 8),
    (84, 96, 9),
    (96, 108, 10),
    (108, 120, 11),
    (120, 132, 12),
    (132, 144, 13),
    (144, 156, 14),
    (156, 168, 15),
    (168, 180, 16),
    (180, None, 17),
)


def _lookup(table: tuple, value: int) -> int:
    for lo, hi, score in table:
        if value >= lo and (hi is None or value < hi):
            return score
    raise ValueError(f"표 범위 밖 값: {value}")


def homeless_points(months: int) -> int:
    """무주택기간(개월) → ① 점수."""
    return _lookup(HOMELESS_TABLE, months)


def dependents_points(count: int) -> int:
    """부양가족 수(명) → ② 점수."""
    return _lookup(DEPENDENTS_TABLE, count)


def savings_points(months: int) -> int:
    """통장 가입기간(개월) → ③ 점수표 값 (배우자 가산 전)."""
    return _lookup(SAVINGS_TABLE, months)


# ── 기간 계산 ────────────────────────────────────────────────────────────


class Period(NamedTuple):
    years: int
    months: int
    days: int

    def __str__(self) -> str:
        return f"{self.years}년{self.months}월{self.days}일"


def add_months(d: date, n: int) -> date:
    """n개월 뒤. 그 달에 같은 날이 없으면 말일로 맞춘다 (1월 31일 + 1개월 = 2월 말일)."""
    year, month = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(year, month + 1, min(d.day, calendar.monthrange(year, month + 1)[1]))


def add_years(d: date, n: int) -> date:
    """n년 뒤. 2월 29일의 평년 생일은 2월 28일이다 (설계 §6-2)."""
    return add_months(d, 12 * n)


def age_on(birth: date, on: date) -> int:
    """만 나이. 생일 당일부터 한 살 더 센다 (설계 §6-3)."""
    n = on.year - birth.year
    return n - 1 if add_years(birth, n) > on else n


def period_months(start: date, end: date) -> int:
    """start부터 end까지 채운 개월 수. start 당일을 1일로 센다 (FAQ 170)."""
    stop = end + timedelta(days=1)
    if stop <= start:
        return 0
    months = (stop.year - start.year) * 12 + stop.month - start.month
    return months - 1 if add_months(start, months) > stop else months


def period(start: date, end: date) -> Period:
    """start부터 end까지의 기간(년·월·일). start 당일을 1일로 센다 (FAQ 170)."""
    stop = end + timedelta(days=1)
    if stop <= start:
        return Period(0, 0, 0)
    months = period_months(start, end)
    return Period(*divmod(months, 12), (stop - add_months(start, months)).days)
