import pytest

from cheongyak_rag.generate import eligible_report as er
from cheongyak_rag.generate import rules
from cheongyak_rag.retrieval import axes

Q_H, Q_HH = axes.Q_HOMELESS, axes.Q_HOUSEHOLDER
RULE_H = rules.rule_eligible("homeless", Q_H, {"homeless_now": True})[1]


def _facts():
    flags = dict.fromkeys((c for c, _ in axes.REGULATION_FLAGS), False)
    return axes.Facts("부산", flags, 10, {k: 0 for k, _ in axes.SPECIAL_TYPES}, "286965", "01")


def _rec(axis="homeless", query=Q_H, verdict="ELIGIBLE", reason="r", profile=None, **kw):
    base = {"sample": "골든셋", "where": "g01", "axis": axis, "query": query, "verdict": verdict,
            "reason": reason, "model": verdict, "gold": "ELIGIBLE", "gold_reason": "정답 이유",
            "profile": profile or {}, "facts": _facts()}  # fmt: skip
    return base | kw


# ── 「정보가 없음」 칸 (설계 §3) ─────────────────────────────────────────


def test_missing_cells_has_the_empty_field_of_the_axis():
    assert er.missing_cells("homeless", Q_H, {"homeless_now": None}, _facts()) == ["homeless_now"]
    assert er.missing_cells("householder", Q_HH, {}, _facts()) == ["is_household_head"]


def test_missing_cells_is_empty_when_the_axis_field_is_answered():
    assert er.missing_cells("homeless", Q_H, {"homeless_now": True}, _facts()) == []
    assert er.missing_cells("householder", Q_HH, {"is_household_head": False}, _facts()) == []


def test_missing_cells_counts_the_info_that_has_no_profile_field():
    got = er.missing_cells("residence", "거주 질의", {"homeless_now": True}, _facts())
    assert got == ["residence_area", "residence_period"]  # 칸이 없는 정보도 없는 정보다


def test_missing_cells_lists_a_cell_once():
    got = er.missing_cells("homeless", Q_H, {}, _facts())
    assert got.count("homeless_now") == 1  # 세 정의에 다 들어도 한 번만 적는다


# ── 가능 규칙이 쓴 이유인지 ──────────────────────────────────────────────


def test_ruled_by_needs_the_rule_to_hit_and_the_reason_to_be_its_sentence():
    p = {"homeless_now": True}
    assert er.ruled_by("homeless", Q_H, p, RULE_H) == "homeless-2"
    assert er.ruled_by("homeless", Q_H, p, "모델이 쓴 이유") is None
    assert er.ruled_by("homeless", Q_H, {"homeless_now": False}, RULE_H) is None
    assert er.ruled_by("account", "q", p, RULE_H) is None


# ── 실패 징후 ────────────────────────────────────────────────────────────


def test_symptom_1_counts_final_eligible_with_a_missing_cell():
    ok = _rec(profile={"homeless_now": True}, reason=RULE_H)
    bad = _rec(profile={"homeless_now": None})
    other = _rec(profile={"homeless_now": None}, verdict="NEED_INFO")  # ELIGIBLE이 아니면 안 센다
    got = er.jw_hits([ok, bad, other])
    assert [h["cells"] for h in got] == [["homeless_now"]] and got[0]["rec"] is bad


def test_symptom_2_counts_final_eligible_whose_reason_is_not_the_rule_sentence():
    ruled = _rec(profile={"homeless_now": True}, reason=RULE_H)
    model = _rec(profile={"homeless_now": True}, reason="제53조상 예외 사유가 없어")
    assert er.model_reasons([ruled, model, _rec(verdict="NEED_INFO")]) == [model]


def test_symptom_3_counts_golden_final_eligible_without_an_eligible_gold():
    right, wrong = _rec(), _rec(gold="NEED_INFO")
    demo = _rec(sample="시연", gold=None)  # 정답이 없는 표본은 안 센다
    assert er.wrong_eligible([right, wrong, demo]) == [wrong]


def test_rule_changes_group_by_rule_and_model_verdict():
    p = {"homeless_now": True, "is_household_head": True}
    recs = [
        _rec(profile=p, reason=RULE_H, model="NEED_INFO"),
        _rec(profile=p, reason=RULE_H, model="NEED_INFO"),
        _rec(profile=p, reason=RULE_H, model="ELIGIBLE"),
        _rec(axis="householder", query=Q_HH, profile=p, model="CONDITIONAL",
             reason=rules.rule_eligible("householder", Q_HH, p)[1]),
        _rec(profile=p, reason="모델 이유"),  # 가능 규칙이 안 쓴 이유는 안 센다
    ]  # fmt: skip
    got = er.rule_changes(recs)
    assert got[("homeless-2", "NEED_INFO")] == 2 and got[("homeless-2", "ELIGIBLE")] == 1
    assert got[("householder-2", "CONDITIONAL")] == 1 and sum(got.values()) == 4


# ── 구간 (plan §실패 징후) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "zone"), [(0, "통과"), (1, "다시 잰다"), (2, "다시 잰다"), (3, "미완")]
)
def test_count_zone(n, zone):
    assert er.zone_count(n) == zone


@pytest.mark.parametrize(
    ("n", "zone"),
    [(432, "정상"), (421, "정상"), (420, "다시 잰다"), (416, "다시 잰다"), (415, "미완")],
)
def test_accuracy_zone(n, zone):
    assert er.zone_accuracy(n) == zone


# ── 측정·리포트 ──────────────────────────────────────────────────────────

FULL = {"homeless_now": True, "is_household_head": True}


def _line(rec, gold="ELIGIBLE"):
    return {"gold_verdict": gold, "sys_verdict": rec["verdict"], "gold_citations": [],
            "law_top5": [], "sys_citations": [], "axis": rec["axis"]}  # fmt: skip


def _side(*recs, demo=()):
    return {"golden": list(recs), "demo": list(demo), "rows": [_line(r, r["gold"]) for r in recs]}


def test_measure_zones_follow_the_plan_bands():
    ruled = _rec(profile=FULL, reason=RULE_H)
    now = _side(ruled, ruled | {"where": "g02"})
    base = _side(_rec(profile=FULL, reason="모델 이유"), _rec(profile=FULL, reason="또 모델"))
    m = er.measure(now, base)
    assert m["zones"]["jw"] == "통과" and m["zones"]["model"] == "정상"
    assert len(m["base"]["model"]) == 2 and m["base"]["changes"] == {}
    assert m["now"]["changes"] == {("homeless-2", "ELIGIBLE"): 2}


def test_measure_flags_an_eligible_with_a_missing_cell_and_a_model_reason():
    bad = _rec(profile={"homeless_now": None}, reason="모델이 쓴 이유")
    m = er.measure(_side(bad), _side(bad))
    assert m["zones"]["jw"] == "다시 잰다" and m["zones"]["model"] == "다시 잰다"
    md = er.render(m, [])
    assert "### 징후 1" in md and "homeless_now" in md and "### 징후 2" in md


def test_render_has_the_five_symptoms_the_metric_table_and_design_section_4():
    ruled = _rec(profile=FULL, reason=RULE_H, model="NEED_INFO")
    m = er.measure(_side(ruled), _side(_rec(profile=FULL, reason="모델", model="NEED_INFO")))
    md = er.render(m, [])
    for head in (
        "## 실패 징후 1~5",
        "## 지표 7개",
        "## 가능 규칙이 이유를 쓴 하위 질의",
        "## 설계 §4",
    ):
        assert head in md
    assert "| homeless-2 | 0 | 0 | 1 | 0 | 0 | 1 |" in md
    assert all(s in md for s in er.DESIGN_SECTION_4)
    assert "### 징후 1" not in md  # 걸린 것이 없으면 표를 안 낸다


def test_changed_golden_lists_only_the_sub_queries_whose_final_verdict_differs():
    old = _rec(verdict="NEED_INFO", key=("g01", "homeless", Q_H))
    new = _rec(profile=FULL, reason=RULE_H, key=("g01", "homeless", Q_H))
    same = _rec(verdict="NEED_INFO", key=("g01", "account", "q"))
    got = er.changed_golden([new, same], [old, same])
    assert [(c["base"], c["now"], c["rule"]) for c in got] == [
        ("NEED_INFO", "ELIGIBLE", "homeless-2")
    ]
