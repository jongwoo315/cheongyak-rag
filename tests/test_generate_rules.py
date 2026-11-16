from datetime import date, timedelta

import pytest

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import rules
from cheongyak_rag.retrieval import axes

AS_OF = date(2026, 9, 10)
Q_TYPE = axes.Q_SPECIAL.format


def _facts(area="부산", *, speclt=False, mdat=False, dtl="01"):
    flags = dict.fromkeys((c for c, _ in axes.REGULATION_FLAGS), False)
    flags["speclt_rdn_earth_at"], flags["mdat_trget_area_secd"] = speclt, mdat
    return axes.Facts(area, flags, 10, {k: 0 for k, _ in axes.SPECIAL_TYPES}, "286965", dtl)


def _hit(axis, query, profile, facts=None, as_of=AS_OF):
    return rules.rule_ineligible(axis, query, profile, facts or _facts(), as_of)


def _rule(axis, query, profile, **kw):
    got = _hit(axis, query, profile, **kw)
    return got[0] if got else None


Q_H, Q_A, Q_HH = axes.Q_HOMELESS, axes.Q_ACCOUNT, axes.Q_HOUSEHOLDER

ST = "special_type"
MC, NW, FT = Q_TYPE(type="다자녀가구"), Q_TYPE(type="신혼부부"), Q_TYPE(type="생애최초")
EL, NB, YT = Q_TYPE(type="노부모 부양"), Q_TYPE(type="신생아"), Q_TYPE(type="청년")
HL = ({"homeless_now": False}, {"homeless_now": True})
HEAD = ({"is_household_head": False}, {"is_household_head": True})
OWN = ({"ever_owned": True}, {"ever_owned": False})


def MARRIED(day):
    return {"married": True, "marriage_date": day}


# (규칙 번호, 축, 질의, 걸리는 프로필, 바로 옆 안 걸리는 프로필)
CASES = [
    ("homeless-1", "homeless", Q_H, *HL),
    ("householder-1", "householder", Q_HH, *HEAD),
    ("multichild-1", ST, MC, *HL),
    ("multichild-2", ST, MC, {"children_unmarried": 0}, {"children_unmarried": 1}),
    ("newlywed-1", ST, NW, *HL),
    ("newlywed-2", ST, NW, MARRIED("2019-09-09"), MARRIED("2019-09-10")),
    ("firsttime-1", ST, FT, *OWN),
    ("firsttime-2", ST, FT, *HL),
    ("elderly-1", ST, EL, {"ascendants_3y": 0}, {"ascendants_3y": 1}),
    ("elderly-2", ST, EL, *HEAD),
    ("elderly-3", ST, EL, *HL),
    ("elderly-4", ST, EL, {"ascendants_any_owner": True}, {"ascendants_any_owner": False}),
    ("newborn-1", ST, NB, *HL),
    ("youth-1", ST, YT, *OWN),
    ("youth-2", ST, YT, {"married": True}, {"married": False}),
    ("youth-3", ST, YT, {"birth_date": "1986-09-10"}, {"birth_date": "1986-09-11"}),  # 만 40 / 39
    ("youth-3", ST, YT, {"birth_date": "2007-09-11"}, {"birth_date": "2007-09-10"}),  # 만 18 / 19
]


@pytest.mark.parametrize("rule_id,axis,query,hit,miss", CASES)
def test_rule_fires_on_its_case_and_not_on_the_next_one(rule_id, axis, query, hit, miss):
    assert _rule(axis, query, hit) == rule_id
    assert _rule(axis, query, miss) is None


def test_reason_is_one_sentence_naming_the_value():
    rule, reason = _hit("homeless", Q_H, {"homeless_now": False})
    assert rule == "homeless-1"
    assert "homeless_now" in reason and "\n" not in reason


def test_empty_profile_fires_nothing():
    every = [(a, q) for _, a, q, _, _ in CASES] + [("account", Q_A)]
    assert all(_hit(a, q, {}) is None for a, q in every)
    assert all(_hit(a, q, dict.fromkeys(rules.profile_fields(a, q))) is None for a, q in every)


def test_referral_is_never_ruled_out_even_when_homeless_now_is_false():
    q = Q_TYPE(type="기관추천")
    assert _hit("special_type", q, {"homeless_now": False, "ever_owned": True}) is None


def test_relocated_and_the_other_axes_have_no_rule():
    p = {"homeless_now": False, "is_household_head": False, "savings_join_date": "2026-09-01"}
    for axis, q in (
        ("residence", axes.Q_RESIDENCE_NO_AREA),
        ("income_asset", axes.Q_INCOME_ASSET),
        ("rewin", axes.Q_REWIN),
        ("special_type", Q_TYPE(type="이전기관 종사자")),
    ):
        assert _hit(axis, q, p) is None


def test_rule_of_another_axis_does_not_fire():
    assert _hit("account", Q_A, {"homeless_now": False}) is None
    assert _hit("homeless", Q_H, {"is_household_head": False}) is None


def test_first_matching_rule_in_table_order_wins():
    both = {"homeless_now": False, "children_unmarried": 0}
    assert _rule("special_type", Q_TYPE(type="다자녀가구"), both) == "multichild-1"


# ── 1순위 가입 기간 N ────────────────────────────────────────────────────


def test_first_rank_months_by_regulation_then_metro_then_the_rest():
    assert rules.first_rank_months(_facts("부산", speclt=True)) == 24
    assert rules.first_rank_months(_facts("부산", mdat=True)) == 24
    assert rules.first_rank_months(_facts("서울")) == 12
    assert rules.first_rank_months(_facts("경기")) == 12
    assert rules.first_rank_months(_facts("인천")) == 12
    assert rules.first_rank_months(_facts("부산")) == 6
    assert rules.first_rank_months(_facts(None)) == 6
    assert rules.first_rank_months(_facts("서울", speclt=True)) == 24


# 가입일 + N개월이 as_of 이전이거나 같은 날이면 지났다 → 안 걸린다
@pytest.mark.parametrize(
    "facts,rule_id,axis,query",
    [
        (_facts("부산", speclt=True), "account-1", "account", Q_A),
        (_facts("서울"), "account-1", "account", Q_A),
        (_facts("부산"), "account-1", "account", Q_A),
        (_facts("서울"), "firsttime-3", "special_type", Q_TYPE(type="생애최초")),
        (_facts("서울"), "elderly-5", "special_type", Q_TYPE(type="노부모 부양")),
        (_facts("서울"), "newborn-2", "special_type", Q_TYPE(type="신생아")),
    ],
)
def test_first_rank_boundary_follows_n_for_the_four_rules(facts, rule_id, axis, query):
    edge = prof.add_months(AS_OF, -rules.first_rank_months(facts))  # 가입일 + N개월 = as_of
    day_after = edge + timedelta(days=1)
    assert _rule(axis, query, {"savings_join_date": edge.isoformat()}, facts=facts) is None
    assert _rule(axis, query, {"savings_join_date": day_after.isoformat()}, facts=facts) == rule_id


def test_the_three_n_values_are_24_12_6():
    for facts, n in ((_facts("부산", speclt=True), 24), (_facts("서울"), 12), (_facts("부산"), 6)):
        assert rules.first_rank_months(facts) == n


@pytest.mark.parametrize(
    "type_,rule_id",
    [("다자녀가구", "multichild-3"), ("신혼부부", "newlywed-4"), ("청년", "youth-4")],
)
def test_special_supply_savings_rule_is_always_six_months(type_, rule_id):
    facts = _facts("부산", speclt=True)  # N=24라도 6개월이다
    q = Q_TYPE(type=type_)
    assert _rule("special_type", q, {"savings_join_date": "2026-03-10"}, facts=facts) is None
    assert _rule("special_type", q, {"savings_join_date": "2026-03-11"}, facts=facts) == rule_id


def test_newlywed_seven_year_limit_is_inclusive_of_the_same_day():
    q = Q_TYPE(type="신혼부부")
    same = {"married": True, "marriage_date": "2019-09-10"}
    over = {"married": True, "marriage_date": "2019-09-09"}
    assert _rule("special_type", q, same) is None
    assert _rule("special_type", q, over) == "newlywed-2"
    # married가 false이거나 비었으면 걸리지 않는다
    # (newlywed-3은 민영 공고에서만 걸리므로 이 줄은 국민주택 공고로 본다)
    f03 = _facts(dtl="03")
    assert (
        _rule("special_type", q, {"married": False, "marriage_date": "2019-09-09"}, facts=f03)
        is None
    )
    assert _rule("special_type", q, {"marriage_date": "2019-09-09"}, facts=f03) is None


def test_referral_1_is_not_ported():
    assert "referral-1" not in {r.id for r in rules.RULES}


# ── newlywed-3: 민영(01) 공고에서 혼인 중이 아니면 신혼부부 특별공급 INELIGIBLE ───────────


def test_newlywed_3_fires_only_on_private_housing_notice_with_married_false():
    q = Q_TYPE(type="신혼부부")
    single = {"married": False}
    assert _rule("special_type", q, single, facts=_facts(dtl="01")) == "newlywed-3"
    assert _rule("special_type", q, single, facts=_facts(dtl="03")) is None
    assert _rule("special_type", q, single, facts=_facts(dtl=None)) is None
    assert _rule("special_type", q, single, facts=_facts(dtl="02")) is None


def test_newlywed_3_does_not_fire_when_married_is_empty_or_true():
    q = Q_TYPE(type="신혼부부")
    assert _rule("special_type", q, {}, facts=_facts(dtl="01")) is None
    assert _rule("special_type", q, {"married": None}, facts=_facts(dtl="01")) is None
    assert _rule("special_type", q, {"married": True}, facts=_facts(dtl="01")) is None


def test_newlywed_3_reason_names_the_cause_and_article():
    _, why = _hit("special_type", Q_TYPE(type="신혼부부"), {"married": False})
    assert "민영주택" in why and "제41조" in why and "\n" not in why


def test_newlywed_3_sits_between_newlywed_2_and_newlywed_4_and_loses_to_newlywed_1():
    ids = [r.id for r in rules.RULES if r.type == "신혼부부"]
    assert ids == ["newlywed-1", "newlywed-2", "newlywed-3", "newlywed-4"]
    q = Q_TYPE(type="신혼부부")
    both = {"married": False, "homeless_now": False}
    assert _rule("special_type", q, both) == "newlywed-1"


def test_newlywed_3_is_not_ported_for_other_special_types():
    for t in ("청년", "생애최초", "신생아"):
        assert _rule("special_type", Q_TYPE(type=t), {"married": False}) != "newlywed-3"


def test_rule_ids_are_exactly_the_ported_list():
    want = {
        "homeless-1", "account-1", "householder-1",
        "multichild-1", "multichild-2", "multichild-3",
        "newlywed-1", "newlywed-2", "newlywed-3", "newlywed-4",
        "firsttime-1", "firsttime-2", "firsttime-3",
        "elderly-1", "elderly-2", "elderly-3", "elderly-4", "elderly-5",
        "newborn-1", "newborn-2",
        "youth-1", "youth-2", "youth-3", "youth-4",
    }  # fmt: skip
    assert [r.id for r in rules.RULES] and {r.id for r in rules.RULES} == want
    assert len(rules.RULES) == len(want)


# ── 규칙이 보는 칸 ───────────────────────────────────────────────────────


def test_profile_fields_are_read_from_the_rule_table():
    assert rules.profile_fields("homeless", Q_H) == ["homeless_now"]
    assert rules.profile_fields("account", Q_A) == ["savings_join_date"]
    assert rules.profile_fields("residence", axes.Q_RESIDENCE_NO_AREA) == []
    multichild = rules.profile_fields("special_type", Q_TYPE(type="다자녀가구"))
    assert multichild == ["homeless_now", "children_unmarried", "savings_join_date"]
    youth = rules.profile_fields("special_type", Q_TYPE(type="청년"))
    assert youth == ["ever_owned", "married", "birth_date", "savings_join_date"]
    assert rules.profile_fields("special_type", Q_TYPE(type="기관추천")) == []


# ── 프로필 가능 규칙 (#180) ──────────────────────────────────────────────

ELIGIBLE_CASES = [
    ("homeless-2", "homeless", Q_H, "homeless_now"),
    ("householder-2", "householder", Q_HH, "is_household_head"),
]


@pytest.mark.parametrize(("rule_id", "axis", "query", "field"), ELIGIBLE_CASES)
def test_eligible_rule_fires_only_when_the_field_is_true(rule_id, axis, query, field):
    got = rules.rule_eligible(axis, query, {field: True})
    assert got is not None and got[0] == rule_id
    assert rules.rule_eligible(axis, query, {field: False}) is None
    assert rules.rule_eligible(axis, query, {field: None}) is None
    assert rules.rule_eligible(axis, query, {}) is None  # 비어 있으면 모르는 값이다


def test_eligible_rule_reasons_are_the_design_sentences():
    assert rules.rule_eligible("homeless", Q_H, {"homeless_now": True}) == (
        "homeless-2",
        "프로필에서 지금 무주택(`homeless_now`=true)이라 무주택세대구성원 요건을 채운다(제53조)",
    )
    assert rules.rule_eligible("householder", Q_HH, {"is_household_head": True}) == (
        "householder-2",
        "프로필에서 세대주(`is_household_head`=true)라 세대주 요건을 채운다(제2조제3호)",
    )


@pytest.mark.parametrize(
    ("axis", "query"),
    [
        ("account", Q_A),
        ("residence", "거주 질의"),
        ("special_type", MC),
        ("special_type", NW),
    ],
)
def test_eligible_rule_ignores_other_axes(axis, query):
    full = {"homeless_now": True, "is_household_head": True}
    assert rules.rule_eligible(axis, query, full) is None


def test_eligible_rule_does_not_fire_together_with_the_ineligible_rule():
    for field, axis, query in (
        ("homeless_now", "homeless", Q_H),
        ("is_household_head", "householder", Q_HH),
    ):
        for value in (True, False, None):
            p = {field: value}
            both = rules.rule_eligible(axis, query, p) and _hit(axis, query, p)
            assert not both


def test_eligible_fields_lists_the_fields_a_possible_rule_reads():
    assert rules.eligible_fields("homeless", Q_H) == ["homeless_now"]
    assert rules.eligible_fields("householder", Q_HH) == ["is_household_head"]
    assert rules.eligible_fields("account", Q_A) == []
    assert rules.eligible_fields("special_type", NW) == []
