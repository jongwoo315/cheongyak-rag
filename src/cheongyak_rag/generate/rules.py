"""프로필 칸 값과 DB 공고 값만으로 하위 질의를 INELIGIBLE로 정하는 규칙 (#82).

규칙은 라벨 규칙(`docs/75-label-rules.md` §4)의 INELIGIBLE 줄을 같은 번호로 옮긴 것이다.
`judge_one`이 LLM 판정 뒤에 부르고, 결손 분석(`questions.py`)이 규칙이 보는 칸을 이 표에서 읽는다.
옮기지 않은 규칙은 둘이다: `referral-1`(공고문의 도시재생 부지제공자 표시)과 `newlywed-3`
(공고문의 예비신혼부부·한부모 갈래). 둘 다 DB에 없는 공고문 사실이 필요하다.
LLM·네트워크·DB를 부르지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import aggregate
from cheongyak_rag.retrieval import axes

# 특별공급 입주자저축 요건(제48조)과 혼인·나이 한도는 공고와 상관없는 고정값이다
SPECIAL_SAVINGS_MONTHS = 6
NEWLYWED_YEARS = 7
YOUTH_AGE = (19, 39)
# 1순위 가입 기간(개월): 투기과열지구·청약과열지역 24, 공급지역이 서울·경기·인천이면 12, 그 밖은 6
MONTHS_REGULATED, MONTHS_METRO, MONTHS_OTHER = 24, 12, 6
METRO_AREAS = ("서울", "경기", "인천")
REGULATION_COLUMNS = ("speclt_rdn_earth_at", "mdat_trget_area_secd")


def first_rank_months(facts: axes.Facts) -> int:
    """이 공고의 1순위 통장 가입 기간(개월). 시·도지사가 늘려 공고한 값은 DB에 없어 못 읽는다."""
    if any(facts.flags.get(c) for c in REGULATION_COLUMNS):
        return MONTHS_REGULATED
    if facts.area and facts.area.startswith(METRO_AREAS):
        return MONTHS_METRO
    return MONTHS_OTHER


@dataclass(frozen=True)
class Ctx:
    as_of: date
    first_rank: int  # 1순위 가입 기간(개월)


Check = Callable[[dict, Ctx], str | None]  # 걸리면 이유 한 문장, 아니면 None


@dataclass(frozen=True)
class Rule:
    id: str
    axis: str
    type: str | None  # `special_type` 축의 유형 이름. 다른 축은 None
    fields: tuple[str, ...]  # 규칙이 보는 프로필 칸
    when: str  # 사람이 읽는 조건(`docs/concepts.md`가 옮긴다)
    check: Check
    # 다른 칸의 답으로 이 규칙이 더 걸릴 수 없게 됐으면 False. 그 규칙의 빈 칸은 물을 이유가 없다
    possible: Callable[[dict], bool] = lambda p: True  # noqa: E731


def _date(p: dict, name: str) -> date | None:
    v = p.get(name)
    return date.fromisoformat(v) if isinstance(v, str) else v


def _is(name: str, value, why: str) -> Check:
    """칸이 `value`와 같으면 걸린다. 빈 칸(None)은 안 걸린다. `False`·`0`은 답한 값이다."""

    def check(p: dict, c: Ctx) -> str | None:
        v = p.get(name)
        return f"{name}이 {str(v).lower()}라 {why}" if v is not None and v == value else None

    return check


def _savings_short(months: Callable[[Ctx], int], why: str) -> Check:
    """가입일 + N개월이 공고일 뒤면 걸린다. 같은 날이면 지났다."""

    def check(p: dict, c: Ctx) -> str | None:
        join = _date(p, "savings_join_date")
        n = months(c)
        if join is None or prof.add_months(join, n) <= c.as_of:
            return None
        return f"청약통장 가입일 {join}부터 {n}개월이 공고일 {c.as_of}까지 안 지나 {why}"

    return check


def _newlywed_over(p: dict, c: Ctx) -> str | None:
    marriage = _date(p, "marriage_date")
    if p.get("married") is not True or marriage is None:
        return None
    if prof.add_years(marriage, NEWLYWED_YEARS) >= c.as_of:
        return None
    return f"혼인신고일 {marriage}부터 공고일 {c.as_of}까지 혼인기간이 {NEWLYWED_YEARS}년을 넘는다"


def _youth_age(p: dict, c: Ctx) -> str | None:
    birth = _date(p, "birth_date")
    if birth is None:
        return None
    age = prof.age_on(birth, c.as_of)
    lo, hi = YOUTH_AGE
    if lo <= age <= hi:
        return None
    return f"공고일 만 나이가 {age}세라 청년 특별공급의 {lo}세 이상 {hi}세 이하에 안 든다"


_HOMELESS = ("homeless_now", False, "무주택세대구성원이 아니다")
_SPECIAL_6M = _savings_short(
    lambda c: SPECIAL_SAVINGS_MONTHS, "특별공급 입주자저축 요건(6개월)을 못 채운다"
)
_FIRST_RANK = _savings_short(lambda c: c.first_rank, "1순위 가입 기간을 못 채운다")
_ST = "special_type"

# 규칙 표. 한 하위 질의에 규칙이 여럿 맞으면 위에서부터 처음 맞는 것이다
# (`docs/75-label-rules.md` §4)
RULES: tuple[Rule, ...] = (
    Rule("homeless-1", "homeless", None, ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("account-1", "account", None, ("savings_join_date",),
         "savings_join_date가 있고 1순위 가입 기간 N개월이 안 지났다", _FIRST_RANK),
    Rule("householder-1", "householder", None, ("is_household_head",), "is_household_head = false",
         _is("is_household_head", False, "세대주가 아니다")),
    Rule("multichild-1", _ST, "다자녀가구", ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("multichild-2", _ST, "다자녀가구", ("children_unmarried",), "children_unmarried = 0",
         _is("children_unmarried", 0, "미혼 자녀가 없다")),
    Rule("multichild-3", _ST, "다자녀가구", ("savings_join_date",),
         "savings_join_date가 있고 6개월이 안 지났다", _SPECIAL_6M),
    Rule("newlywed-1", _ST, "신혼부부", ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("newlywed-2", _ST, "신혼부부", ("married", "marriage_date"),
         "married = true이고 marriage_date가 있고 혼인기간 7년 초과", _newlywed_over,
         lambda p: p.get("married") is not False),
    Rule("newlywed-4", _ST, "신혼부부", ("savings_join_date",),
         "savings_join_date가 있고 6개월이 안 지났다", _SPECIAL_6M),
    Rule("firsttime-1", _ST, "생애최초", ("ever_owned",), "ever_owned = true",
         _is("ever_owned", True, "과거에 주택을 소유한 적이 있다")),
    Rule("firsttime-2", _ST, "생애최초", ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("firsttime-3", _ST, "생애최초", ("savings_join_date",),
         "savings_join_date가 있고 1순위 가입 기간 N개월이 안 지났다", _FIRST_RANK),
    Rule("elderly-1", _ST, "노부모 부양", ("ascendants_3y",), "ascendants_3y = 0",
         _is("ascendants_3y", 0, "3년 이상 부양한 직계존속이 없다")),
    Rule("elderly-2", _ST, "노부모 부양", ("is_household_head",), "is_household_head = false",
         _is("is_household_head", False, "세대주가 아니다")),
    Rule("elderly-3", _ST, "노부모 부양", ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("elderly-4", _ST, "노부모 부양", ("ascendants_any_owner",), "ascendants_any_owner = true",
         _is("ascendants_any_owner", True, "부양하는 직계존속이 주택을 소유해 무주택이 아니다")),
    Rule("elderly-5", _ST, "노부모 부양", ("savings_join_date",),
         "savings_join_date가 있고 1순위 가입 기간 N개월이 안 지났다", _FIRST_RANK),
    Rule("newborn-1", _ST, "신생아", ("homeless_now",), "homeless_now = false",
         _is(*_HOMELESS)),
    Rule("newborn-2", _ST, "신생아", ("savings_join_date",),
         "savings_join_date가 있고 1순위 가입 기간 N개월이 안 지났다", _FIRST_RANK),
    Rule("youth-1", _ST, "청년", ("ever_owned",), "ever_owned = true",
         _is("ever_owned", True, "과거에 주택을 소유한 적이 있다")),
    Rule("youth-2", _ST, "청년", ("married",), "married = true",
         _is("married", True, "혼인 중이다")),
    Rule("youth-3", _ST, "청년", ("birth_date",),
         "birth_date가 있고 만 나이가 19세 미만 또는 39세 초과", _youth_age),
    Rule("youth-4", _ST, "청년", ("savings_join_date",),
         "savings_join_date가 있고 6개월이 안 지났다", _SPECIAL_6M),
)  # fmt: skip


def _type_of(axis: str, query: str) -> str | None:
    """`special_type` 하위 질의의 유형 이름. 다른 축은 None. 집계가 쓰는 표를 그대로 쓴다."""
    return aggregate._TYPE_BY_QUERY.get(query, query) if axis == "special_type" else None


def _rules_for(axis: str, query: str) -> list[Rule]:
    t = _type_of(axis, query)
    return [r for r in RULES if r.axis == axis and r.type == t]


def profile_fields(axis: str, query: str, profile: dict | None = None) -> list[str]:
    """이 하위 질의에 걸리는 규칙이 보는 프로필 칸. 규칙 표 순서이고 같은 칸은 한 번만 적는다.

    `profile`을 주면 그 답으로 더 걸릴 수 없는 규칙(`possible`이 False)의 칸은 뺀다.
    """
    live = [r for r in _rules_for(axis, query) if profile is None or r.possible(profile)]
    return list(dict.fromkeys(f for r in live for f in r.fields))


def rule_ineligible(
    axis: str, query: str, profile: dict, facts: axes.Facts, as_of: date
) -> tuple[str, str] | None:
    """하위 질의가 프로필·공고 값만으로 INELIGIBLE이면 (규칙 번호, 이유 한 문장), 아니면 None.

    `profile`은 `Profile.to_dict()` 꼴이다. 빈 칸(None)은 모르는 값이라 규칙이 안 걸린다.
    """
    ctx = Ctx(as_of, first_rank_months(facts))
    for rule in _rules_for(axis, query):
        why = rule.check(profile, ctx)
        if why:
            return rule.id, why
    return None
