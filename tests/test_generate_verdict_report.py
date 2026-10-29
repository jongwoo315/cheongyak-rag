import dataclasses
import json
import re

import pytest

from cheongyak_rag.generate import verdict_report as vr
from cheongyak_rag.retrieval import axes
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_axes import _load_chunks, _notice, _version

LABEL = re.compile(r"^\[([^\]]+)\] ", re.M)


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
    (profiles / "full.json").write_text(
        json.dumps({"birth_date": "1985-04-10", "is_household_head": True}), encoding="utf-8"
    )
    (profiles / "partial.json").write_text('{"birth_date": "1985-04-10"}', encoding="utf-8")
    (profiles / "empty.json").write_text("{}", encoding="utf-8")
    return {
        "engine": pg_engine,
        "samples_json": samples,
        "profiles_dir": profiles,
        "root": tmp_path,
    }


def _run(world, client, *extra, name="out"):
    root = world["root"]
    code = vr.main(
        ["--report", *extra],
        engine=world["engine"], embedder=FakeEmbedder(dim=1536), client=client,
        cache_path=root / "cache.jsonl", samples_json=world["samples_json"],
        profiles_dir=world["profiles_dir"], out_md=root / f"{name}.md",
        out_json=root / f"{name}.json", sleep=lambda s: None,
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


def test_other_zone_bands():
    assert [vr.zone_count(n) for n in (0, 1, 2, 3)] == ["통과", "다시 잰다", "다시 잰다", "미완"]
    assert [vr.zone_decisive(n) for n in (12, 10, 9, 6, 5)] == [
        "통과", "통과", "다시 잰다", "다시 잰다", "미완"
    ]  # fmt: skip
    assert [vr.zone_forced(r) for r in (0.0, 0.2, 0.21, 0.5, 0.51)] == [
        "통과", "통과", "다시 잰다", "다시 잰다", "미완"
    ]  # fmt: skip
    assert vr.zone_cost(1.0, 0, False) == "통과" and vr.zone_cost(1.0, None, False) == "미측정"
    assert vr.zone_cost(1.0, 3, False) == "다시 잰다" and vr.zone_cost(1.0, 4, False) == "미완"
    assert vr.zone_cost(3.1, 0, False) == "미완" and vr.zone_cost(0.1, 0, True) == "미완"


# ── 리포트 ───────────────────────────────────────────────────────────────


def test_report_has_all_six_symptoms_and_every_sample(world):
    code, md, js = _run(world, FakeChat([_echo()]))
    assert code == 0
    for n in "123456":
        assert re.search(rf"^\| {n}\. ", md, re.M)
    assert "## 2. 판정값 분포" in md and "## 5. 열린 질문" in md
    assert len(js["cells"]) == 6  # 공고 2건 × 프로필 3종
    assert md.splitlines()[0].startswith("공고 2건 × 프로필 3종, 켜진 하위 질의")
    assert all(f"× `{p}`" in md for p in ("full", "partial", "empty"))
    assert set(js["symptoms"]["zones"]) == {"run", "empty", "nofield", "decisive", "forced", "cost"}


def test_report_flags_decided_verdicts_on_the_empty_profile(world):
    code, md, js = _run(world, FakeChat([_echo("ELIGIBLE")]))
    assert js["symptoms"]["zones"]["empty"] == "미완"  # 빈 프로필의 ELIGIBLE이 3개를 넘는다
    assert js["symptoms"]["zones"]["run"] == "통과" and code == 0


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


def test_budget_stops_the_run_and_exits_1(world):
    code, md, js = _run(world, FakeChat([_echo()]), "--budget-usd", "0.0001")
    assert code == 1 and js["stop"][0] == "budget" and "비용 상한에서 멈춤" in md
    assert len(js["cells"]) == 1 and js["first_run"] is None


def test_hard_error_stops_the_run(world):
    from cheongyak_rag.generate.answer import HardApiError

    code, md, js = _run(world, FakeChat([HardApiError("insufficient_quota")]))
    assert code == 1 and js["stop"][0] == "hard" and "인증·쿼터 오류로 멈춤" in md


def test_second_run_costs_no_calls_and_keeps_the_first_run(world):
    code1, _, js1 = _run(world, FakeChat([_echo()]))
    client = FakeChat([_echo("INELIGIBLE")])
    code2, md2, js2 = _run(world, client)
    assert (code1, code2) == (0, 0) and client.calls == []
    assert (
        js2["second_run"]["calls"] == 0 and js2["first_run"]["calls"] == js1["usage"]["calls"] > 0
    )
    assert js2["symptoms"]["zones"]["cost"] == "통과"
    assert "두 번째 실행 호출 0" in md2


@pytest.mark.parametrize("text", ["<<<<<<< HEAD", "[]"])
def test_unreadable_previous_record_stops_before_any_call(world, text):
    root = world["root"]
    (root / "out.json").write_text(text, encoding="utf-8")
    client = FakeChat([_echo()])
    code = vr.main(
        ["--report"], engine=world["engine"], embedder=FakeEmbedder(dim=1536), client=client,
        cache_path=root / "cache.jsonl", samples_json=world["samples_json"],
        profiles_dir=world["profiles_dir"], out_md=root / "out.md", out_json=root / "out.json",
        sleep=lambda s: None,
    )  # fmt: skip
    assert code == 3 and client.calls == []
    assert (root / "out.json").read_text(encoding="utf-8") == text  # 첫 실행 기록을 덮지 않는다


def test_missing_profile_file_is_a_setup_error(world):
    (world["profiles_dir"] / "full.json").unlink()
    code = vr.main(
        ["--report"], engine=world["engine"], client=FakeChat([_echo()]),
        samples_json=world["samples_json"], profiles_dir=world["profiles_dir"],
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
    assert same["symptoms"]["zones"]["cost"] == "통과"
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
