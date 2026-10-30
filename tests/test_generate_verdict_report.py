import dataclasses
import json
import re

import pytest

from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate import verdict_report as vr
from cheongyak_rag.retrieval import axes
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_axes import _load_chunks, _notice, _version

LABEL = re.compile(r"^\[([^\]]+)\] ", re.M)
BASELINE = {
    "source": "테스트", "system_sha": "92f338a4", "model": "m", "total": 135,
    "eligible_empty": 7, "eligible_full_nofield": 13, "decisive_full": 10,
    "decisive_full_n": 12, "forced": 0, "ineligible_full_nofield": 5,
    "eligible_partial_nofield": 12, "first_run_usd": 0.93, "first_run_calls": 135,
    "distribution": {},
}  # fmt: skip


def _echo(verdict="ELIGIBLE"):
    def reply(kw):
        labels = LABEL.findall(kw["messages"][1]["content"])
        body = {
            "verdict": verdict, "reason": "문맥대로다.", "conditions": [], "need_info": [],
            "citations": labels[:1],
        }  # fmt: skip
        return json.dumps(body, ensure_ascii=False)

    return reply


@pytest.fixture
def world(pg_engine, tmp_path):
    """공고 둘(7축이 켜지는 것 · 3축만 켜지는 것) + chunks + 표본 JSON + 프로필 3종."""
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
    baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
    return {
        "engine": pg_engine,
        "samples_json": samples,
        "profiles_dir": profiles,
        "baseline_json": baseline,
        "root": tmp_path,
    }


def _run(world, client, *extra, name="out"):
    root = world["root"]
    code = vr.main(
        ["--report", *extra],
        engine=world["engine"], embedder=FakeEmbedder(dim=1536), client=client,
        cache_path=root / "cache.jsonl", samples_json=world["samples_json"],
        profiles_dir=world["profiles_dir"], baseline_json=world["baseline_json"],
        out_md=root / f"{name}.md", out_json=root / f"{name}.json", sleep=lambda s: None,
    )  # fmt: skip
    return (
        code,
        (root / f"{name}.md").read_text("utf-8"),
        json.loads((root / f"{name}.json").read_text("utf-8")),
    )


# ── 구간 ─────────────────────────────────────────────────────────────────


def test_zone_run_follows_the_plan_bands():
    ok = {"out_of_enum": 0, "off_called": 0, "no_cite": 0, "bad_label": 0, "cell_errors": 0}
    assert vr.zone_run(missing=0, transient=False, **ok) == "통과"
    assert vr.zone_run(missing=2, transient=True, **ok) == "다시 잰다"
    assert vr.zone_run(missing=2, transient=False, **ok) == "미완"  # 일시 오류가 아니다
    assert vr.zone_run(missing=3, transient=True, **ok) == "미완"
    for k in ok:
        assert vr.zone_run(missing=0, transient=False, **{**ok, k: 1}) == "미완"


def test_zone_jw_follows_the_plan_bands():
    assert vr.zone_jw(0, 0, 0, 0) == "통과"
    assert vr.zone_jw(0, 0, 1, 0) == "다시 잰다" and vr.zone_jw(0, 0, 2, 0) == "다시 잰다"
    assert vr.zone_jw(0, 0, 3, 0) == "미완"
    assert vr.zone_jw(1, 0, 0, 0) == "미완" and vr.zone_jw(0, 1, 0, 0) == "미완"
    assert vr.zone_jw(0, 0, 0, 1) == "미완"  # 셀 전체가 실패했으면 못 잰 것이다


def test_other_zone_bands():
    assert [vr.zone_loss(n) for n in (0, 1)] == ["통과", "미완"]
    assert [vr.zone_decisive(n) for n in (12, 10, 9, 6, 5)] == [
        "통과", "통과", "다시 잰다", "다시 잰다", "미완"
    ]  # fmt: skip
    assert vr.zone_cost(0, 1.0, 0, False) == "통과"
    assert vr.zone_cost(0, 1.0, None, False) == "미측정"
    assert (
        vr.zone_cost(0, 1.0, 3, False) == "다시 잰다" and vr.zone_cost(0, 1.0, 4, False) == "미완"
    )
    assert (
        vr.zone_cost(1, 1.0, 0, False) == "다시 잰다"
        and vr.zone_cost(3, 1.0, 0, False) == "다시 잰다"
    )
    assert vr.zone_cost(4, 1.0, 0, False) == "미완"
    assert vr.zone_cost(0, 3.1, 0, False) == "미완" and vr.zone_cost(0, 0.1, 0, True) == "미완"
    assert vr.zone_cost(0, 0.1, 0, False, dist_same=False) == "미완"


# ── 리포트 ───────────────────────────────────────────────────────────────


def test_report_has_all_six_symptoms_and_every_sample(world):
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 0
    for n in "123456":
        assert re.search(rf"^\| {n}\. ", md, re.M)
    assert "## 2. 판정값 분포" in md and "## 3. guard가 바꾼 판정 전부" in md
    assert "## 4. 표본" in md and "## 5. 열린 질문" in md
    assert len(js["cells"]) == 6  # 공고 2건 × 프로필 3종
    assert all(f"× `{p}`" in md for p in ("full", "partial", "empty"))
    assert set(js["symptoms"]["zones"]) == {"jw", "loss", "decisive", "run", "cost"}
    first = md.splitlines()[0]
    assert (
        first.startswith("빈 프로필 ELIGIBLE 0(guard 전 ") and "칸 없는 4개 축 ELIGIBLE 0(" in first
    )


def test_guard_clears_the_empty_profile_and_the_report_shows_what_it_was(world):
    code, md, js = _run(world, FakeChat([_echo("ELIGIBLE")]))
    s = js["symptoms"]
    assert (
        s["empty_eligible"] == [] and s["empty_eligible_pre"] > 0
    )  # guard 전 ELIGIBLE이 guard 후 0
    assert s["nofield_eligible"] == [] and s["nofield_eligible_pre"] > 0
    assert s["zones"]["jw"] == "통과" and s["zones"]["loss"] == "통과" and code == 0
    assert len(s["guarded"]) > 0 and "→" in md  # 분포 표에 guard 전→후가 보인다
    assert "모델이 쓴 이유 원문" in md and "guard가 넣은 필요한 정보" in md


def test_report_exits_1_when_an_empty_profile_still_gets_eligible(world, monkeypatch):
    monkeypatch.setattr(vd, "eligible_guard", lambda axis_id, profile: True)  # guard가 빠졌다
    code, md, js = _run(world, FakeChat([_echo("ELIGIBLE")]))
    assert js["symptoms"]["zones"]["jw"] == "미완" and code == 1
    assert len(js["symptoms"]["empty_eligible"]) > 0 and "## 6. 어긋난 곳" in md


def test_report_exits_1_when_the_guard_changes_a_verdict_with_all_fields_present(
    world, monkeypatch
):
    monkeypatch.setattr(vd, "eligible_guard", lambda axis_id, profile: False)  # 너무 넓다
    code, md, js = _run(world, FakeChat([_echo("ELIGIBLE")]))
    s = js["symptoms"]
    assert s["empty_eligible"] == [] and s["nofield_eligible"] == []  # 징후 1은 통과다
    assert len(s["loss"]) > 0 and s["zones"]["loss"] == "미완" and code == 1


def test_off_axis_call_is_measured_independently_and_exits_1(world, monkeypatch):
    orig = axes.plan_from_facts

    def always_rewin(facts):
        return [
            dataclasses.replace(p, on=True, queries=[axes.Q_REWIN]) if p.id == "rewin" else p
            for p in orig(facts)
        ]

    monkeypatch.setattr(axes, "plan_from_facts", always_rewin)
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1 and js["symptoms"]["zones"]["run"] == "미완"
    assert len(js["symptoms"]["off_called"]) > 0 and "꺼진 축 호출" in md


def test_missing_label_is_counted_by_the_report_own_sql(world):
    from sqlalchemy import text

    # 측정 코드의 SQL이 verdict.py 대조와 따로 라벨을 센다
    real = vr.label_exists
    with world["engine"].begin() as conn:
        conn.execute(text("DELETE FROM chunks WHERE source = 'faq'"))
    assert real(world["engine"], "286965", "Q1") is False
    assert real(world["engine"], "286965", "제2조") is True
    assert real(world["engine"], "999", "제2조") is False


def _vrow(axis, verdict, **kw):
    row = {
        "axis": axis, "verdict": verdict, "citations": ["제1조"], "missing_labels": [],
        "invalid_citations": [], "forced": False, "no_context": False, "error": None,
        "guarded": False, "original_verdict": None,
    }  # fmt: skip
    return {**row, **kw}


def _cell(profile, *verdicts):
    on = [
        "homeless",
        "account",
        "residence",
        "income_asset",
        "rewin",
        "householder",
        "special_type",
    ]
    return {"profile": profile, "on_sql": on, "verdicts": list(verdicts)}


def _guarded(axis, **kw):
    return _vrow(axis, "NEED_INFO", guarded=True, original_verdict="ELIGIBLE", **kw)


def test_symptoms_count_by_profile_and_axis():
    m = {
        "cells": [
            _cell(
                "empty",
                _vrow("homeless", "ELIGIBLE"),
                _guarded("homeless"),
                _vrow("homeless", "NEED_INFO"),
            ),
            _cell(
                "partial",
                _vrow("homeless", "INELIGIBLE"),
                _vrow("account", "ELIGIBLE", citations=[]),
                _vrow("rewin", "ELIGIBLE", missing_labels=["제9조", "제8조"]),
                _guarded("residence"),
            ),
            _cell(
                "full",
                _vrow("homeless", "CONDITIONAL"),
                _vrow("account", "NEED_INFO"),
                _vrow("residence", "ELIGIBLE"),
                _guarded("rewin"),
                _guarded("householder"),
                _vrow("special_type", "INELIGIBLE"),
            ),
        ],
        "cell_errors": [],
        "stop": None,
    }
    s = vr.symptoms(m)
    assert s["total"] == 13
    assert (len(s["empty_eligible"]), s["empty_eligible_pre"]) == (1, 2)  # guard 후 · 전
    assert (len(s["nofield_eligible"]), s["nofield_eligible_pre"]) == (1, 2)  # full의 칸 없는 축
    assert len(s["loss"]) == 1  # full의 칸이 다 있는 축을 guard가 바꿨다
    assert (s["backed_n"], len(s["decisive"])) == (2, 1)  # NEED_INFO는 판정을 낸 것이 아니다
    assert s["ineligible_nofield"] == 1 and len(s["guarded"]) == 4
    assert (s["partial_nofield_eligible"], s["partial_nofield_eligible_pre"]) == (1, 2)
    assert len(s["no_cite"]) == 1 and len(s["bad_label"]) == 1 and s["n_bad_labels"] == 2
    assert s["zones"]["run"] == "미완" and s["zones"]["jw"] == "미완"
    assert s["zones"]["loss"] == "미완" and s["dist_same"] is None
    empty = vr.symptoms({"cells": [], "cell_errors": [], "stop": None})
    assert empty["zones"]["run"] == "미완" and empty["zones"]["jw"] == "미완"


def test_distribution_compares_the_verdict_before_the_guard():
    cells = [_cell("full", _vrow("residence", "ELIGIBLE"), _guarded("rewin"))]
    pre = {"full": {"residence": {"ELIGIBLE": 1}, "rewin": {"ELIGIBLE": 1}}}
    post = {"full": {"residence": {"ELIGIBLE": 1}, "rewin": {"NEED_INFO": 1}}}
    assert vr.distribution(cells, pre=True) == pre
    assert vr.distribution(cells, pre=False) == post
    m = {"cells": cells, "cell_errors": [], "stop": None}
    assert vr.symptoms(m, {"distribution": pre})["dist_same"] is True
    assert vr.symptoms(m, {"distribution": post})["dist_same"] is False


def test_baseline_missing_a_key_the_report_reads_is_a_setup_error(world):
    bad = {k: v for k, v in BASELINE.items() if k != "decisive_full_n"}
    world["baseline_json"].write_text(json.dumps(bad), encoding="utf-8")
    client = FakeChat([_echo()])
    code = vr.main(
        ["--report"], engine=world["engine"], client=client,
        samples_json=world["samples_json"], profiles_dir=world["profiles_dir"],
        baseline_json=world["baseline_json"],
    )  # fmt: skip
    assert code == 3 and client.calls == []  # 호출 비용을 쓰기 전에 멈춘다


def test_missing_baseline_is_a_setup_error(world):
    world["baseline_json"].unlink()
    code = vr.main(
        ["--report"], engine=world["engine"], client=FakeChat([_echo()]),
        samples_json=world["samples_json"], profiles_dir=world["profiles_dir"],
        baseline_json=world["baseline_json"],
    )  # fmt: skip
    assert code == 3


def test_committed_baseline_is_readable_and_matches_the_plan_numbers():
    base = vr.load_baseline(vr.BASELINE_JSON)
    assert (base["eligible_empty"], base["eligible_full_nofield"]) == (7, 13)
    assert base["system_sha"] == vr.system_sha() == "92f338a4"  # 프롬프트를 고치지 않았다
    assert (
        sum(n for a in base["distribution"].values() for x in a.values() for n in x.values()) == 135
    )


def test_label_missing_from_chunks_makes_the_report_incomplete(world, monkeypatch):
    # verdict.py의 대조는 통과시키고 측정 코드의 SQL이 따로 잡는지 본다
    from cheongyak_rag.generate import verdict as vd

    monkeypatch.setattr(
        vd, "present_in_chunks", lambda engine, mst, chunks: {c.label for c in chunks}
    )
    monkeypatch.setattr(vr, "label_exists", lambda *a: False)
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1 and js["symptoms"]["zones"]["run"] == "미완"
    assert js["symptoms"]["n_bad_labels"] > 0 and "DB에 없는 라벨" in md


def test_budget_stops_the_run_and_exits_1(world):
    code, md, js = _run(world, FakeChat([_echo()]), "--budget-usd", "0.0001")
    assert code == 1 and js["stop"][0] == "budget" and "비용 상한에서 멈춤" in md
    zones = js["symptoms"]["zones"]
    assert zones["jw"] == zones["loss"] == "미완"  # 안 돈 셀을 못 쟀는데 통과로 찍지 않는다
    assert len(js["cells"]) == 1 and js["first_run"] is None


def test_hard_error_stops_the_run(world):
    from cheongyak_rag.generate.answer import HardApiError

    code, md, js = _run(world, FakeChat([HardApiError("insufficient_quota")]))
    assert code == 1 and js["stop"][0] == "hard" and "인증·쿼터 오류로 멈춤" in md


def test_second_run_costs_no_calls_and_keeps_the_first_run(world):
    code1, _, js1 = _run(world, FakeChat([_echo()]))
    same = {**BASELINE, "distribution": vr.distribution(js1["cells"], pre=True)}
    world["baseline_json"].write_text(json.dumps(same), encoding="utf-8")  # 같은 응답을 읽은 기준
    client = FakeChat([_echo("INELIGIBLE")])
    code2, md2, js2 = _run(world, client)
    assert (code1, code2) == (0, 0) and client.calls == []
    assert (
        js2["second_run"]["calls"] == 0 and js2["first_run"]["calls"] == js1["usage"]["calls"] > 0
    )
    assert js2["symptoms"]["dist_same"] is True
    assert js2["symptoms"]["zones"]["cost"] == "미완"  # 첫 실행이 호출했다 — 기대값은 호출 0
    assert "두 번째 실행 호출 0" in md2 and "PR #12와 칸마다 같다" in md2


def test_cost_passes_when_the_first_run_reads_only_the_cache(world):
    """프롬프트를 안 고치면 첫 실행도 캐시만 읽는다 — 실제 측정이 기대하는 모양."""
    _, _, warm = _run(world, FakeChat([_echo()]), name="warm")
    same = {**BASELINE, "distribution": vr.distribution(warm["cells"], pre=True)}
    world["baseline_json"].write_text(json.dumps(same), encoding="utf-8")
    first = FakeChat([_echo("INELIGIBLE")])
    _, _, js1 = _run(world, first, name="out")
    again = FakeChat([_echo("INELIGIBLE")])
    code, md, js2 = _run(world, again, name="out")
    assert first.calls == again.calls == [] and js1["first_run"]["calls"] == 0
    assert js1["symptoms"]["zones"]["cost"] == "미측정"
    assert code == 0 and js2["symptoms"]["zones"]["cost"] == "통과"


@pytest.mark.parametrize("text", ["<<<<<<< HEAD", "[]"])
def test_unreadable_previous_record_stops_before_any_call(world, text):
    root = world["root"]
    (root / "out.json").write_text(text, encoding="utf-8")
    client = FakeChat([_echo()])
    code = vr.main(
        ["--report"], engine=world["engine"], embedder=FakeEmbedder(dim=1536), client=client,
        cache_path=root / "cache.jsonl", samples_json=world["samples_json"],
        profiles_dir=world["profiles_dir"], baseline_json=world["baseline_json"],
        out_md=root / "out.md", out_json=root / "out.json", sleep=lambda s: None,
    )  # fmt: skip
    assert code == 3 and client.calls == []
    assert (root / "out.json").read_text(encoding="utf-8") == text  # 첫 실행 기록을 덮지 않는다


def test_missing_profile_file_is_a_setup_error(world):
    (world["profiles_dir"] / "full.json").unlink()
    code = vr.main(
        ["--report"], engine=world["engine"], client=FakeChat([_echo()]),
        samples_json=world["samples_json"], profiles_dir=world["profiles_dir"],
        baseline_json=world["baseline_json"],
    )  # fmt: skip
    assert code == 3


# ── attach_runs: 첫 실행 · 두 번째 실행을 가르는 규칙 ────────────────────


def _usage(calls, usd=1.0):
    return {"calls": calls, "retries": 0, "cache_hits": 0, "input_tokens": 10,
            "output_tokens": 1, "usd": usd, "cell_median_s": 1.0, "cell_max_s": 1.0}  # fmt: skip


def _rec(calls, *, sha="a", model="m", stop=None, errors=(), usd=1.0):
    return {"usage": _usage(calls, usd), "stop": stop, "cell_errors": list(errors),
            "system_sha": sha, "model": model, "symptoms": {"zones": {}}}  # fmt: skip


def _attached(run, prev=None):
    vr.attach_runs(run, prev)
    return run


def test_second_run_needs_the_same_prompt_and_model():
    first = _attached(_rec(135))
    assert first["first_run"]["calls"] == 135 and first["second_run"] is None
    same = _attached(_rec(0), first)
    assert same["second_run"]["calls"] == 0 and same["first_run"]["calls"] == 135
    assert same["symptoms"]["zones"]["cost"] == "미완"  # 첫 실행 호출이 4 이상이다
    cached = _attached(_rec(0, usd=0), _attached(_rec(0, usd=0)))
    assert cached["symptoms"]["zones"]["cost"] == "통과"
    other = _attached(
        _rec(0, sha="b"), first
    )  # 프롬프트가 바뀐 뒤 캐시만 읽은 실행은 두 번째 실행이 아니다
    assert other["second_run"] is None and other["first_run"]["calls"] == 0
    assert _attached(_rec(0, model="n"), first)["second_run"] is None


def test_stopped_run_keeps_the_old_first_run_and_costs_add_up():
    first = _attached(_rec(135, usd=0.9))
    stopped = _attached(_rec(50, stop=("budget", "x"), usd=2.0), first)
    assert stopped["first_run"]["calls"] == 135 and stopped["second_run"] is None
    assert stopped["symptoms"]["zones"]["cost"] == "미완"
    # 첫 실행이 멈췄으면 이어 받은 실행의 비용에 멈춘 실행의 비용을 더한다
    s1 = _attached(_rec(50, stop=("budget", "x"), usd=2.0))
    assert s1["first_run"] is None
    done = _attached(_rec(85, usd=1.5), s1)
    assert done["first_run"]["calls"] == 135 and done["first_run"]["usd"] == 3.5
    assert done["symptoms"]["zones"]["cost"] == "미완"  # 합계가 $3을 넘는다


def test_run_with_cell_errors_is_not_a_first_run():
    errs = [{"notice": "n", "profile": "full", "error": "x"}]
    run = _attached(_rec(100, errors=errs))
    assert run["first_run"] is None and run["symptoms"]["zones"]["cost"] == "미완"


def test_rerun_with_as_many_calls_is_still_a_second_run():
    first = _attached(_rec(135))
    again = _attached(_rec(135), first)  # 캐시 키가 흔들려 호출이 줄지 않았다
    assert again["second_run"]["calls"] == 135 and again["first_run"]["calls"] == 135
    assert again["symptoms"]["zones"]["cost"] == "미완"


def test_run_with_missing_verdicts_is_not_a_first_run():
    run = _rec(100)
    run["symptoms"]["missing"] = [({}, {})]  # 판정을 못 낸 하위 질의 하나
    run = _attached(run)
    assert run["first_run"] is None and run["symptoms"]["zones"]["cost"] == "미완"


def test_label_recheck_db_error_is_a_cell_error_not_a_lost_report(world, monkeypatch):
    from sqlalchemy.exc import OperationalError

    real, n = vr.label_exists, {"i": 0}

    def flaky(*a):
        n["i"] += 1
        if n["i"] == 1:
            raise OperationalError("SELECT", {}, Exception("연결 끊김"))
        return real(*a)

    monkeypatch.setattr(vr, "label_exists", flaky)
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1 and len(js["cell_errors"]) == 1 and len(js["cells"]) == 5
    assert "OperationalError" in js["cell_errors"][0]["error"]


def test_unexpected_exception_in_one_cell_is_recorded_and_the_run_continues(world, monkeypatch):
    from cheongyak_rag.generate import verdict as vd

    real = vd.judge
    n = {"i": 0}

    def flaky(*a, **kw):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("임베딩 실패")
        return real(*a, **kw)

    monkeypatch.setattr(vd, "judge", flaky)
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 1 and len(js["cell_errors"]) == 1 and len(js["cells"]) == 5
    assert "RuntimeError" in js["cell_errors"][0]["error"]
