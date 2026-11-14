import pytest

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import questions_report as qr
from cheongyak_rag.retrieval import axes

TYPE = axes.Q_SPECIAL.format
EMPTY = prof.Profile().to_dict()


def _facts():
    flags = dict.fromkeys((c for c, _ in axes.REGULATION_FLAGS), False)
    by_type = {k: 0 for k, _ in axes.SPECIAL_TYPES}
    by_type["NWWDS_HSHLDCO"] = by_type["INSTT_RECOMEND_HSHLDCO"] = 5
    return axes.Facts("서울", flags, 10, by_type, "286965", "01")


Q_NEWLY, Q_INSTT = TYPE(type="신혼부부"), TYPE(type="기관추천")


def _gold(axis, query, verdict, need=(), rule=None):
    return {"axis": axis, "query": query, "verdict": verdict, "need": list(need), "rule": rule,
            "reason": "이유"}  # fmt: skip


def _row(labels, profile=None, id_="g01", kind="partial"):
    return {"id": id_, "notice_name": f"공고 {id_}", "as_of": "2026-09-10", "profile_kind": kind,
            "profile": {**EMPTY, **(profile or {})}, "labels": labels}  # fmt: skip


def _line(row, g, sys, pre=None, error=None, top=("제2조",), matched=True):
    return {"id": row["id"], "notice_name": row["notice_name"], "axis": g["axis"],
            "query": g["query"], "gold_verdict": g["verdict"], "matched": matched,
            "sys_verdict": sys, "sys_pre_verdict": pre or sys, "error": error,
            "law_top5": list(top), "faq_top3": []}  # fmt: skip


def _lines(row, *systems):
    return [_line(row, g, s) for g, s in zip(row["labels"], systems, strict=True)]


G_HOME = _gold("homeless", axes.Q_HOMELESS, "NEED_INFO", ["homeless_now"], "homeless-3")
G_RES = _gold(
    "residence", axes.Q_RESIDENCE_NO_AREA, "NEED_INFO", ["residence_area", "residence_period"]
)
G_NEW = _gold("special_type", Q_NEWLY, "NEED_INFO", ["household_income", "real_estate_value"])
G_INS = _gold("special_type", Q_INSTT, "NEED_INFO", ["referral_status"], "referral-2")
PLANS = axes.plan_from_facts(_facts())


# ── 정답 라벨로 합친 경로와 필요한 질문 ──────────────────────────────────


def test_gold_routes_merge_the_gold_labels_by_priority():
    row = _row([G_HOME, G_NEW, {**G_INS, "verdict": "INELIGIBLE"}])
    agg = qr.gold_routes(PLANS, row)
    assert agg.general.verdict == "NEED_INFO"
    got = {r.key: r.verdict for r in agg.special}
    assert got == {"신혼부부": "NEED_INFO", "기관추천": "INELIGIBLE"}


def test_needed_questions_follow_the_design_definition():
    row = _row([G_HOME, G_NEW, G_INS])
    need = qr.needed_questions(PLANS, row, _facts())
    # 정답 NEED_INFO 하위 질의의 없는 정보와 불가 판정을 낼 수 있는 빈 칸
    assert {"homeless_now", "household_income", "real_estate_value", "referral_status"} <= need
    assert {"married", "marriage_date", "savings_join_date"} <= need  # 신혼부부 규칙 칸
    assert "residence_area" not in need  # 이 문항 정답 라벨에 거주 하위 질의가 없다


def test_a_closed_gold_route_makes_its_questions_unneeded():
    closed = {**G_NEW, "verdict": "INELIGIBLE", "need": []}
    row = _row([G_HOME, closed, G_INS])
    need = qr.needed_questions(PLANS, row, _facts())
    assert "household_income" not in need and "married" not in need
    assert "referral_status" in need  # 기관추천 경로는 열려 있다


def test_general_ineligible_gold_needs_no_question():
    row = _row([{**G_HOME, "verdict": "INELIGIBLE", "need": []}, G_NEW, G_INS])
    assert qr.needed_questions(PLANS, row, _facts()) == set()


def test_only_need_info_gold_labels_make_questions_needed():
    row = _row([{**G_HOME, "verdict": "ELIGIBLE", "need": []}], {"homeless_now": True})
    assert qr.needed_questions(PLANS, row, _facts()) == set()


# ── 시스템 질문과 불필요·빠진 질문 ───────────────────────────────────────


def test_system_questions_come_from_run_verdicts_and_skip_unmatched_lines():
    row = _row([G_HOME, G_RES])
    lines = [_line(row, G_HOME, "NEED_INFO"), _line(row, G_RES, None, matched=False)]
    asked = qr.asked_questions(PLANS, row, lines, _facts())
    assert [q.name for q in asked] == ["homeless_now"]


def test_unfiltered_info_asks_every_missing_info_of_need_info_verdicts():
    row = _row([G_HOME, G_RES, G_NEW])
    lines = _lines(row, "NEED_INFO", "UNVERIFIABLE", "NEED_INFO")
    got = qr.unfiltered_info(row, lines, _facts())
    assert got == {"homeless_now", "household_income", "real_estate_value"}


def test_question_sources_name_the_sub_queries_that_use_the_question():
    closed = {**G_NEW, "verdict": "INELIGIBLE", "need": [], "rule": "newlywed-3"}
    row = _row([G_HOME, closed])
    lines = _lines(row, "NEED_INFO", "NEED_INFO")
    got = qr.question_sources(row, lines, _facts(), {"household_income"})
    want = {"name": "household_income", "axis": "special_type", "query": Q_NEWLY,
            "gold": "INELIGIBLE", "gold_rule": "newlywed-3", "system": "NEED_INFO"}  # fmt: skip
    assert got == [want]


def test_measure_counts_unneeded_missing_and_the_unfiltered_baseline():
    closed = {**G_NEW, "verdict": "INELIGIBLE", "need": [], "rule": "newlywed-3"}
    row = _row([G_HOME, closed, G_INS])
    now = _lines(row, "NEED_INFO", "NEED_INFO", "NEED_INFO")  # 신혼부부 경로를 못 닫았다
    base = _lines(row, "NEED_INFO", "NEED_INFO", "UNVERIFIABLE")
    m = qr.measure([row], now, base, {"g01": _facts()})
    assert (m["found"], m["den"]) == (2, 2)  # NEED_INFO 정답 라벨은 homeless·기관추천 둘이다
    assert len(m["unneeded"]) == 1 and "household_income" in m["unneeded"][0]["names"]
    assert len(m["unfiltered"]) == 1 and len(m["missing"]) == 0
    # 기준 판정은 기관추천을 UNVERIFIABLE로 내서 referral_status가 빠졌다
    assert [x["names"] for x in m["missing_base"]] == [{"referral_status"}]


def test_analysis_mismatch_lists_the_sub_queries_with_a_different_need():
    row = _row([G_HOME, {**G_RES, "need": ["residence_area"]}])
    total, bad = qr.analysis_mismatches(row, _facts())
    assert total == 2
    assert [(b["axis"], b["need"], b["got"]) for b in bad] == [
        ("residence", ["residence_area"], ["residence_area", "residence_period"])
    ]


# ── 규칙이 바꾼 하위 질의 ────────────────────────────────────────────────


def test_rule_hits_need_a_successful_call_with_context():
    g = _gold("homeless", axes.Q_HOMELESS, "INELIGIBLE", [], "homeless-1")
    row = _row([g], {"homeless_now": False})
    ok = _line(row, g, "INELIGIBLE", pre="NEED_INFO")
    hits = qr.rule_hits(row, [ok], _facts())
    assert [(h["rule"], h["model"], h["system"], h["gold"]) for h in hits] == [
        ("homeless-1", "NEED_INFO", "INELIGIBLE", "INELIGIBLE")
    ]
    assert qr.rule_values(hits[0]) == "homeless_now=False"
    assert qr.rule_hits(row, [_line(row, g, None, error="끊김")], _facts()) == []
    assert qr.rule_hits(row, [_line(row, g, "UNVERIFIABLE", top=())], _facts()) == []  # 근거 0개
    assert qr.rule_hits(row, [_line(row, g, None, matched=False)], _facts()) == []


def test_fatal_lines_are_gold_ineligible_with_system_eligible():
    row = _row([{**G_HOME, "verdict": "INELIGIBLE"}, G_RES])
    lines = _lines(row, "ELIGIBLE", "ELIGIBLE")
    assert [r["axis"] for r in qr.fatal_lines(lines)] == ["homeless"]


# ── 구간 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "found,unneeded,band",
    [(378, 0, "통과"), (377, 0, "다시 잰다"), (360, 0, "다시 잰다"), (359, 0, "미완"),
     (378, 1, "다시 잰다"), (378, 3, "다시 잰다"), (378, 4, "미완"), (360, 4, "미완")],
)  # fmt: skip
def test_jw_band(found, unneeded, band):
    assert qr.band_jw(found, 378, unneeded) == band


@pytest.mark.parametrize("now,band", [(20, "정상"), (24, "정상"), (25, "다시 잰다"),
                                      (27, "다시 잰다"), (28, "미완")])  # fmt: skip
def test_missing_band_is_relative_to_the_baseline(now, band):
    assert qr.band_missing(now, 24) == band


@pytest.mark.parametrize("n,band", [(0, "정상"), (1, "다시 잰다"), (3, "다시 잰다"), (4, "미완")])
def test_rule_band(n, band):
    assert qr.band_rule(n) == band


@pytest.mark.parametrize("n,band", [(0, "정상"), (2, "정상"), (3, "다시 잰다"), (5, "다시 잰다"),
                                    (6, "미완")])  # fmt: skip
def test_fatal_band(n, band):
    assert qr.band_fatal(n) == band


# ── 글 ───────────────────────────────────────────────────────────────────


def test_render_has_every_section_and_the_design_lines():
    closed = {**G_NEW, "verdict": "INELIGIBLE", "need": [], "rule": "newlywed-3"}
    row = _row([G_HOME, closed, G_INS])
    now = _lines(row, "NEED_INFO", "NEED_INFO", "NEED_INFO")
    m = qr.measure([row], now, now, {"g01": _facts()})
    md = qr.render([row], _full(now), _full(now), m)
    heads = ("## jw 기준", "## 실패 징후 2", "## 실패 징후 3", "## 실패 징후 4", "## 지표 7개",
             "## 규칙이 바꾼 하위 질의", "## 질문 목록 예시", "## 설계 §4")  # fmt: skip
    assert all(h in md for h in heads)
    assert qr.JW_CRITERIA in md and all(s in md for s in qr.DESIGN_SECTION_4)
    assert "newlywed-3" in md and "이번에 옮기지 않은 규칙" in md


def _full(lines):
    """지표 계산에 필요한 칸을 채운다."""
    return [
        {**r, "gold_citations": ["제2조"], "sys_citations": [], "faq_top3": [], "cause": None}
        for r in lines
    ]


def test_design_section_4_matches_the_design_document():
    text = (qr.ROOT / "docs/plans/82-1114-design-missing-info.md").read_text(encoding="utf-8")
    section = text.split("## 4. 숫자 읽는 법")[1].split("## 5.")[0]
    for line in qr.DESIGN_SECTION_4:
        assert line in section.replace("**", "")
