"""#81 B8 집계 — 우선순위 규칙이 코드와 기대값에서 같은가."""

import itertools
import time

from cheongyak_rag.generate import aggregate as agg
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes

# 기대값의 유일한 출처. 설계 §B8 / 바탕 설계 §168의 우선순위를 코드와 따로 적었다
ORDER = ("INELIGIBLE", "UNVERIFIABLE", "NEED_INFO", "CONDITIONAL", "ELIGIBLE")
GENERAL = ("homeless", "account", "residence", "rewin", "householder")
SLOTS = (*GENERAL, "income_asset", "special_type")  # 7칸
STATES = (None, *ORDER)  # 꺼짐 + 판정값 5개

TYPE_A, TYPE_B = "다자녀가구", "신혼부부"


def _type_query(name):
    return axes.Q_SPECIAL.format(type=name)


def _v(axis, verdict, query=None):
    return vd.Verdict(axis, axis, query or axis, verdict=verdict)


def _plans(on_ids):
    return [axes.AxisPlan(a.id, a.name, a.id in on_ids, "") for a in axes.AXES]


def _expect(values):
    """순번 최솟값. 값이 없으면 None."""
    ranks = [ORDER.index(x) for x in values]
    return ORDER[min(ranks)] if ranks else None


def test_all_combinations_match_the_priority_rule():
    """7칸 × 6가지 상태 = 279,936개. 코드의 경로별 판정이 순번 최솟값과 다른 조합이 0이다."""
    # 객체는 (칸, 상태)마다 하나씩 만들어 돌려 쓴다 — 조합마다 새로 만들면 느리다
    cells = {
        (s, st): _v(s, st, _type_query(TYPE_A) if s == "special_type" else None)
        for s in SLOTS
        for st in ORDER
    }
    plans = {}
    wrong = total = 0
    t0 = time.perf_counter()
    for combo in itertools.product(STATES, repeat=len(SLOTS)):
        total += 1
        on = {s for s, st in zip(SLOTS, combo, strict=True) if st is not None}
        key = frozenset(on)
        if key not in plans:
            plans[key] = _plans(on)
        verdicts = [cells[(s, st)] for s, st in zip(SLOTS, combo, strict=True) if st is not None]
        got = agg.aggregate(plans[key], verdicts)

        general = [st for s, st in zip(SLOTS, combo, strict=True) if s in GENERAL and st]
        income = [st for s, st in zip(SLOTS, combo, strict=True) if s == "income_asset" and st]
        type_a = [st for s, st in zip(SLOTS, combo, strict=True) if s == "special_type" and st]
        want_general = _expect(general)
        # 특별공급 유형 경로는 유형 질의가 있을 때만 생긴다
        want_special = {TYPE_A: _expect(general + income + type_a)} if type_a else {}
        got_special = {r.key: r.verdict for r in got.special}
        if (
            got.general.verdict != want_general
            or got.verdict != want_general
            or got_special != want_special
        ):
            wrong += 1
    assert total == 6**7 == 279_936
    assert wrong == 0
    assert time.perf_counter() - t0 < 10  # 조합을 줄이지 말고 계산을 가볍게 한다


def test_each_special_type_is_merged_on_its_own():
    """다자녀 INELIGIBLE이 신혼부부 경로나 일반공급 판정을 끌어내리지 않는다."""
    plans = _plans({*GENERAL, "income_asset", "special_type"})
    verdicts = [_v(a, "ELIGIBLE") for a in GENERAL]
    verdicts += [
        _v("income_asset", "ELIGIBLE"),
        _v("special_type", "INELIGIBLE", _type_query(TYPE_A)),
        _v("special_type", "CONDITIONAL", _type_query(TYPE_B)),
    ]
    got = agg.aggregate(plans, verdicts)
    assert got.verdict == got.general.verdict == "ELIGIBLE"
    assert {r.key: r.verdict for r in got.special} == {TYPE_A: "INELIGIBLE", TYPE_B: "CONDITIONAL"}
    # 신청 가능한 경로 = ELIGIBLE · CONDITIONAL인 경로 (일반공급 포함)
    assert [r.key for r in got.applicable] == ["general", TYPE_B]


def test_income_axis_joins_special_routes_but_not_general():
    plans = _plans({"homeless", "income_asset", "special_type"})
    verdicts = [
        _v("homeless", "ELIGIBLE"),
        _v("income_asset", "INELIGIBLE"),
        _v("special_type", "ELIGIBLE", _type_query(TYPE_A)),
    ]
    got = agg.aggregate(plans, verdicts)
    assert got.general.verdict == "ELIGIBLE"
    assert got.special[0].verdict == "INELIGIBLE"


def test_missing_verdict_counts_as_unverifiable():
    plans = _plans({"homeless", "account"})
    verdicts = [_v("homeless", "ELIGIBLE"), _v("account", None)]
    got = agg.aggregate(plans, verdicts)
    assert got.verdict == "UNVERIFIABLE"  # 빼고 합치면 ELIGIBLE이 된다


def test_nothing_on_gives_none():
    got = agg.aggregate(_plans(set()), [])
    assert got.verdict is None and got.general.verdict is None
    assert got.special == [] and got.applicable == []


def test_special_axis_without_type_query_match_keeps_the_query_as_key():
    plans = _plans({"homeless", "special_type"})
    verdicts = [_v("homeless", "ELIGIBLE"), _v("special_type", "NEED_INFO", axes.Q_SPECIAL_NO_TYPE)]
    got = agg.aggregate(plans, verdicts)
    assert [r.verdict for r in got.special] == ["NEED_INFO"]


def test_verdicts_of_off_axes_are_ignored():
    got = agg.aggregate(
        _plans({"homeless"}), [_v("homeless", "ELIGIBLE"), _v("rewin", "INELIGIBLE")]
    )
    assert got.verdict == "ELIGIBLE"
