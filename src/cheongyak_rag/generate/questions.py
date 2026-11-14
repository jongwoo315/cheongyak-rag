"""결손 분석(B1b)과 질문 순서(B9b) (#82).

하위 질의마다 판정에 필요한데 없는 정보(`info`)와 프로필 불가 규칙이 보는 빈 칸
(`can_rule_out`)을 낸다(`analyze`). 판정과 집계가 끝난 뒤에는 신청할 수 없는 경로를 빼고 남은
NEED_INFO 하위 질의의 정보를 한 질문으로 합쳐 순서를 정한다(`build_questions`).
LLM·네트워크·DB를 부르지 않는다. 정의는 `docs/plans/82-1114-design-missing-info.md` §2.2·§2.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cheongyak_rag.generate import aggregate, rules
from cheongyak_rag.retrieval import axes

if TYPE_CHECKING:
    from cheongyak_rag.generate import verdict as vd

# 정보 이름 17개. 라벨 규칙(`docs/75-label-rules.md`) `need` 칸의 이름 그대로다.
# (이름, 한국어 문장, 프로필에 칸이 있는지). 표 순서가 질문 순서의 마지막 기준이다
INFO: tuple[tuple[str, str, bool], ...] = (
    ("homeless_now", "지금 무주택세대구성원인가요?", True),
    ("savings_join_date", "청약통장 가입일이 언제인가요?", True),
    ("is_household_head", "세대주인가요?", True),
    ("deposit_amount", "청약통장 예치금이 얼마인가요?", False),
    ("payment_count", "청약통장 납입 횟수와 금액이 어떻게 되나요?", False),
    ("household_income", "세대의 월평균 소득이 얼마인가요?", False),
    ("real_estate_value", "보유한 부동산 자산 가액이 얼마인가요?", False),
    ("residence_area", "어느 지역에 거주하나요?", False),
    ("residence_period", "그 지역에 얼마나 거주했나요?", False),
    ("referral_status", "기관 추천 대상인가요?", False),
    ("child_age", "자녀의 나이(출생 시점)가 어떻게 되나요?", False),
    ("minor_children_count", "미성년 자녀가 몇 명인가요? (태아·입양 포함)", False),
    ("winning_history", "과거 당첨 이력이 있나요?", False),
    ("ascendant_age", "부양하는 직계존속이 몇 세인가요?", False),
    ("income_tax_years", "소득세를 낸 기간이 몇 년인가요?", False),
    ("employer_status", "이전기관 종사자인가요?", False),
    ("marriage_status", "혼인 상태(예비신혼부부·한부모 여부)가 어떻게 되나요?", False),
)
# 정답 라벨 `need`에는 없지만 프로필 불가 규칙이 보는 프로필 칸.
# 불가 판정을 낼 수 있는 빈 칸으로만 나온다
RULE_ONLY: tuple[tuple[str, str], ...] = (
    ("ever_owned", "과거에 주택을 소유한 적이 있나요?"),
    ("married", "지금 배우자가 있나요?"),
    ("marriage_date", "최초 혼인신고일이 언제인가요?"),
    ("children_unmarried", "미혼 자녀가 몇 명인가요?"),
    ("ascendants_3y", "3년 넘게 부양한 직계존속이 몇 명인가요?"),
    ("ascendants_any_owner", "부양하는 직계존속 중 주택을 소유한 사람이 있나요?"),
    ("birth_date", "생년월일이 언제인가요?"),
)
INFO_NAMES = tuple(n for n, _, _ in INFO)
TEXT = {n: t for n, t, _ in INFO} | dict(RULE_ONLY)
HAS_FIELD = {n: has for n, _, has in INFO} | {n: True for n, _ in RULE_ONLY}
ORDER = [*INFO_NAMES, *(n for n, _ in RULE_ONLY)]

# 특별공급 유형별로 규칙에 안 걸렸을 때 더 필요한 정보 (라벨 규칙 §4.7 「그 밖」 줄)
TYPE_INFO = {
    "다자녀가구": ("minor_children_count",),
    "신혼부부": ("household_income", "real_estate_value"),
    "생애최초": ("household_income", "real_estate_value", "income_tax_years", "deposit_amount"),
    "노부모 부양": ("ascendant_age", "deposit_amount"),
    "신생아": ("child_age", "household_income", "deposit_amount"),
    "기관추천": ("referral_status",),
    "청년": ("household_income", "deposit_amount"),
    "이전기관 종사자": ("employer_status",),
}
AXIS_INFO = {
    "residence": ("residence_area", "residence_period"),
    "income_asset": ("household_income", "real_estate_value"),
    "rewin": ("winning_history",),
}


@dataclass
class Missing:
    info: list[str]  # 판정하는 데 필요한데 없는 정보
    can_rule_out: list[
        str
    ]  # 규칙이 보는 프로필 칸 중 비어 있는 것. 채우면 INELIGIBLE이 정해질 수 있다


def _empty(profile: dict, name: str) -> bool:
    return profile.get(name) is None


def _info(axis: str, query: str, profile: dict, facts: axes.Facts) -> list[str]:
    if axis == "homeless":
        return ["homeless_now"] if _empty(profile, "homeless_now") else []
    if axis == "householder":
        return ["is_household_head"] if _empty(profile, "is_household_head") else []
    if axis == "account":
        # 예치금(민영)·납입 횟수(국민)는 프로필에 칸이 없어 가입일이 있어도 필요하다
        pay = {"01": ["deposit_amount"], "03": ["payment_count"]}
        out = ["savings_join_date"] if _empty(profile, "savings_join_date") else []
        return out + pay.get(facts.house_dtl_secd, ["deposit_amount", "payment_count"])
    if axis == "special_type":
        t = aggregate._TYPE_BY_QUERY.get(query, query)
        extra = ["marriage_status"] if t == "신혼부부" and profile.get("married") is False else []
        return [*TYPE_INFO.get(t, ()), *extra]
    return list(AXIS_INFO.get(axis, ()))


def analyze(axis: str, query: str, profile: dict, facts: axes.Facts) -> Missing:
    """하위 질의 하나의 없는 정보와 불가 판정을 낼 수 있는 빈 칸. 판정 결과와 상관없이 정한다.

    `profile`은 `Profile.to_dict()` 꼴이고 `None`이 빈 칸이다.
    """
    out = [f for f in rules.profile_fields(axis, query) if _empty(profile, f)]
    return Missing(_info(axis, query, profile, facts), out)


@dataclass
class Question:
    name: str  # 정보 이름
    text: str  # 한국어 문장
    has_field: bool  # 프로필에 입력 칸이 있는지
    can_rule_out: bool  # 답이 INELIGIBLE이면 그 하위 질의가 정해지는 칸인지
    axes: list[str] = field(default_factory=list)  # 쓰이는 축 id
    routes: list[str] = field(default_factory=list)  # 쓰이는 경로 이름


def _route_keys(v: vd.Verdict, special: list[str]) -> list[str]:
    """하위 질의가 합쳐지는 경로 키. `aggregate.aggregate`가 합치는 방식과 같다."""
    if v.axis in aggregate.GENERAL_AXES:
        return [aggregate.GENERAL_KEY, *special]
    if v.axis == aggregate.INCOME_AXIS:
        return list(special)
    if v.axis == aggregate.TYPE_AXIS:
        return [aggregate._TYPE_BY_QUERY.get(v.query, v.query)]
    return []


def build_questions(
    plans: list[axes.AxisPlan], verdicts: list[vd.Verdict], profile: dict, facts: axes.Facts
) -> list[Question]:
    """판정과 집계가 끝난 응답의 질문 목록 (설계 §2.3). 순서가 곧 물을 차례다."""
    agg = aggregate.aggregate(plans, verdicts)
    routes = [agg.general, *agg.special]
    open_keys = [r.key for r in routes if r.verdict != "INELIGIBLE"]
    if not open_keys:  # 일반공급이 INELIGIBLE이면 모든 경로가 닫힌다
        return []
    names = {r.key: r.name for r in routes}
    on = {p.id for p in plans if p.on}
    special = [r.key for r in agg.special]
    found: dict[str, dict] = {}
    for v in verdicts:
        if (
            v.axis not in on or v.verdict != "NEED_INFO"
        ):  # UNVERIFIABLE은 근거를 못 찾은 것이라 안 묻는다
            continue
        keys = [k for k in _route_keys(v, special) if k in open_keys]
        if not keys:
            continue
        miss = analyze(v.axis, v.query, profile, facts)
        for name, rule in [(n, True) for n in miss.can_rule_out] + [(n, False) for n in miss.info]:
            q = found.setdefault(name, {"axes": [], "routes": set(), "rule": False})
            q["axes"] += [v.axis] if v.axis not in q["axes"] else []
            q["routes"] |= set(keys)
            q["rule"] |= rule
    ranked = sorted(
        found.items(),
        key=lambda kv: (
            not kv[1]["rule"],
            -len(kv[1]["routes"]),
            aggregate.GENERAL_KEY not in kv[1]["routes"],
            ORDER.index(kv[0]),
        ),
    )
    return [
        Question(
            name, TEXT[name], HAS_FIELD[name], q["rule"], q["axes"],
            [names[k] for k in open_keys if k in q["routes"]],
        )
        for name, q in ranked
    ]  # fmt: skip
