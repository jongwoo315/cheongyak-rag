"""#81 B8 집계 — 우선순위 규칙이 코드와 기대값에서 같은가."""

import dataclasses
import json
import time
from datetime import date

import pytest
from sqlalchemy import text

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import aggregate as agg
from cheongyak_rag.generate import aggregate_report as ar
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_axes import _load_chunks, _notice, _version

GENERAL = ("homeless", "account", "residence", "rewin", "householder")

TYPE_A, TYPE_B = "다자녀가구", "신혼부부"


def _type_query(name):
    return axes.Q_SPECIAL.format(type=name)


def _v(axis, verdict, query=None):
    return vd.Verdict(axis, axis, query or axis, verdict=verdict)


def _plans(on_ids):
    return [axes.AxisPlan(a.id, a.name, a.id in on_ids, "") for a in axes.AXES]


def test_all_combinations_match_the_priority_rule():
    """7칸 × 6가지 상태 = 279,936개. 경로별 판정이 순번 최솟값과 다른 조합이 0이다."""
    t0 = time.perf_counter()
    total, wrong = ar.rule_mismatches()
    assert total == 6**7 == 279_936
    assert wrong == 0
    assert time.perf_counter() - t0 < 10  # 조합을 줄이지 말고 계산을 가볍게 한다


def test_rule_check_catches_a_wrong_priority(monkeypatch):
    swapped = {**agg._RANK, "UNVERIFIABLE": 2, "NEED_INFO": 1}
    monkeypatch.setattr(agg, "_RANK", swapped)
    monkeypatch.setattr(
        agg, "PRIORITY", ("INELIGIBLE", "NEED_INFO", "UNVERIFIABLE", "CONDITIONAL", "ELIGIBLE")
    )
    assert ar.rule_mismatches()[1] > 0


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


@pytest.mark.parametrize("verdict", ["INELIGIBLE", "UNVERIFIABLE", "NEED_INFO", None])
def test_only_eligible_and_conditional_routes_are_applicable(verdict):
    """정보가 더 필요하거나 확인 못 한 경로는 신청 가능한 경로가 아니다."""
    plans = _plans({"homeless", "special_type"})
    verdicts = [_v("homeless", "ELIGIBLE"), _v("special_type", verdict, _type_query(TYPE_A))]
    got = agg.aggregate(plans, verdicts)
    assert [r.key for r in got.applicable] == ["general"]
    assert agg.aggregate(_plans({"homeless"}), [_v("homeless", verdict)]).applicable == []


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


# ── B9 응답 ──────────────────────────────────────────────────────────────


@pytest.fixture
def world(pg_engine):
    """공고(특별공급 다자녀 4세대, 투기과열) + 법령 버전 + chunks. (engine, hmn, notice, plans)."""
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(4, {"MNYCH_HSHLDCO": 4})], speclt_rdn_earth_at=True)
    _load_chunks(pg_engine, other_mst=False)
    pblanc, name, facts = axes.load_facts(pg_engine, hmn)
    notice = vd.NoticeInfo(hmn, pblanc, name, date(2026, 10, 1), facts)
    return pg_engine, hmn, notice, axes.plan_from_facts(facts)


def _fv(
    axis, verdict, query=None, reason="문맥대로다.", cites=("제2조",), ctx=("제2조", "Q1"), **kw
):
    return vd.Verdict(
        axis, axis, query or axis, verdict=verdict, reason=reason, citations=list(cites),
        context_labels=list(ctx), titles={c: f"{c} 제목" for c in cites}, **kw,
    )  # fmt: skip


def _all_verdicts(**over):
    base = {a: "ELIGIBLE" for a in (*GENERAL, "income_asset")}
    base |= over
    out = [_fv(a, v) for a, v in base.items()]
    out.append(_fv("special_type", "INELIGIBLE", _type_query(TYPE_A)))
    return out


def _profile():
    return prof.Profile(birth_date=date(1990, 1, 1))


def _chunk_text(engine, label):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT text FROM chunks WHERE label = :l LIMIT 1"), {"l": label}
        ).scalar_one()


def test_answer_has_every_field_and_dumps_to_json(world):
    engine, hmn, notice, plans = world
    a = agg.build_answer(engine, notice, plans, _all_verdicts(), _profile())
    assert a.verdict == a.general.verdict == "ELIGIBLE"
    assert [(r.key, r.verdict) for r in a.special] == [(TYPE_A, "INELIGIBLE")]
    assert [r.key for r in a.applicable] == ["general"]
    assert a.questions == []
    assert a.law_mst == "286965" and a.law_effective_date == "2026-06-15"
    assert a.score["total"]["lo"] <= a.score["total"]["hi"]
    assert len(a.checklist) == 7
    item = a.checklist[0]
    assert item.axis == "homeless" and item.verdict == "ELIGIBLE" and item.reason
    (ev,) = item.citations
    assert ev.label == "제2조" and ev.text == _chunk_text(engine, "제2조")
    assert ev.source == "주택공급에 관한 규칙 제2조 (법령 MST 286965 · 시행일 2026-06-15)"
    dumped = json.dumps(dataclasses.asdict(a), ensure_ascii=False)
    assert json.loads(dumped)["verdict"] == "ELIGIBLE"


def test_faq_evidence_uses_the_faq_row_and_its_source(world):
    engine, _, notice, plans = world
    v = [_fv("homeless", "ELIGIBLE", cites=("제2조", "Q1"))]
    a = agg.build_answer(engine, notice, plans, v, _profile())
    laws, faq = a.checklist[0].citations
    assert (laws.kind, faq.kind) == ("law", "faq")
    assert faq.text == _chunk_text(engine, "Q1")
    assert faq.source == "2024 주택청약 FAQ Q1"


def test_links_are_only_for_verified_kinds(world):
    engine, _, notice, plans = world
    v = [_fv("homeless", "ELIGIBLE", cites=("제2조", "Q1"))]
    both = agg.build_answer(engine, notice, plans, v, _profile(), link_kinds=("law", "faq"))
    law, faq = both.checklist[0].citations
    assert law.url == agg.link_for("law", "286965") and "286965" in law.url
    assert faq.url == agg.link_for("faq", "286965")
    only_law = agg.build_answer(engine, notice, plans, v, _profile(), link_kinds=("law",))
    assert [e.url is not None for e in only_law.checklist[0].citations] == [True, False]
    none = agg.build_answer(engine, notice, plans, v, _profile(), link_kinds=())
    assert [e.url for e in none.checklist[0].citations] == [None, None]


def test_read_texts_takes_law_rows_of_the_notice_mst_only(pg_engine):
    _version(pg_engine)
    _load_chunks(pg_engine, other_mst=True)  # 같은 라벨의 MST 999 조문이 함께 들어 있다
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE chunks SET text = 'OLD' WHERE law_mst = '999'"))
    got = agg.read_texts(pg_engine, "286965", ["제2조", "Q1"])
    assert set(got) == {"제2조", "Q1"} and "OLD" not in got.values()
    # 적용되는 법령 버전을 모르면 조문은 읽지 않고 FAQ만 읽는다
    assert set(agg.read_texts(pg_engine, None, ["제2조", "Q1"])) == {"Q1"}
    assert agg.read_texts(pg_engine, "286965", []) == {}


def test_outside_mentions_are_reason_numbers_missing_from_the_context():
    reason = "제2조와 제53조제1항, 제35조의2, FAQ Q1과 Q99 그리고 제53조를 다시 본다."
    got = agg.outside_mentions(reason, ["제2조", "Q1"])
    assert got == ["제53조", "제35조의2", "Q99"]  # 항은 조로 세고 같은 번호는 한 번만
    assert agg.outside_mentions("제2조만 본다", ["제2조"]) == []
    assert agg.outside_mentions("", []) == []
    # 접두 번호는 다른 조다 — 제5조가 문맥에 있어도 제53조는 검색 밖이다
    assert agg.outside_mentions("제53조", ["제5조"]) == ["제53조"]


def test_answer_marks_outside_mentions_per_query(world):
    engine, _, notice, plans = world
    v = [
        _fv("homeless", "ELIGIBLE", reason="제2조와 제53조를 봤다.", ctx=("제2조",)),
        _fv("account", "ELIGIBLE", reason="제2조를 봤다.", ctx=("제2조",)),
    ]
    a = agg.build_answer(engine, notice, plans, v, _profile())
    assert [i.outside for i in a.checklist] == [["제53조"], []]


def test_render_text_shows_the_outside_mention_and_the_forced_note(world):
    engine, _, notice, plans = world
    v = [
        _fv("homeless", "ELIGIBLE", reason="제2조와 제53조를 봤다.", ctx=("제2조",)),
        _fv("account", "UNVERIFIABLE", forced=True, original_verdict="ELIGIBLE"),
    ]
    out = agg.render_text(agg.build_answer(engine, notice, plans, v, _profile()))
    assert "검색 밖 언급: 제53조" in out
    assert "인용이 모두 기각돼 UNVERIFIABLE로 바뀜 (모델 판정 ELIGIBLE)" in out
    assert out.count("검색 밖 언급") == 1  # 문맥 안 번호만 언급한 질의에는 안 붙는다


def test_failed_verdict_is_listed_with_its_error_and_counts_as_unverifiable(world):
    engine, _, notice, plans = world
    v = _all_verdicts()
    v[1] = vd.Verdict("account", "account", "account", verdict=None, error="RuntimeError: x")
    a = agg.build_answer(engine, notice, plans, v, _profile())
    assert a.verdict == "UNVERIFIABLE"
    item = a.checklist[1]
    assert item.verdict is None and item.error == "RuntimeError: x" and item.citations == []


def test_render_text_leads_with_global_verdict_routes_and_checklist(world):
    engine, _, notice, plans = world
    a = agg.build_answer(engine, notice, plans, _all_verdicts(), _profile())
    out = agg.render_text(a)
    head = out.split("\n\n")[0]
    assert "전역 판정" in head and "ELIGIBLE" in head
    assert "특별공급 다자녀가구" in out and "INELIGIBLE" in out
    assert "신청 가능한 경로" in out and "체크리스트" in out
    assert "주택공급에 관한 규칙 제2조" in out
    assert out.index("전역 판정") < out.index("체크리스트")


def test_verdict_cli_prints_the_answer_above_the_old_report(tmp_path, capsys, world):
    engine, hmn, *_ = world
    pf = tmp_path / "p.json"
    pf.write_text('{"birth_date": "1990-01-01"}', encoding="utf-8")
    reply = json.dumps(
        {"verdict": "ELIGIBLE", "reason": "r", "conditions": [], "need_info": [], "citations": []}
    )
    code = vd.main(
        [hmn, "--profile", str(pf)], engine=engine, embedder=FakeEmbedder(dim=1536),
        client=FakeChat([reply]), cache_path=tmp_path / "c.jsonl", trace_key="k",
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    top, sep, old = out.partition("\n---\n")
    assert sep and "전역 판정" in top and "공고: " not in old.split("\n")[0]
    assert old.lstrip().startswith("공고: ")  # 기존 출력은 구분선 아래에 그대로 있다
    assert "켜짐 —" in out and "판정 7개" in out


def test_note_names_the_rule_before_any_other_change():
    v = _fv("homeless", "INELIGIBLE", ruled=True, rule="homeless-1", original_verdict="ELIGIBLE")
    assert agg._note(v) == "프로필 불가 규칙 homeless-1이 INELIGIBLE로 바꿈 (모델 판정 ELIGIBLE)"
    both = _fv("homeless", "INELIGIBLE", ruled=True, rule="homeless-1", forced=True,
               original_verdict="NEED_INFO")  # fmt: skip
    assert agg._note(both).startswith("프로필 불가 규칙 homeless-1")


def test_note_does_not_say_changed_when_the_model_already_said_ineligible():
    v = _fv("homeless", "INELIGIBLE", ruled=True, rule="homeless-1", original_verdict="INELIGIBLE")
    assert agg._note(v) == "프로필 불가 규칙 homeless-1이 걸림 (모델 판정도 INELIGIBLE)"
