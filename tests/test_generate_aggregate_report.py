import json
import re

import pytest

from cheongyak_rag.generate import aggregate as agg
from cheongyak_rag.generate import aggregate_report as ar
from cheongyak_rag.generate import verdict_report as vr
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_axes import _load_chunks, _notice, _version

LABEL = re.compile(r"^\[([^\]]+)\] ", re.M)
OK = {"law": 200, "faq": 200}


def _echo(verdict="ELIGIBLE", reason="문맥대로다."):
    def reply(kw):
        labels = LABEL.findall(kw["messages"][1]["content"])
        # 조문 하나와 FAQ 하나를 인용한다 — 링크 형식 둘이 다 실린다
        cites = [x for x in labels if x[0] != "Q"][:1] + [x for x in labels if x[0] == "Q"][:1]
        body = {
            "verdict": verdict, "reason": reason, "conditions": [], "need_info": [],
            "citations": cites,
        }  # fmt: skip
        return json.dumps(body, ensure_ascii=False)

    return reply


@pytest.fixture
def world(pg_engine, tmp_path):
    """공고 둘(7축이 켜지는 것 · 3축만) + chunks + 표본 JSON + 프로필 3종 + PR #14 기록."""
    _version(pg_engine)
    a = _notice(pg_engine, 1, models=[(7, {"MNYCH_HSHLDCO": 4, "NWWDS_HSHLDCO": 3})],
                speclt_rdn_earth_at=True)  # fmt: skip
    b = _notice(pg_engine, 2, models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    samples = tmp_path / "last_run.json"
    samples.write_text(json.dumps({"samples": [{"notice": a}, {"notice": b}]}), encoding="utf-8")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    full = {"birth_date": "1985-04-10", "homeless_now": True, "is_household_head": True,
            "savings_join_date": "2014-03-01"}  # fmt: skip
    (profiles / "full.json").write_text(json.dumps(full), encoding="utf-8")
    (profiles / "partial.json").write_text('{"birth_date": "1985-04-10"}', encoding="utf-8")
    (profiles / "empty.json").write_text("{}", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"system_sha": "92f338a4", "cells": []}), encoding="utf-8")
    return {
        "engine": pg_engine, "samples_json": samples, "profiles_dir": profiles,
        "baseline_json": baseline, "root": tmp_path, "hmn": a,
    }  # fmt: skip


def _run(world, client, *extra, name="out", status=None, combos=lambda: (279_936, 0), **kw):
    root = world["root"]
    code = ar.main(
        ["--report", *extra],
        engine=world["engine"], embedder=FakeEmbedder(dim=1536), client=client,
        cache_path=root / "cache.jsonl", samples_json=world["samples_json"],
        profiles_dir=world["profiles_dir"], baseline_json=world["baseline_json"],
        out_md=root / f"{name}.md", out_json=root / f"{name}.json", sleep=lambda s: None,
        fetch_status=lambda url: (status or OK)["faq" if "molit" in url else "law"],
        combos=combos, **kw,
    )  # fmt: skip
    return (
        code,
        (root / f"{name}.md").read_text("utf-8"),
        json.loads((root / f"{name}.json").read_text("utf-8")),
    )


# ── 다시 계산 ────────────────────────────────────────────────────────────


def test_indep_outside_matches_the_rule_without_calling_aggregate():
    reason = "제2조와 제53조제1항, 제35조의2, FAQ Q1과 Q99 그리고 제53조를 다시 본다."
    assert ar.mentions(reason) == ["제2조", "제53조", "제35조의2", "Q1", "Q99", "제53조"]
    assert ar.indep_outside(reason, ["제2조", "Q1"]) == ["제53조", "제35조의2", "Q99"]
    assert ar.indep_outside("제53조", ["제5조"]) == ["제53조"]
    assert ar.indep_outside("", ["제2조"]) == []
    # 구현과 같은 답이다 — 같은 규칙을 다른 코드로 센 것
    assert ar.indep_outside(reason, ["제2조", "Q1"]) == agg.outside_mentions(
        reason, ["제2조", "Q1"]
    )


def test_expected_routes_merges_general_and_each_type():
    v = lambda axis, verdict, query=None: {"axis": axis, "verdict": verdict, "query": query or axis}  # noqa: E731
    verdicts = [
        v("homeless", "ELIGIBLE"),
        v("account", None),  # 호출 실패 = UNVERIFIABLE
        v("income_asset", "CONDITIONAL"),
        v("special_type", "ELIGIBLE", "다자녀가구 특별공급의 신청 자격과 요건은 어떻게 되나요?"),
        v("special_type", "INELIGIBLE", "신혼부부 특별공급의 신청 자격과 요건은 어떻게 되나요?"),
        v("rewin", "INELIGIBLE"),  # 꺼진 축이라 안 센다
    ]
    got = ar.expected_routes(["homeless", "account", "income_asset", "special_type"], verdicts)
    assert got == {
        "general": "UNVERIFIABLE",
        "다자녀가구": "UNVERIFIABLE",
        "신혼부부": "INELIGIBLE",
    }


# ── 리포트 ───────────────────────────────────────────────────────────────


def test_zone_bands():
    assert ar.zone_rule(0, 0, False) == "통과"
    assert ar.zone_rule(1, 0, False) == "미완" and ar.zone_rule(0, 1, False) == "미완"
    assert ar.zone_rule(0, 0, True) == "미완"
    assert ar.zone_outside(0, 0, 1, False) == "통과"
    assert ar.zone_outside(0, 0, 0, False) == "다시 잰다"  # 표시가 한 번도 안 붙었다
    assert ar.zone_outside(1, 0, 5, False) == "미완" and ar.zone_outside(0, 1, 5, False) == "미완"
    assert ar.zone_links({"law": {"status": 200}}) == "통과"
    assert ar.zone_links({"law": {"status": 200}, "faq": {"status": 404}}) == "미완"


def test_report_measures_outside_mentions_and_leads_with_symptoms_1_and_2(world):
    client = FakeChat([_echo("ELIGIBLE", "제99조와 Q77을 본다.")])
    code, md, js = _run(world, client)
    assert code == 0
    first = md.splitlines()[:2]
    assert first[0].startswith("징후 1") and "다른 조합 0개" in first[0]
    assert first[1].startswith("징후 2") and "검색 밖 언급이 붙은 하위 질의" in first[1]
    s = js["symptoms"]
    assert s["A"] == s["B"] == s["C"] == s["D"] == 0
    assert s["E"] == s["total_queries"] > 0  # 제99조 · Q77은 어느 하위 질의 검색에도 없다
    assert s["zones"]["rule"] == "통과" and s["zones"]["outside"] == "통과"
    assert s["mention_law"] == [s["total_queries"], s["total_queries"]]
    assert "## 3. 검색 밖 언급이 붙은 하위 질의 전부" in md and "제99조 · Q77" in md
    assert js["first_run"]["calls"] > 0  # 캐시가 빈 실행이라 LLM을 불렀다
    # 근거 원문은 JSON에서 길이와 해시로 줄어든다
    ev = js["cells"][0]["answer"]["checklist"][0]["citations"][0]
    assert "text" not in ev and ev["text_len"] > 0 and len(ev["text_sha256"]) == 12
    assert "## 4. 응답 한 개 전문" in md and "```text" in md


def test_report_says_so_when_no_outside_mention_was_ever_flagged(world):
    code, md, js = _run(world, FakeChat([_echo("ELIGIBLE", "문맥대로다.")]))
    assert code == 0
    s = js["symptoms"]
    assert s["E"] == 0 and s["zones"]["outside"] == "다시 잰다"
    assert "표시가 한 번도 안 붙었다" in md


def test_report_exits_one_when_a_route_verdict_differs_from_the_recount(world, monkeypatch):
    real = agg.aggregate

    def wrong(plans, verdicts):
        out = real(plans, verdicts)
        out.general.verdict = "INELIGIBLE" if out.general.verdict != "INELIGIBLE" else "ELIGIBLE"
        return out

    monkeypatch.setattr(agg, "aggregate", wrong)
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1
    assert js["symptoms"]["B"] >= 1 and js["symptoms"]["zones"]["rule"] == "미완"
    assert "경로 판정이 측정 코드와 다른 것 (B)" in md


def test_report_exits_one_when_an_evidence_text_differs_from_chunks(world, monkeypatch):
    real = agg.read_texts
    monkeypatch.setattr(
        agg, "read_texts", lambda *a, **k: {k_: v + "!" for k_, v in real(*a, **k).items()}
    )
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1
    assert js["symptoms"]["D"] >= 1 and js["symptoms"]["zones"]["outside"] == "미완"
    assert "원문이 다르다" in md


def test_report_exits_one_when_the_rule_check_finds_a_mismatch(world):
    code, md, js = _run(world, FakeChat([_echo()]), combos=lambda: (279_936, 2))
    assert code == 1 and js["symptoms"]["A"] == 2
    assert "다른 조합 2개" in md.splitlines()[0]


def test_report_exits_one_and_lists_the_query_whose_call_failed(world):
    """호출이 실패한 하위 질의는 UNVERIFIABLE로 세지만 측정은 미완이고 리포트가 적는다."""
    code, md, js = _run(world, FakeChat([RuntimeError("boom"), _echo()]))
    s = js["symptoms"]
    assert code == 1
    assert len(s["missing"]) >= 1 and s["zones"]["rule"] == s["zones"]["outside"] == "미완"
    assert "호출이 실패해 판정이 없는 하위 질의" in md and "boom" in md


def test_report_checks_each_carried_link_kind(world):
    code, md, js = _run(world, FakeChat([_echo()]), status={"law": 200, "faq": 404})
    s = js["symptoms"]
    assert code == 0  # 징후 4가 미완이어도 exit 1은 징후 1·2만이다
    assert {k: v["status"] for k, v in s["links"].items()} == {"law": 200, "faq": 404}
    assert s["zones"]["links"] == "미완" and "404" in md


def test_second_run_reads_the_cache_and_is_recorded(world):
    client = FakeChat([_echo()])
    _, _, first = _run(world, client)
    assert first["first_run"]["calls"] > 0 and first["second_run"] is None
    # 두 번째 실행: 같은 캐시 · 같은 프롬프트 → 호출 0
    again = FakeChat([_echo()])
    _, md, second = _run(world, again)
    assert again.calls == [] and second["second_run"]["calls"] == 0
    assert second["first_run"]["calls"] == first["first_run"]["calls"]
    assert vr.system_sha() == second["system_sha"]
