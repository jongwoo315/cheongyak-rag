import json

import pytest
from sqlalchemy import text

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import trace_report as tr
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_generate_verdict import LABEL, _reply
from tests.test_retrieval_axes import _load_chunks, _notice, _version

KEY = "report-key"
FULL = {"birth_date": "1985-04-10", "marriage_date": "2012-05-20", "married": True}
PARTIAL = {"birth_date": "1985-04-10"}
EMPTY: dict = {}


def P(d):
    return prof.Profile.from_dict(d)


def _profiles():
    return {"full": P(FULL), "partial": P(PARTIAL), "empty": P(EMPTY)}


# ── 구간 · 순수 함수 ──────────────────────────────────────────────────────


def test_zone_rows_has_no_retry_band():
    assert tr.zone_rows(0, 0) == "통과"
    assert tr.zone_rows(1, 0) == "미완" and tr.zone_rows(0, 1) == "미완"


def test_zone_hide_bands():
    assert tr.zone_hide(0, 0, 0, False) == "통과"
    assert tr.zone_hide(0, 1, 0, False) == "다시 잰다"
    assert tr.zone_hide(0, 1, 0, True) == "미완"  # 다시 잰 뒤에도 D가 남았다
    assert tr.zone_hide(1, 0, 0, False) == "미완" and tr.zone_hide(0, 0, 1, False) == "미완"
    assert tr.zone_hide(1, 5, 0, False) == "미완"


def test_zone_calls_bands():
    assert tr.zone_calls(0, 0, True, False) == "통과"
    assert tr.zone_calls(0, None, True, False) == "미측정"
    assert tr.zone_calls(1, 0, True, False) == "다시 잰다"
    assert tr.zone_calls(2, 0, True, False) == "다시 잰다"
    assert tr.zone_calls(3, 0, True, False) == "다시 잰다"  # 경계: 1~3이 다시 잰다
    assert tr.zone_calls(4, 0, True, False) == "미완"
    assert tr.zone_calls(0, 0, False, False) == "미완"  # 분포가 다르다
    assert tr.zone_calls(0, 0, True, True) == "미완"  # 멈춘 실행
    assert tr.zone_calls(0, 2, True, False) == "판정 불가"  # plan에 구간이 없다


def test_date_forms_are_the_four_non_iso_shapes():
    forms = tr.date_forms(P({"marriage_date": "2012-05-20"}))
    assert forms == {
        "2012-05-20": ["2012년 5월 20일", "2012년 05월 20일", "2012.05.20", "2012/05/20"]
    }


def test_hide_replaces_every_iso_value_in_nested_objects():
    out = tr.hide({"a": ["x 2012-05-20 y", {"b": "1985-04-10"}], "n": 1}, P(FULL))
    assert out == {"a": ["x [프로필 값] y", {"b": "[프로필 값]"}], "n": 1}


def test_plain_sha_is_keyless_sha256_of_the_sorted_json():
    import hashlib

    p = P(PARTIAL)
    body = json.dumps(p.to_dict(), sort_keys=True).encode()
    assert tr.plain_sha(p) == hashlib.sha256(body).hexdigest()


# ── 가짜 행으로 징후를 잰다 ───────────────────────────────────────────────


def _q(profile="full", ok=True, notice="n1", checklist=1):
    return {
        "notice": notice, "profile": profile, "extra": False, "ok": ok, "seconds": 0.1,
        "answer": {"checklist": [{}] * checklist, "x": "y"} if ok else None,
        "verdicts": [],
    }  # fmt: skip


def _r(i, profile_hash=None, **kw):
    base = {
        "id": i, "house_manage_no": "n1", "pblanc_no": "n1",
        "profile_hash": profile_hash or "a" * 64,
        "status": "ok", "error": None, "verdict": "NEED_INFO", "seconds": 0.1,
        "steps": {"queries": [{}]}, "answer": {"checklist": [{}], "x": "y"}, "json": "{}",
        "size": 100,
    }  # fmt: skip
    return base | kw


def _hashes(queries):
    return {
        n: format(i + 1, "x") * 64
        for i, n in enumerate(dict.fromkeys(q["profile"] for q in queries))
    }


def _m(queries, rows):
    return {"base": 0, "queries": queries, "rows": rows, "stop": None}


def _sym(queries, rows, retry=False):
    return tr.symptoms(_m(queries, rows), _profiles(), {"cells": []}, ["n1"], retry)


def _good(queries):
    h = _hashes(queries)
    return [_r(i + 1, h[q["profile"]]) for i, q in enumerate(queries)]


def test_clean_rows_measure_zero_everywhere():
    qs = [_q("full"), _q("partial"), _q("full")]
    s = _sym(qs, _good(qs))
    assert (s["A"], s["B"], s["C"], s["D"], s["E"]) == (0, 0, 0, 0, 0)
    assert s["zones"]["rows"] == s["zones"]["hide"] == "통과"


def test_a_counts_the_gap_between_queries_and_new_rows():
    qs = [_q("full"), _q("partial")]
    s = _sym(qs, _good(qs)[:1])
    assert s["A"] == 1 and s["zones"]["rows"] == "미완"


def test_b_flags_a_row_that_does_not_match_its_query():
    qs = [_q("full"), _q("partial")]
    rows = _good(qs)
    rows[1] = rows[1] | {"house_manage_no": "다른공고"}
    rows[0] = rows[0] | {"answer": {"checklist": [{}], "x": "바뀜"}}
    s = _sym(qs, rows)
    assert s["B"] == 2 and s["zones"]["rows"] == "미완"


def test_b_checks_status_error_rows_and_step_counts():
    qs = [_q("full", ok=False), _q("partial")]
    rows = _good(qs)
    rows[0] = rows[0] | {"status": "error", "answer": None, "steps": {}}
    assert _sym(qs, rows)["B"] == 0
    rows[0] = rows[0] | {"answer": {"x": 1}}
    rows[1] = rows[1] | {"steps": {"queries": [{}, {}]}}
    assert _sym(qs, rows)["B"] == 2


def test_c_counts_a_row_with_the_iso_date_and_exits_incomplete():
    qs = [_q("full")]
    rows = _good(qs)
    rows[0]["json"] = '{"answer": "혼인신고일 2012-05-20 이다"}'
    s = _sym(qs, rows)
    assert s["C"] == 1 and s["D"] == 0 and s["zones"]["hide"] == "미완"


def test_d_alone_is_retry_and_stays_incomplete_after_a_retry():
    qs = [_q("full")]
    rows = _good(qs)
    rows[0]["json"] = '{"answer": "혼인신고일 2012년 5월 20일 이다"}'
    s = _sym(qs, rows)
    assert (s["C"], s["D"], s["E"]) == (0, 1, 0) and s["zones"]["hide"] == "다시 잰다"
    assert _sym(qs, rows, retry=True)["zones"]["hide"] == "미완"


def test_derived_values_are_counted_but_do_not_change_the_zone():
    qs = [_q("full")]
    rows = _good(qs)
    rows[0]["json"] = '{"reason": "가입기간 12년 6개월 3일"}'
    s = _sym(qs, rows)
    assert len(s["leaks"]["derived"]) == 1 and s["zones"]["hide"] == "통과"


def test_a_date_form_is_not_counted_twice_as_derived():
    qs = [_q("full")]
    rows = _good(qs)
    rows[0]["json"] = '{"reason": "2012년 5월 20일"}'
    s = _sym(qs, rows)
    assert s["D"] == 1 and s["leaks"]["derived"] == []


def test_e_flags_the_plain_sha256_of_the_same_json():
    qs = [_q("partial")]
    rows = [_r(1, tr.plain_sha(P(PARTIAL)))]
    s = _sym(qs, rows)
    assert s["E"] == 1 and "키 없는" in s["diffs_e"][0]["why"][0]
    assert s["zones"]["hide"] == "미완"


def test_e_flags_changing_overlapping_and_malformed_hashes():
    qs = [_q("full"), _q("full"), _q("partial"), _q("empty")]
    rows = [_r(1, "a" * 64), _r(2, "b" * 64), _r(3, "c" * 64), _r(4, "c" * 64)]
    s = _sym(qs, rows)
    flagged = {x["id"]: x["why"] for x in s["diffs_e"]}
    assert "같은 프로필 다른 해시" in flagged[2]
    assert "다른 프로필과 해시가 겹친다" in flagged[3] and 4 in flagged
    assert tr.hash_problems([_q("full")], [_r(1, "xyz")], _profiles())[0]["why"] == [
        "64자 16진수가 아니다"
    ]


def test_dist_diffs_compares_the_final_verdicts_per_profile_and_axis():
    def cell(profile, v):
        return {
            "notice": "n1",
            "profile": profile,
            "verdicts": [{"axis": "homeless", "verdict": v}],
        }

    baseline = {"cells": [cell("full", "ELIGIBLE"), cell("empty", "NEED_INFO")]}
    now = [
        {
            "ok": True,
            "extra": False,
            "profile": "full",
            "verdicts": cell("full", "ELIGIBLE")["verdicts"],
        },
        {
            "ok": True,
            "extra": False,
            "profile": "empty",
            "verdicts": cell("empty", "INELIGIBLE")["verdicts"],
        },
        {
            "ok": True,
            "extra": True,
            "profile": "full",
            "verdicts": cell("full", "UNVERIFIABLE")["verdicts"],
        },
    ]
    diffs = tr.dist_diffs(now, baseline, ["n1"])
    assert [(d["profile"], d["axis"]) for d in diffs] == [("empty", "homeless")]


# ── 끝까지 도는 실행 ──────────────────────────────────────────────────────


def _echo_with(reason):
    def reply(kw):
        labels = LABEL.findall(kw["messages"][1]["content"])
        return _reply("INELIGIBLE", citations=labels[:1], reason=reason)

    return reply


@pytest.fixture
def world(pg_engine, tmp_path):
    _version(pg_engine)
    hmn = _notice(pg_engine, n=103, models=[(7, {"MNYCH_HSHLDCO": 4, "NWWDS_HSHLDCO": 3})])
    _load_chunks(pg_engine, other_mst=False)
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps({"samples": [{"notice": hmn}]}), encoding="utf-8")
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    for name, d in (("full", FULL), ("partial", PARTIAL), ("empty", EMPTY)):
        (pdir / f"{name}.json").write_text(json.dumps(d), encoding="utf-8")
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"system_sha": "x", "cells": []}), encoding="utf-8")
    return pg_engine, hmn, {
        "samples_json": samples, "profiles_dir": pdir, "baseline_json": base,
        "out_md": tmp_path / "out.md", "out_json": tmp_path / "out.json",
        "cache_path": tmp_path / "c.jsonl", "trace_key": KEY,
    }  # fmt: skip


def _run(world, reason="프로필의 혼인신고일(2012-05-20)이 맞다.", extra=()):
    engine, _, kw = world
    return tr.main(
        ["--report", *extra], engine=engine, embedder=FakeEmbedder(dim=1536),
        client=FakeChat([_echo_with(reason)]), **kw,
    )  # fmt: skip


def test_report_runs_twenty_style_queries_and_writes_both_files(world, capsys):
    engine, hmn, kw = world
    code = _run(world)
    out = capsys.readouterr().out
    assert code == 0 and "징후 1:" in out and "징후 2:" in out
    md = kw["out_md"].read_text(encoding="utf-8")
    saved = json.loads(kw["out_json"].read_text(encoding="utf-8"))
    assert saved["symptoms"]["zones"]["rows"] == "통과" == saved["symptoms"]["zones"]["hide"]
    assert saved["symptoms"]["new_rows"] == saved["symptoms"]["queries"] == 5  # 3쌍 + 덧붙인 2건
    assert saved["symptoms"]["stats"]["status"] == {"ok": 4, "error": 1}  # 없는 관리번호만 실패
    for head in ("## 1. 징후 1~3", "## 2. 질의", "## 3. 행 한 개 전문", "## 4. 실패 행 전문",
                 "## 5. 파생값", "## 6. 표본"):  # fmt: skip
        assert head in md
    assert "[프로필 값]" in md and "2012-05-20" not in md  # 가린 자리가 보이고 원본은 없다
    assert md.splitlines()[2].startswith("- 징후 1:") and md.splitlines()[3].startswith("- 징후 2:")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM traces")).scalar() == 5


def test_second_run_keeps_the_first_runs_calls(world):
    _run(world)
    first = json.loads(world[2]["out_json"].read_text(encoding="utf-8"))["first_run"]
    _run(world)
    again = json.loads(world[2]["out_json"].read_text(encoding="utf-8"))
    assert again["first_run"] == first and again["second_run"] is not None
    assert again["symptoms"]["new_rows"] == 5  # 실행마다 그 실행의 새 행으로 잰다


def test_report_exits_1_when_a_row_goes_missing(world, monkeypatch):
    engine = world[0]
    real = tr.trace.run_traced

    def lose_a_row(*a, **k):
        out = real(*a, **k)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM traces WHERE id = :i"), {"i": out.trace_id})
        return out

    monkeypatch.setattr(tr.trace, "run_traced", lose_a_row)
    assert _run(world) == 1
    saved = json.loads(world[2]["out_json"].read_text(encoding="utf-8"))
    assert saved["symptoms"]["A"] >= 1  # 리포트는 쓰고 나서 exit 1


def test_report_exits_1_when_the_stored_row_keeps_a_profile_date(world, monkeypatch):
    engine = world[0]
    real = tr.trace.run_traced

    def leak(*a, **k):
        out = real(*a, **k)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE traces SET error = '혼인신고일 2012-05-20' WHERE id = :i"),
                {"i": out.trace_id},
            )
        return out

    monkeypatch.setattr(tr.trace, "run_traced", leak)
    assert _run(world) == 1
    saved = json.loads(world[2]["out_json"].read_text(encoding="utf-8"))
    assert saved["symptoms"]["C"] >= 1 and saved["symptoms"]["zones"]["hide"] == "미완"


def test_report_prints_retry_zone_when_only_other_date_forms_remain(world, monkeypatch, capsys):
    engine = world[0]
    real = tr.trace.run_traced

    def other_form(*a, **k):
        out = real(*a, **k)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE traces SET error = '혼인신고일 2012년 5월 20일' WHERE id = :i"),
                {"i": out.trace_id},
            )
        return out

    monkeypatch.setattr(tr.trace, "run_traced", other_form)
    code = _run(world)
    out = capsys.readouterr().out
    assert code == 0 and "hide 다시 잰다" in out
    assert _run(world, extra=("--retry",)) == 1  # 다시 쟀는데도 남았다


def test_report_without_key_exits_2(world, capsys):
    world[2]["trace_key"] = ""
    assert _run(world) == 2
    assert "TRACE_HASH_KEY" in capsys.readouterr().err
    assert not world[2]["out_md"].exists()


def test_a_uses_the_sample_size_not_the_number_of_queries_that_ran():
    qs = [_q("full"), _q("partial")]
    m = _m(qs, _good(qs)) | {"expected": 3}
    s = tr.symptoms(m, _profiles(), {"cells": []}, ["n1"], False)
    assert s["A"] == 1 and s["zones"]["rows"] == "미완"
