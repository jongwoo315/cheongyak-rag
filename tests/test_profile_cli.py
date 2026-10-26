"""CLI `python -m cheongyak_rag.profile_score`와 리포트 (#77 통과 기준 6)."""

import json
from datetime import date
from pathlib import Path

import pytest

from cheongyak_rag import profile, profile_score
from cheongyak_rag import profile_check as check
from cheongyak_rag.ingest import law_versions, notice
from tests.law_version_fakes import FAKE_OC, make_row
from tests.notice_fakes import make_notice

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "runs" / "77" / "sample-profiles.json"
CURRENT = ("286965", date(2026, 6, 15), date(2026, 6, 15))
OLD = ("265605", date(2024, 10, 1), date(2024, 9, 30))

COMPLETE = {
    "birth_date": "1988-03-15",
    "married": True,
    "marriage_date": "2016-05-20",
    "homeless_now": True,
    "ever_owned": False,
    "is_household_head": True,
    "children_unmarried": 1,
    "children_30plus_1y": 0,
    "ascendants_3y": 1,
    "ascendants_any_owner": False,
    "savings_join_date": "2012-07-01",
    "spouse_has_savings": True,
    "spouse_savings_join_date": "2015-02-10",
}


def load(engine, versions, *dates):
    rows = [law_versions.to_row(make_row(m, e, p), FAKE_OC) for m, e, p in versions]
    notice.upsert(engine, law_versions.LAW_VERSIONS, rows)
    rows = [
        notice.to_notice_row(make_notice(i, de=d.isoformat())).row
        for i, d in enumerate(dates, start=1)
    ]
    notice.upsert(engine, notice.NOTICES, rows)


@pytest.fixture
def profile_file(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(COMPLETE), encoding="utf-8")
    return path


def test_as_of_prints_judgement_values_scores_and_missing(profile_file, capsys):
    assert profile_score.main(["--profile", str(profile_file), "--as-of", "2026-10-23"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"as_of", "values", "scores", "missing"}
    assert out["scores"]["total"] == {"lo": 59, "hi": 59}
    assert out["scores"]["homeless"] == {"lo": 22, "hi": 22}
    assert out["values"]["homeless_period"]["value"] == "10년5월4일"
    assert out["values"]["homeless_period"]["basis"].startswith("별표1")
    assert out["missing"] == []


def test_as_of_partial_profile_prints_ranges(tmp_path, capsys):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({**COMPLETE, "savings_join_date": None}), encoding="utf-8")
    assert profile_score.main(["--profile", str(path), "--as-of", "2026-10-23"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["missing"] == ["savings_join_date"]
    assert out["scores"]["savings"]["lo"] < out["scores"]["savings"]["hi"]
    assert out["values"]["savings_period"]["value"] is None


def test_bad_profile_exits_nonzero_with_message(tmp_path, capsys):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"birth": "1988-03-15"}), encoding="utf-8")
    assert profile_score.main(["--profile", str(path), "--as-of", "2026-10-23"]) == 2
    assert "알 수 없는 입력 칸" in capsys.readouterr().err


def test_needs_a_date_source(profile_file):
    with pytest.raises(SystemExit):
        profile_score.main(["--profile", str(profile_file)])


def test_notice_uses_its_announcement_date(pg_engine, profile_file, capsys):
    load(pg_engine, [CURRENT], date(2026, 9, 1))
    argv = ["--profile", str(profile_file), "--notice", "2026000001:2026000001"]
    assert profile_score.main(argv, engine=pg_engine) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["as_of"] == "2026-09-01"
    assert out["notice"] == {
        "house_manage_no": "2026000001",
        "pblanc_no": "2026000001",
        "rcrit_pblanc_de": "2026-09-01",
        "mst": "286965",
    }


def test_notice_with_other_law_version_is_not_computed(pg_engine, profile_file, capsys):
    """별표 1은 MST 286965 것만 받았다. 다른 버전이 걸린 공고는 계산하지 않고 그 사실을 낸다."""
    load(pg_engine, [CURRENT, OLD], date(2026, 3, 1))  # 2026-03-01에는 2024-10-01 버전이 유효하다
    argv = ["--profile", str(profile_file), "--notice", "2026000001:2026000001"]
    assert profile_score.main(argv, engine=pg_engine) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["computed"] is False
    assert out["mst"] == "265605" and out["expected_mst"] == "286965"
    assert "scores" not in out


def test_notice_without_version_is_not_computed(pg_engine, profile_file, capsys):
    load(pg_engine, [CURRENT], date(2026, 1, 1))  # 어느 버전의 시행일보다 앞선 공고
    argv = ["--profile", str(profile_file), "--notice", "2026000001:2026000001"]
    assert profile_score.main(argv, engine=pg_engine) == 1
    assert json.loads(capsys.readouterr().out)["mst"] is None


def test_unknown_notice_exits_one(pg_engine, profile_file, capsys):
    load(pg_engine, [CURRENT], date(2026, 9, 1))
    argv = ["--profile", str(profile_file), "--notice", "9:9"]
    assert profile_score.main(argv, engine=pg_engine) == 1
    assert "공고를 찾지 못했다" in capsys.readouterr().err


# ── 샘플 프로필 ──────────────────────────────────────────────────────────


def samples():
    return json.loads(SAMPLES.read_text(encoding="utf-8"))


def test_sample_profiles_are_complete_one_blank_and_empty():
    by_name = {s["name"]: profile.Profile.from_dict(s["profile"]) for s in samples()}
    assert len(by_name) == 3
    full, no_date, empty = by_name.values()
    T = date(2026, 10, 23)
    assert profile.score(full, T).missing == ()
    assert profile.score(no_date, T).missing == ("savings_join_date",)
    assert profile.score(empty, T).missing == check.FIELDS


# ── 리포트 ───────────────────────────────────────────────────────────────


@pytest.fixture
def paths(tmp_path):
    return {"run": tmp_path / "runs" / "last_run.json", "md": tmp_path / "docs" / "77.md"}


def report(engine, paths, *extra):
    argv = [
        "--report", "--samples", str(SAMPLES),
        "--run", str(paths["run"]), "--out", str(paths["md"]),
        "--soundness-n", "30", "--tightness-bases", "1", *extra,
    ]  # fmt: skip
    return profile_score.main(argv, engine=engine)


@pytest.fixture
def fast_tightness(monkeypatch):
    stub = {"bases": 0, "seed": 0, "measured": 10, "tight": 10, "ratio": 1.0, "pairs": [],
            "loose": [], "skipped": {}}  # fmt: skip
    monkeypatch.setattr(check, "tightness", lambda **kw: stub)


def test_report_writes_run_and_markdown(pg_engine, paths):
    load(pg_engine, [CURRENT], date(2026, 8, 1), date(2026, 9, 1))
    assert report(pg_engine, paths) == 0
    run = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert run["table"]["mismatches"] == [] and run["table"]["rows"] == {
        "homeless": 16, "dependents": 7, "savings": 17
    }  # fmt: skip
    assert run["faq"]["matched"] == run["faq"]["cases"] == 11
    assert (run["faq170"]["matched"], run["faq170"]["rows"]) == (6, 6)
    assert run["soundness"]["violations"] == 0 and run["soundness"]["n"] == 30
    assert run["calc"] == {"notices": 2, "samples": 3, "ok": 6, "failed": 0, "failures": []}
    md = paths["md"].read_text(encoding="utf-8")
    first = md.splitlines()[0]
    assert "어긋난 칸 0개" in first and "11/11" in first and "위반 0건" in first and "6/6" in first
    for heading in (
        "점수표 원문 대조",
        "FAQ 사례",
        "soundness",
        "tightness",
        "공고별",
        "열린 질문",
    ):
        assert heading in md
    for q in (46, 151, 153, 154, 156, 157, 158, 159, 161, 162, 170):
        assert f"| {q} |" in md


def test_report_names_the_four_open_questions(pg_engine, paths, fast_tightness):
    load(pg_engine, [CURRENT], date(2026, 9, 1))
    report(pg_engine, paths)
    md = paths["md"].read_text(encoding="utf-8")
    assert md.count("### 열린 질문 ") >= 4
    assert "배우자 통장은 가입일 그대로" in md
    assert "2월 28일" in md


def test_report_exits_one_when_table_disagrees(pg_engine, paths, fast_tightness, monkeypatch):
    load(pg_engine, [CURRENT], date(2026, 9, 1))
    monkeypatch.setattr(profile, "HOMELESS_TABLE", ((0, 12, 3), *profile.HOMELESS_TABLE[1:]))
    assert report(pg_engine, paths) == 1
    run = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert len(run["table"]["mismatches"]) == 2
    assert "어긋난 칸 1개" in paths["md"].read_text(encoding="utf-8").splitlines()[0]


def test_report_exits_one_on_soundness_violation(pg_engine, paths, fast_tightness, monkeypatch):
    load(pg_engine, [CURRENT], date(2026, 9, 1))
    bad = {"n": 30, "seed": 1, "violations": 1, "examples": [], "avg_erased": 3.0}
    monkeypatch.setattr(check, "soundness", lambda *a, **kw: bad)
    assert report(pg_engine, paths) == 1


def test_report_counts_notices_on_other_law_versions_as_failures(pg_engine, paths, fast_tightness):
    load(pg_engine, [CURRENT, OLD], date(2026, 3, 1), date(2026, 9, 1))
    assert report(pg_engine, paths) == 1
    run = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert run["calc"]["failed"] == 3 and run["calc"]["ok"] == 3
    assert run["calc"]["failures"][0]["kind"] == "mst"
