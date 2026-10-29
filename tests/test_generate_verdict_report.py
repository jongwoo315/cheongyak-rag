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


def test_missing_profile_file_is_a_setup_error(world):
    (world["profiles_dir"] / "full.json").unlink()
    code = vr.main(
        ["--report"], engine=world["engine"], client=FakeChat([_echo()]),
        samples_json=world["samples_json"], profiles_dir=world["profiles_dir"],
    )  # fmt: skip
    assert code == 3
