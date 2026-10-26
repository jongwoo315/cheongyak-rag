"""프로필 입력을 판정용 값과 가점(부분 입력이면 범위)으로 바꾼다 (#77).

기준일은 입주자모집공고일이다. LLM·네트워크 호출이 없고 날짜 연산은 `datetime.date`만 쓴다.
점수표는 「주택공급에 관한 규칙」 별표 1(MST 286965)이다. 상수는 코드에 적고,
`profile_check`가 원문 표를 파싱한 결과와 테스트로 대조한다.
"""

from __future__ import annotations

import calendar
import dataclasses
from dataclasses import dataclass, field
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


# ── 값을 정하는 규칙 ─────────────────────────────────────────────────────

MIN_AGE = 19  # 가점제 신청자는 공고일 현재 성년이다
MARRIAGE_AGE = 18  # 혼인 가능 최저 연령 (설계 §4)
MAX_AGE = 100  # 생년월일을 모를 때 보는 가장 이른 출생: 공고일 100년 전
MAX_COUNT = 10  # 자녀·직계존속 수를 모를 때의 상한. 6명 이상이면 35점이라 10이면 충분하다
PRE_2024_END = date(2023, 12, 31)  # 제10조⑥: 이 날 이전 미성년 기간은 2년까지
MINOR_PRE_CAP_YEARS, MINOR_TOTAL_CAP_YEARS = 2, 5
SPOUSE_BONUS_MAX, SAVINGS_MAX = 3, 17  # 별표 1 비고 2


def homeless_start(
    birth_date: date,
    marriage_date: date | None,
    ever_owned: bool | None,
    homeless_since: date | None,
) -> date:
    """무주택 기산일 (별표1 1호가목3, FAQ 153·156).

    만 30세 되는 날. 30세 전에 혼인했으면 혼인신고일. 소유 이력이 있으면 그 날과
    무주택자가 된 날 중 늦은 날.
    """
    start = add_years(birth_date, 30)
    if marriage_date is not None and marriage_date < start:
        start = marriage_date
    if ever_owned and homeless_since is not None and homeless_since > start:
        start = homeless_since
    return start


def savings_start(join_date: date, birth_date: date) -> date:
    """제10조⑥을 반영한 통장 가입기간의 시작일. 이 날부터 공고일까지 세면 인정 기간이다.

    미성년(만 19세 전)으로 가입한 기간 중 2023-12-31 이전 부분은 2년까지, 2024-01-01 이후
    부분과 합쳐 5년까지만 인정한다. 둘 다 앞쪽(오래된 쪽)을 잘라 내므로 시작일이 뒤로 간다.
    """
    adult = add_years(birth_date, 19)
    if join_date >= adult:
        return join_date
    start = join_date
    if join_date <= PRE_2024_END:
        pre_end = min(PRE_2024_END, adult - timedelta(days=1))
        start = max(start, add_years(pre_end + timedelta(days=1), -MINOR_PRE_CAP_YEARS))
    return max(start, add_years(adult, -MINOR_TOTAL_CAP_YEARS))


def spouse_bonus(join_date: date | None, as_of: date) -> int:
    """배우자 통장 가산점 (별표1 비고2, FAQ 170). 가입기간의 50%에 ③ 점수표를 적용해 3점까지.

    배우자 생년월일을 받지 않아 제10조⑥은 적용하지 않는다 (설계 §6-4).
    """
    if join_date is None:
        return 0
    return min(SPOUSE_BONUS_MAX, savings_points(period_months(join_date, as_of) // 2))


# ── 입력 ─────────────────────────────────────────────────────────────────


class ProfileError(ValueError):
    """프로필 입력이 서로 모순되거나 형식이 틀렸다."""


@dataclass(frozen=True)
class Profile:
    """사용자 입력. 전부 optional이고 `None`은 모른다는 뜻이다 (설계 §2).

    제53조 무주택 간주는 판정하지 않는다 — `homeless_now`·`homeless_since`는 사용자가 그 판정을
    끝낸 값이다.

    설계 §2에 없는 칸이 둘 있다. `spouse_has_savings`는 `spouse_savings_join_date`가 비어 있을 때
    「배우자 통장이 없다」와 「모른다」를 가르려고 더했다. `ever_married`는 `married`(지금 배우자가
    있다)만으로는 「혼인한 적이 없다」와 「이혼·사별했다」를 못 가르는데 ① 기산일이 후자에게
    혼인신고일을 쓰기 때문에 더했다.
    """

    birth_date: date | None = None
    married: bool | None = None  # 공고일 현재 배우자가 있다
    ever_married: bool | None = None  # 혼인한 적이 있다 (이혼·사별 포함)
    marriage_date: date | None = None  # 최초 혼인신고일 (이혼·사별했어도 적는다)
    homeless_now: bool | None = None
    ever_owned: bool | None = None
    homeless_since: date | None = None
    is_household_head: bool | None = None
    children_unmarried: int | None = None
    children_30plus_1y: int | None = None
    ascendants_3y: int | None = None
    ascendants_any_owner: bool | None = None
    savings_join_date: date | None = None
    spouse_has_savings: bool | None = None
    spouse_savings_join_date: date | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        names = {f.name: f for f in dataclasses.fields(cls)}
        unknown = set(data) - set(names)
        if unknown:
            raise ProfileError(f"알 수 없는 입력 칸: {sorted(unknown)}")
        out = {}
        for key, value in data.items():
            if value is None:
                continue
            kind = _KINDS[key]
            if kind == "date":
                try:
                    out[key] = date.fromisoformat(value)
                except (TypeError, ValueError):
                    raise ProfileError(f"{key}: YYYY-MM-DD 날짜여야 한다 ({value!r})") from None
            elif kind == "bool" and not isinstance(value, bool):
                raise ProfileError(f"{key}: true/false여야 한다 ({value!r})")
            elif kind == "count" and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ProfileError(f"{key}: 0 이상의 정수여야 한다 ({value!r})")
            else:
                out[key] = value
        return cls(**out)

    def to_dict(self) -> dict:
        return {
            f.name: v.isoformat() if isinstance(v := getattr(self, f.name), date) else v
            for f in dataclasses.fields(self)
        }


_KINDS = {
    **dict.fromkeys(
        ("birth_date", "marriage_date", "homeless_since", "savings_join_date",
         "spouse_savings_join_date"), "date"),
    **dict.fromkeys(
        ("married", "ever_married", "homeless_now", "ever_owned", "is_household_head",
         "ascendants_any_owner", "spouse_has_savings"), "bool"),
    **dict.fromkeys(("children_unmarried", "children_30plus_1y", "ascendants_3y"), "count"),
}  # fmt: skip


def _resolve(p: Profile, as_of: date) -> Profile:
    """입력끼리 모순을 잡고, 다른 칸이 정해 주는 값을 채운다 (소유 이력 · 배우자 통장)."""
    owned, married, spouse_has = p.ever_owned, p.married, p.spouse_has_savings
    ever_married = p.ever_married
    if p.homeless_since is not None:
        if owned is False:
            raise ProfileError("소유 이력이 없다고 했는데 무주택자가 된 날이 있다")
        owned = True
    if p.spouse_savings_join_date is not None:
        if spouse_has is False:
            raise ProfileError("배우자 통장이 없다고 했는데 가입일이 있다")
        spouse_has = True
    if spouse_has:
        if married is False:
            raise ProfileError("배우자가 없다고 했는데 배우자 통장이 있다")
        married = True
    if p.marriage_date is not None or married is True:
        if ever_married is False:
            raise ProfileError("혼인한 적이 없다고 했는데 배우자나 혼인신고일이 있다")
        ever_married = True
    elif ever_married is False and married is None:
        married = False
    if married is False and spouse_has is None:
        spouse_has = False
    for name, kind in _KINDS.items():
        v = getattr(p, name)
        if kind == "count" and v is not None and v < 0:
            raise ProfileError(f"{name}: 0 이상이어야 한다 ({v})")
        if kind == "date" and v is not None and v > as_of:
            raise ProfileError(f"{name} {v}이 공고일 {as_of}보다 늦다")
    b = p.birth_date
    if b is not None:
        if age_on(b, as_of) < MIN_AGE:
            raise ProfileError(f"공고일 현재 만 {MIN_AGE}세 미만이다 (생년월일 {b})")
        if p.marriage_date is not None and p.marriage_date < add_years(b, MARRIAGE_AGE):
            raise ProfileError(
                f"혼인신고일 {p.marriage_date}이 만 {MARRIAGE_AGE}세 되는 날보다 빠르다"
            )
        if p.savings_join_date is not None and p.savings_join_date < b:
            raise ProfileError(f"통장 가입일 {p.savings_join_date}이 생년월일 {b}보다 빠르다")
    return dataclasses.replace(
        p,
        ever_owned=owned,
        married=married,
        ever_married=ever_married,
        spouse_has_savings=spouse_has,
    )


def _missing(p: Profile) -> tuple[str, ...]:
    """점수를 한 값으로 정하려면 더 필요한 칸. `_resolve`를 거친 프로필을 받는다."""
    homeless_open = p.homeless_now is not False
    has_asc = p.ascendants_3y != 0  # None이거나 1 이상
    # 세대주가 아니거나 소유자가 있으면 직계존속은 몇 명이든 0명으로 센다
    asc_counted = p.is_household_head is not False and p.ascendants_any_owner is not True
    spouse_open = p.married is not False
    need = {
        "birth_date": True,
        "married": True,
        "ever_married": homeless_open and p.married is False and p.ever_married is None,
        "marriage_date": homeless_open
        and (p.ever_married is True or (p.ever_married is None and p.married is not False)),
        "homeless_now": True,
        "ever_owned": homeless_open,
        "homeless_since": homeless_open and p.ever_owned is not False,
        "is_household_head": has_asc and p.ascendants_any_owner is not True,
        "children_unmarried": True,
        "children_30plus_1y": True,
        "ascendants_3y": asc_counted,
        "ascendants_any_owner": has_asc and p.is_household_head is not False,
        "savings_join_date": True,
        "spouse_has_savings": spouse_open,
        "spouse_savings_join_date": spouse_open and p.spouse_has_savings is not False,
    }
    return tuple(n for n, wanted in need.items() if wanted and getattr(p, n) is None)


# ── 결과 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Range:
    """항목 점수의 [lo, hi]. 모든 입력을 알면 lo == hi다."""

    lo: int
    hi: int

    @property
    def exact(self) -> bool:
        return self.lo == self.hi


@dataclass(frozen=True)
class Value:
    """판정용 값과 그 근거. 입력이 모자라 못 정하면 `value`가 None이고 근거에 이유를 적는다."""

    value: object
    basis: str


@dataclass(frozen=True)
class ProfileScore:
    as_of: date
    values: dict[str, Value]
    homeless: Range  # ① 무주택기간
    dependents: Range  # ② 부양가족 수
    savings: Range  # ③ 통장 가입기간 (배우자 가산 포함)
    total: Range
    missing: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        def plain(v):
            return v.isoformat() if isinstance(v, date) else str(v) if isinstance(v, Period) else v

        return {
            "as_of": self.as_of.isoformat(),
            "values": {
                k: {"value": plain(v.value), "basis": v.basis} for k, v in self.values.items()
            },
            "scores": {
                name: {"lo": r.lo, "hi": r.hi}
                for name, r in (
                    ("homeless", self.homeless),
                    ("dependents", self.dependents),
                    ("savings", self.savings),
                    ("total", self.total),
                )
            },
            "missing": list(self.missing),
        }


# ── 항목 점수와 범위 ─────────────────────────────────────────────────────
#
# 모르는 칸이 있으면 「아는 칸과 모순되지 않는 모든 완성」 중 최소·최대를 낸다.
# 항목 점수는 모르는 날짜 칸마다 한쪽으로만 움직이므로(단조), 최소·최대는 그 칸의 양 끝
# 값에서 나온다. 모르는 칸마다 양 끝 값(불리언은 둘 다)을 넣어 보고 점수의 최소·최대를 고른다.
# 날짜 칸의 양 끝은 서로의 제약(혼인 ≥ 만 18세, 가입 ≥ 출생)을 따른다.


def _latest_birth(n: int, on: date) -> date:
    """만 n세가 `on`까지 되는 가장 늦은 생년월일."""
    day = timedelta(days=1)
    b = add_years(on, -n)
    while add_years(b, n) > on:
        b -= day
    while add_years(b + day, n) <= on:
        b += day
    return b


def _earliest(as_of: date) -> date:
    return add_years(as_of, -MAX_AGE)


def _birth_domain(p: Profile, as_of: date) -> tuple[date, date]:
    """생년월일을 모를 때 가능한 [이른 쪽, 늦은 쪽]. 이미 아는 날짜가 늦은 쪽을 당긴다."""
    hi = _latest_birth(MIN_AGE, as_of)
    if p.savings_join_date is not None:
        hi = min(hi, p.savings_join_date)
    if p.marriage_date is not None:
        hi = min(hi, _latest_birth(MARRIAGE_AGE, p.marriage_date))
    return min(_earliest(as_of), hi), hi


def _births(p: Profile, as_of: date) -> list[date]:
    if p.birth_date is not None:
        return [p.birth_date]
    return sorted(set(_birth_domain(p, as_of)))


def _homeless_score(birth, marriage, owned, since, as_of: date) -> int:
    start = homeless_start(birth, marriage, owned, since)
    return 0 if start > as_of else homeless_points(period_months(start, as_of))


def _homeless_range(p: Profile, as_of: date) -> Range:
    if p.homeless_now is False:
        return Range(0, 0)
    owned_opts = [p.ever_owned] if p.ever_owned is not None else [False, True]
    scores = []
    for b in _births(p, as_of):
        if p.marriage_date is not None:
            marriages = [p.marriage_date]
        elif p.ever_married is False:
            marriages = [None]
        else:
            marriages = [add_years(b, MARRIAGE_AGE), as_of]
            marriages += [None] if p.ever_married is None else []
        for m in marriages:
            for owned in owned_opts:
                if not owned:
                    sinces = [None]
                else:
                    sinces = [p.homeless_since] if p.homeless_since else [_earliest(as_of), as_of]
                scores += [_homeless_score(b, m, owned, since, as_of) for since in sinces]
    return Range(0 if p.homeless_now is None else min(scores), max(scores))


def _dependents_count(p: Profile) -> tuple[int, int]:
    def span(v, unknown_hi=MAX_COUNT):
        return (v, v) if v is not None else (0, unknown_hi)

    spouse = (0, 1) if p.married is None else (int(p.married),) * 2
    kids = span(p.children_unmarried), span(p.children_30plus_1y)
    asc_lo, asc_hi = span(p.ascendants_3y)
    counted = p.is_household_head is not False and p.ascendants_any_owner is not True
    certain = p.is_household_head is True and p.ascendants_any_owner is False
    lo = spouse[0] + sum(k[0] for k in kids) + (asc_lo if certain else 0)
    hi = spouse[1] + sum(k[1] for k in kids) + (asc_hi if counted else 0)
    return lo, hi


def _dependents_range(p: Profile) -> Range:
    lo, hi = _dependents_count(p)
    return Range(dependents_points(lo), dependents_points(hi))


def _savings_own_points(join: date, birth: date, as_of: date) -> int:
    return savings_points(period_months(savings_start(join, birth), as_of))


def _spouse_bonus_range(p: Profile, as_of: date) -> Range:
    if p.married is False or p.spouse_has_savings is False:
        return Range(0, 0)
    if p.spouse_savings_join_date is not None:
        v = spouse_bonus(p.spouse_savings_join_date, as_of)
        return Range(v, v)
    lo = spouse_bonus(as_of, as_of) if p.spouse_has_savings else 0
    return Range(lo, spouse_bonus(_earliest(as_of), as_of))


def _savings_range(p: Profile, as_of: date) -> Range:
    own = []
    for b in _births(p, as_of):
        joins = [p.savings_join_date] if p.savings_join_date is not None else [b, as_of]
        own += [_savings_own_points(j, b, as_of) for j in joins]
    bonus = _spouse_bonus_range(p, as_of)
    return Range(min(SAVINGS_MAX, min(own) + bonus.lo), min(SAVINGS_MAX, max(own) + bonus.hi))


# ── 판정용 값 ────────────────────────────────────────────────────────────


def _homeless_values(p: Profile, as_of: date) -> tuple[Value, Value]:
    if p.homeless_now is False:
        why = Value(None, "세대원이 주택을 소유해 무주택기간이 없다 (FAQ 154)")
        return why, why
    marriage_known = p.marriage_date is not None or p.ever_married is False
    owned_known = p.ever_owned is not None and (not p.ever_owned or p.homeless_since is not None)
    if p.birth_date is None or not marriage_known or not owned_known:
        why = Value(None, "입력 부족 — 생년월일·혼인신고일·소유 이력이 있어야 기산일이 정해진다")
        return why, why
    b30 = add_years(p.birth_date, 30)
    base = min(b30, p.marriage_date) if p.marriage_date else b30
    start = homeless_start(p.birth_date, p.marriage_date, p.ever_owned, p.homeless_since)
    if start != base:
        reason = "소유 이력이 있어 무주택자가 된 날부터 (만 30세·혼인신고일보다 늦다)"
    elif base != b30:
        reason = "만 30세 전에 혼인해 혼인신고일부터"
    else:
        reason = "만 30세 되는 날부터 (생일 당일부터 30세로 본다)"
    note = " · 기산일이 공고일 뒤라 무주택기간이 아직 시작되지 않았다 (설계 §6-1)"
    ongoing = start <= as_of
    return (
        Value(start, f"별표1 1호가목3 (FAQ 153·156): {reason}"),
        Value(
            period(start, as_of),
            "별표1 1호가목: 기산일부터 공고일까지, 기산일 당일을 1일로 센다 (FAQ 170)"
            + ("" if ongoing else note),
        ),
    )


def _values(p: Profile, as_of: date) -> dict[str, Value]:
    start, length = _homeless_values(p, as_of)
    lo, hi = _dependents_count(p)
    dep = (
        "별표1 1호나목: 배우자 + 미혼 자녀 + 30세 이상 1년 직계비속"
        " + 직계존속(세대주이고 소유자 없을 때만)"
    )
    if p.birth_date is not None and p.savings_join_date is not None:
        s = savings_start(p.savings_join_date, p.birth_date)
        cap = (
            ""
            if s == p.savings_join_date
            else f" · 제10조⑥ 적용: 미성년 기간 상한으로 인정 시작일 {s}"
        )
        sav = Value(
            period(s, as_of),
            "별표1 1호다목: 최초 가입일부터 공고일까지, 가입일 당일을 1일로 센다" + cap,
        )
    else:
        sav = Value(None, "입력 부족 — 생년월일과 통장 가입일이 있어야 한다")
    bonus = _spouse_bonus_range(p, as_of)
    bonus_basis = (
        "별표1 비고2 (FAQ 170): 배우자 통장 가입기간의 50%에 ③ 점수표를 적용해 3점까지."
        " 배우자 통장은 가입일 그대로 센다(제10조⑥ 미적용, 설계 §6-4)"
    )
    age = (
        Value(age_on(p.birth_date, as_of), "공고일 현재 만 나이 (생일 당일부터 한 살 더 센다)")
        if p.birth_date
        else Value(None, "입력 부족 — 생년월일")
    )
    return {
        "age": age,
        "homeless_start": start,
        "homeless_period": length,
        "dependents": Value(lo if lo == hi else None, dep + ("" if lo == hi else " (입력 부족)")),
        "savings_period": sav,
        "spouse_bonus": Value(bonus.lo if bonus.exact else None, bonus_basis),
    }


def score(p: Profile, as_of: date) -> ProfileScore:
    """프로필을 공고일(`as_of`) 기준 가점으로 바꾼다. 모르는 칸이 있으면 항목마다 범위를 낸다."""
    p = _resolve(p, as_of)
    h, d, s = _homeless_range(p, as_of), _dependents_range(p), _savings_range(p, as_of)
    total = Range(h.lo + d.lo + s.lo, h.hi + d.hi + s.hi)
    return ProfileScore(as_of, _values(p, as_of), h, d, s, total, _missing(p))
