import json

import pytest

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import aggregate as agg
from cheongyak_rag.generate import questions as qs
from cheongyak_rag.generate import rules
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes

TYPE = axes.Q_SPECIAL.format
EMPTY = prof.Profile().to_dict()
GENERAL = ("homeless", "account", "residence", "rewin", "householder")


def _facts(secd="01", area="서울"):
    flags = dict.fromkeys((c for c, _ in axes.REGULATION_FLAGS), False)
    return axes.Facts(area, flags, 10, {k: 0 for k, _ in axes.SPECIAL_TYPES}, "286965", secd)


def _info(axis, query, profile=None, facts=None):
    return qs.analyze(axis, query, {**EMPTY, **(profile or {})}, facts or _facts())


Q = {
    "homeless": axes.Q_HOMELESS,
    "account": axes.Q_ACCOUNT,
    "residence": axes.Q_RESIDENCE_NO_AREA,
    "income_asset": axes.Q_INCOME_ASSET,
    "rewin": axes.Q_REWIN,
    "householder": axes.Q_HOUSEHOLDER,
}


# ── 정보 이름 표 ─────────────────────────────────────────────────────────


def test_info_table_is_the_17_label_rule_names():
    want = {"homeless_now", "savings_join_date", "deposit_amount", "payment_count",
            "household_income", "real_estate_value", "residence_area", "residence_period",
            "referral_status", "child_age", "minor_children_count", "winning_history",
            "ascendant_age", "income_tax_years", "is_household_head", "employer_status",
            "marriage_status"}  # fmt: skip
    assert len(qs.INFO_NAMES) == 17 and set(qs.INFO_NAMES) == want


def test_golden_need_names_are_all_in_the_table():
    golden = [json.loads(x) for x in open("runs/75/golden.jsonl", encoding="utf-8") if x.strip()]
    used = {n for r in golden for g in r["labels"] for n in g["need"]}
    assert used == set(qs.INFO_NAMES)


def test_only_homeless_now_savings_join_date_and_household_head_have_a_profile_field():
    assert {n for n in qs.INFO_NAMES if qs.HAS_FIELD[n]} == {
        "homeless_now", "savings_join_date", "is_household_head"
    }  # fmt: skip
    profile_cells = set(prof.Profile().to_dict())
    assert {n for n in qs.TEXT if qs.HAS_FIELD[n]} <= profile_cells


def test_every_rule_field_has_a_question_text():
    fields = {f for r in rules.RULES for f in r.fields}
    assert fields <= set(qs.TEXT) and fields <= set(prof.Profile().to_dict())


# ── 결손 분석: 축 7개 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "axis,info",
    [
        ("homeless", ["homeless_now"]),
        ("householder", ["is_household_head"]),
        ("residence", ["residence_area", "residence_period"]),
        ("income_asset", ["household_income", "real_estate_value"]),
        ("rewin", ["winning_history"]),
        ("account", ["savings_join_date", "deposit_amount"]),
    ],
)
def test_empty_profile_axis_info(axis, info):
    assert _info(axis, Q[axis]).info == info


def test_filled_profile_cells_are_not_missing():
    assert _info("homeless", Q["homeless"], {"homeless_now": False}).info == []
    assert _info("householder", Q["householder"], {"is_household_head": False}).info == []
    # residence · income · rewin은 프로필 칸이 없어 프로필이 꽉 차도 늘 없다
    full = {k: True for k in ("homeless_now", "is_household_head")}
    assert _info("residence", Q["residence"], full).info == ["residence_area", "residence_period"]
    assert _info("rewin", Q["rewin"], full).info == ["winning_history"]


# ── 청약통장 `01` · `03` · 모름 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "secd,money",
    [
        ("01", ["deposit_amount"]),
        ("03", ["payment_count"]),
        (None, ["deposit_amount", "payment_count"]),
    ],
)
def test_account_money_info_follows_the_house_type(secd, money):
    facts = _facts(secd)
    assert _info("account", Q["account"], facts=facts).info == ["savings_join_date", *money]
    got = _info("account", Q["account"], {"savings_join_date": "2025-01-01"}, facts)
    assert got.info == money  # 가입일이 있어도 예치금·납입은 없다


def test_account_rule_cell_is_savings_join_date():
    assert _info("account", Q["account"]).can_rule_out == ["savings_join_date"]
    assert _info("account", Q["account"], {"savings_join_date": "2025-01-01"}).can_rule_out == []


# ── 특별공급 유형 8개 ────────────────────────────────────────────────────

TYPE_CASES = {
    "다자녀가구": (
        ["minor_children_count"],
        ["homeless_now", "children_unmarried", "savings_join_date"],
    ),
    "신혼부부": (
        ["household_income", "real_estate_value"],
        ["homeless_now", "married", "marriage_date", "savings_join_date"],
    ),
    "생애최초": (
        ["household_income", "real_estate_value", "income_tax_years", "deposit_amount"],
        ["ever_owned", "homeless_now", "savings_join_date"],
    ),
    "노부모 부양": (
        ["ascendant_age", "deposit_amount"],
        ["ascendants_3y", "is_household_head", "homeless_now", "ascendants_any_owner",
         "savings_join_date"],
    ),
    "신생아": (
        ["child_age", "household_income", "deposit_amount"],
        ["homeless_now", "savings_join_date"],
    ),
    "기관추천": (["referral_status"], []),
    "청년": (
        ["household_income", "deposit_amount"],
        ["ever_owned", "married", "birth_date", "savings_join_date"],
    ),
    "이전기관 종사자": (["employer_status"], []),
}  # fmt: skip


def test_type_cases_cover_the_eight_special_types():
    assert set(TYPE_CASES) == {name for _, name in axes.SPECIAL_TYPES}


@pytest.mark.parametrize("type_", list(TYPE_CASES))
def test_special_type_info_and_rule_cells(type_):
    info, cells = TYPE_CASES[type_]
    got = _info("special_type", TYPE(type=type_))
    assert (got.info, got.can_rule_out) == (info, cells)


def test_newlywed_adds_marriage_status_only_when_married_is_false():
    q = TYPE(type="신혼부부")
    base = ["household_income", "real_estate_value"]
    assert _info("special_type", q, {"married": False}).info == [*base, "marriage_status"]
    assert _info("special_type", q, {"married": True}).info == base
    assert _info("special_type", q).info == base


def test_can_rule_out_lists_only_the_empty_cells():
    got = _info("special_type", TYPE(type="다자녀가구"), {"homeless_now": True})
    assert got.can_rule_out == ["children_unmarried", "savings_join_date"]
    done = {"homeless_now": True, "children_unmarried": 2, "savings_join_date": "2020-01-01"}
    assert _info("special_type", TYPE(type="다자녀가구"), done).can_rule_out == []


def test_unknown_type_has_nothing_to_ask():
    assert _info("special_type", axes.Q_SPECIAL_NO_TYPE).info == []


# ── 질문 ─────────────────────────────────────────────────────────────────


def _plans(*on):
    return [axes.AxisPlan(a.id, a.name, a.id in on, "") for a in axes.AXES]


def _v(axis, verdict, query=None):
    return vd.Verdict(axis, axis, query or Q.get(axis, axis), verdict=verdict)


def _special(type_, verdict):
    return _v("special_type", verdict, TYPE(type=type_))


def _ask(plans, verdicts, profile=None, facts=None):
    return qs.build_questions(plans, verdicts, {**EMPTY, **(profile or {})}, facts or _facts())


def _names(questions):
    return [q.name for q in questions]


def test_general_ineligible_closes_every_route_and_asks_nothing():
    verdicts = [_v("homeless", "INELIGIBLE"), _v("account", "NEED_INFO"),
                _special("신혼부부", "NEED_INFO")]  # fmt: skip
    assert _ask(_plans("homeless", "account", "special_type"), verdicts) == []


def test_ineligible_special_route_drops_its_own_questions():
    plans = _plans("homeless", "special_type")
    verdicts = [_v("homeless", "ELIGIBLE"), _special("신혼부부", "INELIGIBLE"),
                _special("기관추천", "NEED_INFO")]  # fmt: skip
    got = _ask(plans, verdicts)
    assert _names(got) == ["referral_status"]
    assert got[0].routes == ["특별공급 기관추천"]


def test_a_route_closed_by_another_axis_hides_the_questions_only_it_used():
    plans = _plans("homeless", "income_asset", "special_type")
    verdicts = [
        _v("homeless", "ELIGIBLE"),
        _v("income_asset", "NEED_INFO"),
        _special("신혼부부", "INELIGIBLE"),
        _special("기관추천", "ELIGIBLE"),
    ]
    got = _ask(plans, verdicts)
    # income_asset는 두 특별공급 경로에 들어가는데 신혼부부는 닫혔다 — 기관추천 경로에만 남는다
    assert _names(got) == ["household_income", "real_estate_value"]
    assert all(q.routes == ["특별공급 기관추천"] for q in got)


def test_same_info_on_two_routes_is_one_question_with_both_routes():
    plans = _plans("special_type")
    verdicts = [_special("신혼부부", "NEED_INFO"), _special("청년", "NEED_INFO")]
    got = {q.name: q for q in _ask(plans, verdicts)}
    assert list(got).count("household_income") == 1
    assert got["household_income"].routes == ["특별공급 신혼부부", "특별공급 청년"]
    assert got["household_income"].axes == ["special_type"]
    assert got["deposit_amount"].routes == ["특별공급 청년"]


def test_same_info_on_two_axes_lists_both_axes_and_the_general_route():
    plans = _plans("homeless", "householder")
    verdicts = [_v("homeless", "NEED_INFO"), _v("householder", "NEED_INFO")]
    got = _ask(plans, verdicts)
    assert _names(got) == ["homeless_now", "is_household_head"]
    assert got[0].routes == ["일반공급"] and got[0].axes == ["homeless"]


def test_rule_cells_come_before_missing_info():
    plans = _plans("homeless", "residence", "special_type")
    verdicts = [_v("homeless", "NEED_INFO"), _v("residence", "NEED_INFO"),
                _special("다자녀가구", "NEED_INFO")]  # fmt: skip
    got = _ask(plans, verdicts)
    flags = [q.can_rule_out for q in got]
    assert flags == sorted(flags, reverse=True)  # True가 모두 앞이다
    assert got[0].name == "homeless_now" and got[0].can_rule_out
    # residence_area는 3개 경로에 쓰이지만 규칙 칸(children_unmarried, 경로 1개)보다 뒤다
    assert _names(got).index("children_unmarried") < _names(got).index("residence_area")


def test_wider_route_count_comes_first_within_a_group():
    plans = _plans("homeless", "income_asset", "special_type")
    verdicts = [_v("income_asset", "NEED_INFO"), _special("신혼부부", "NEED_INFO"),
                _special("생애최초", "NEED_INFO")]  # fmt: skip
    profile = {"homeless_now": True, "savings_join_date": "2020-01-01", "ever_owned": False,
               "married": True, "marriage_date": "2024-01-01"}  # fmt: skip
    got = _ask(plans, verdicts, profile)
    assert not any(q.can_rule_out for q in got)
    counts = [len(q.routes) for q in got]
    assert counts == sorted(counts, reverse=True)
    assert _names(got)[:2] == ["household_income", "real_estate_value"]  # 경로 2개
    assert _names(got)[2:] == ["deposit_amount", "income_tax_years"]  # 경로 1개(생애최초): 표 순서


def test_general_route_wins_a_tie_then_the_table_order():
    plans = _plans("residence", "special_type")
    verdicts = [_v("residence", "NEED_INFO"), _special("기관추천", "NEED_INFO")]
    got = _ask(plans, verdicts)
    # residence는 일반공급 + 기관추천 2개, referral_status는 기관추천 1개
    assert _names(got) == ["residence_area", "residence_period", "referral_status"]


def test_unverifiable_and_failed_verdicts_are_not_asked():
    plans = _plans("homeless", "account", "residence")
    verdicts = [_v("homeless", "UNVERIFIABLE"), _v("account", None), _v("residence", "NEED_INFO")]
    assert _names(_ask(plans, verdicts)) == ["residence_area", "residence_period"]


def test_off_axes_and_non_need_info_verdicts_are_skipped():
    plans = _plans("homeless")  # residence는 꺼졌다
    verdicts = [_v("homeless", "ELIGIBLE"), _v("residence", "NEED_INFO")]
    assert _ask(plans, verdicts) == []
    assert _ask(_plans("homeless"), [_v("homeless", "CONDITIONAL")]) == []


def test_question_line_has_every_field():
    got = _ask(_plans("homeless"), [_v("homeless", "NEED_INFO")])
    assert len(got) == 1
    q = got[0]
    assert (q.name, q.has_field, q.can_rule_out) == ("homeless_now", True, True)
    assert q.text == qs.TEXT["homeless_now"] and q.axes == ["homeless"]
    assert q.routes == ["일반공급"]


def test_question_without_profile_field_is_still_asked():
    got = _ask(_plans("residence"), [_v("residence", "NEED_INFO")])
    assert [(q.name, q.has_field) for q in got] == [
        ("residence_area", False),
        ("residence_period", False),
    ]


# ── 응답·텍스트 ──────────────────────────────────────────────────────────


def _answer(questions):
    r = agg.Route("general", "일반공급", "NEED_INFO")
    zero = {"lo": 0, "hi": 0}
    score = dict.fromkeys(("homeless", "dependents", "savings", "total"), zero) | {"missing": []}
    return agg.Answer(
        "1", "1", "단지", "2026-09-10", None, None, "NEED_INFO", r, [], [], [], score, questions
    )


def test_answer_dumps_questions_to_json():
    got = _ask(_plans("homeless"), [_v("homeless", "NEED_INFO")])
    import dataclasses

    data = json.loads(json.dumps(dataclasses.asdict(_answer(got))))
    assert data["questions"][0]["name"] == "homeless_now"
    assert set(data["questions"][0]) == {
        "name",
        "text",
        "has_field",
        "can_rule_out",
        "axes",
        "routes",
    }


def test_render_text_lists_questions_in_order():
    got = _ask(
        _plans("homeless", "residence"), [_v("homeless", "NEED_INFO"), _v("residence", "NEED_INFO")]
    )
    text = agg.render_text(_answer(got))
    lines = text.splitlines()
    head = lines.index(f"확인할 질문: {len(got)}개")
    for n, q in enumerate(got, 1):
        assert q.text in lines[head + n] and lines[head + n].lstrip().startswith(f"{n}.")
    assert "입력란 없음" in lines[head + 2]
    assert "불가 판정" in lines[head + 1]


def test_render_text_with_no_question_keeps_the_none_line():
    assert agg.render_text(_answer([])).splitlines()[-1] == "확인할 질문: 없음"


# ── 규칙이 더 걸릴 수 없는 칸은 묻지 않는다 ─────────────────────────────


def test_marriage_date_is_not_a_rule_cell_for_someone_who_is_not_married():
    q = TYPE(type="신혼부부")
    unmarried = _info("special_type", q, {"married": False})
    assert "marriage_date" not in unmarried.can_rule_out
    assert "married" not in unmarried.can_rule_out  # 답한 칸이다
    assert unmarried.info[-1] == "marriage_status"
    for profile in ({}, {"married": True}):  # 모르거나 혼인 중이면 혼인신고일이 규칙을 가를 수 있다
        assert "marriage_date" in _info("special_type", q, profile).can_rule_out


def test_profile_fields_without_a_profile_keeps_every_rule_cell():
    assert "marriage_date" in rules.profile_fields("special_type", TYPE(type="신혼부부"))
    got = rules.profile_fields("special_type", TYPE(type="신혼부부"), {"married": False})
    assert "marriage_date" not in got
