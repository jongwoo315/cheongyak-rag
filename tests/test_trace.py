import dataclasses
import hashlib
import json
import re
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from cheongyak_rag import profile as prof
from cheongyak_rag import trace
from cheongyak_rag.config import Settings
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_generate_verdict import LABEL, MODEL, _reply
from tests.test_retrieval_axes import _load_chunks, _notice, _version

KEY = "test-key-1"
BIRTH = date(1990, 1, 1)


def _echo_with(reason):
    """첫 문맥 라벨을 인용하고 이유 문장을 정해 둔 가짜 응답."""

    def reply(kw):
        labels = LABEL.findall(kw["messages"][1]["content"])
        return _reply("INELIGIBLE", citations=labels[:1], reason=reason)

    return reply


@pytest.fixture
def hmn(pg_engine):
    _version(pg_engine)
    h = _notice(pg_engine, models=[(7, {"MNYCH_HSHLDCO": 4, "NWWDS_HSHLDCO": 3})])
    _load_chunks(pg_engine, other_mst=False)
    return h


def _run(engine, client, hmn, profile=None, key=KEY, **kw):
    return trace.run_traced(
        engine,
        FakeEmbedder(dim=1536),
        client,
        MODEL,
        hmn,
        profile or prof.Profile(birth_date=BIRTH),
        key=key,
        **kw,
    )


def _rows(engine):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT * FROM traces ORDER BY id"))]


# ── 해시 ─────────────────────────────────────────────────────────────────


def test_same_profile_same_hash_and_it_is_64_hex():
    p = prof.Profile(birth_date=BIRTH, married=True)
    h = trace.profile_hash(p, KEY)
    assert h == trace.profile_hash(prof.Profile(birth_date=BIRTH, married=True), KEY)
    assert re.fullmatch(r"[0-9a-f]{64}", h)


def test_one_field_or_the_key_changes_the_hash():
    p = prof.Profile(birth_date=BIRTH)
    h = trace.profile_hash(p, KEY)
    assert h != trace.profile_hash(prof.Profile(birth_date=date(1990, 1, 2)), KEY)
    assert h != trace.profile_hash(prof.Profile(birth_date=BIRTH, married=False), KEY)
    assert h != trace.profile_hash(p, "other-key")


def test_hash_is_not_a_plain_sha256_of_the_same_json():
    p = prof.Profile(birth_date=BIRTH)
    plain = hashlib.sha256(json.dumps(p.to_dict(), sort_keys=True).encode()).hexdigest()
    assert trace.profile_hash(p, KEY) != plain


def test_empty_key_raises_before_anything_runs(pg_engine):
    client = FakeChat([_reply()])
    with pytest.raises(trace.MissingKey, match="TRACE_HASH_KEY"):
        _run(pg_engine, client, "없음", key="")
    assert client.calls == [] and _rows(pg_engine) == []


def test_settings_has_an_empty_trace_key_by_default():
    assert Settings(_env_file=None).trace_hash_key == ""


# ── 가리기 ───────────────────────────────────────────────────────────────


def test_mask_walks_dicts_lists_and_strings_and_leaves_the_rest():
    p = prof.Profile(birth_date=BIRTH, married=True, children_unmarried=2)
    obj = {"a": ["생일 1990-01-01 이다", {"b": "1990-01-01"}], "n": 3, "t": True, "x": None}
    assert trace.mask(obj, p) == {
        "a": ["생일 [프로필 값] 이다", {"b": "[프로필 값]"}],
        "n": 3,
        "t": True,
        "x": None,
    }


def test_mask_with_no_string_values_is_identity():
    obj = {"a": "1990-01-01"}
    assert trace.mask(obj, prof.Profile(married=True)) == obj


def test_stored_row_hides_the_profile_date_but_the_returned_answer_keeps_it(pg_engine, hmn):
    reason = "프로필의 생년월일(1990-01-01)이 요건에 안 맞는다."
    out = _run(pg_engine, FakeChat([_echo_with(reason)]), hmn)
    assert any("1990-01-01" in i.reason for i in out.answer.checklist)
    assert any("1990-01-01" in v.reason for v in out.verdicts)
    (row,) = _rows(pg_engine)
    dumped = json.dumps(row, default=str, ensure_ascii=False)
    assert "1990-01-01" not in dumped and trace.MASK in dumped


# ── 행 ───────────────────────────────────────────────────────────────────


def test_ok_run_writes_one_row_that_matches_the_response(pg_engine, hmn):
    out = _run(pg_engine, FakeChat([_reply("INELIGIBLE")]), hmn)
    (row,) = _rows(pg_engine)
    assert out.trace_id == row["id"] and out.trace_error is None
    assert row["status"] == "ok" and row["error"] is None
    assert row["house_manage_no"] == hmn and row["pblanc_no"] == out.notice.pblanc_no
    assert row["verdict"] == out.answer.verdict == "INELIGIBLE"
    assert row["model"] == MODEL and re.fullmatch(r"[0-9a-f]{8}", row["system_sha"])
    assert row["profile_hash"] == trace.profile_hash(prof.Profile(birth_date=BIRTH), KEY)
    assert row["answer"] == json.loads(json.dumps(dataclasses.asdict(out.answer)))
    assert len(row["steps"]["queries"]) == len(out.answer.checklist) > 2
    assert row["seconds"] > 0


def test_steps_record_axes_queries_and_totals(pg_engine, hmn):
    out = _run(pg_engine, FakeChat([_reply("INELIGIBLE")]), hmn)
    steps = _rows(pg_engine)[0]["steps"]
    assert steps["as_of"] == out.notice.as_of.isoformat()
    assert steps["law_mst"] == out.notice.facts.law_mst
    assert [a["id"] for a in steps["axes"]] == [a.id for a in axes.AXES]
    assert all(a["reason"] for a in steps["axes"])
    q = steps["queries"][0]
    assert set(q) >= {"axis", "query", "context_labels", "model_verdict", "verdict", "forced",
                      "guarded", "invalid_citations", "input_tokens", "output_tokens", "usd",
                      "cached", "error"}  # fmt: skip
    assert steps["total"]["llm_calls"] == len(out.verdicts)


def test_guarded_query_keeps_the_model_verdict_in_steps(pg_engine, hmn):
    # 빈 프로필의 ELIGIBLE은 코드가 NEED_INFO로 바꾼다
    out = _run(pg_engine, FakeChat([_reply("ELIGIBLE")]), hmn, prof.Profile())
    q = _rows(pg_engine)[0]["steps"]["queries"]
    assert any(x["guarded"] and x["model_verdict"] == "ELIGIBLE" and x["verdict"] == "NEED_INFO"
               for x in q)  # fmt: skip
    assert out.answer.verdict == "NEED_INFO"


def test_unknown_notice_writes_an_error_row_and_reraises(pg_engine):
    client = FakeChat([_reply()])
    with pytest.raises(axes.NoticeNotFound):
        _run(pg_engine, client, "0000000000")
    (row,) = _rows(pg_engine)
    assert row["status"] == "error" and row["house_manage_no"] == "0000000000"
    assert row["pblanc_no"] is None and row["verdict"] is None and row["answer"] is None
    assert "NoticeNotFound" in row["error"] and row["steps"] == {}
    assert client.calls == []


def test_error_text_hides_the_profile_value(pg_engine, hmn):
    # 통장 가입일이 생년월일보다 빠르면 ProfileError 메시지에 두 날짜가 그대로 든다
    bad = prof.Profile(birth_date=date(2000, 1, 1), savings_join_date=date(1990, 5, 5))
    with pytest.raises(prof.ProfileError) as raised:
        _run(pg_engine, FakeChat([_reply()]), hmn, bad)
    assert "2000-01-01" in str(raised.value) and "1990-05-05" in str(raised.value)
    (row,) = _rows(pg_engine)
    assert row["status"] == "error" and "ProfileError" in row["error"]
    assert "2000-01-01" not in row["error"] and "1990-05-05" not in row["error"]


def test_failing_write_returns_the_response_with_trace_error(pg_engine, hmn, monkeypatch):
    def boom(engine, row):
        raise OperationalError("INSERT", {}, Exception("연결 끊김"))

    monkeypatch.setattr(trace, "write", boom)
    out = _run(pg_engine, FakeChat([_reply("INELIGIBLE")]), hmn)
    assert out.answer.verdict == "INELIGIBLE"
    assert out.trace_id is None and "OperationalError" in out.trace_error


def test_failing_error_row_write_does_not_hide_the_flow_exception(pg_engine, monkeypatch):
    def boom(engine, row):
        raise OperationalError("INSERT", {}, Exception("연결 끊김"))

    monkeypatch.setattr(trace, "write", boom)
    with pytest.raises(axes.NoticeNotFound) as e:
        _run(pg_engine, FakeChat([_reply()]), "없음")
    assert any("trace 행도 못 썼다" in n for n in e.value.__notes__)


def test_two_queries_make_two_rows_with_one_hash_per_profile(pg_engine, hmn):
    client = FakeChat([_reply("INELIGIBLE")])
    _run(pg_engine, client, hmn)
    _run(pg_engine, client, hmn)
    _run(pg_engine, client, hmn, prof.Profile(birth_date=date(1991, 1, 1)))
    rows = _rows(pg_engine)
    assert [r["status"] for r in rows] == ["ok"] * 3
    assert rows[0]["profile_hash"] == rows[1]["profile_hash"] != rows[2]["profile_hash"]


def test_run_traced_is_the_same_flow_as_judge(pg_engine, hmn):
    out = _run(pg_engine, FakeChat([_reply("INELIGIBLE")]), hmn)
    _, _, again = vd.judge(
        pg_engine, FakeEmbedder(dim=1536), FakeChat([_reply("INELIGIBLE")]), MODEL, hmn,
        prof.Profile(birth_date=BIRTH),
    )  # fmt: skip
    assert [(v.query, v.verdict) for v in out.verdicts] == [(v.query, v.verdict) for v in again]


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli(engine, hmn, tmp_path, profile_json='{"birth_date": "1990-01-01"}', **kw):
    pf = tmp_path / "p.json"
    pf.write_text(profile_json, encoding="utf-8")
    return vd.main(
        [hmn, "--profile", str(pf)],
        engine=engine,
        embedder=FakeEmbedder(dim=1536),
        client=FakeChat([_reply("INELIGIBLE")]),
        cache_path=tmp_path / "c.jsonl",
        **kw,
    )


def test_cli_without_key_exits_2_before_the_flow_and_writes_nothing(
    pg_engine, hmn, tmp_path, capsys
):
    code = _cli(pg_engine, hmn, tmp_path, trace_key="")
    cap = capsys.readouterr()
    assert code == 2 and "TRACE_HASH_KEY" in cap.err and cap.out == ""
    assert _rows(pg_engine) == []


def test_cli_defaults_to_the_settings_key(pg_engine, hmn, tmp_path, monkeypatch):
    from cheongyak_rag.config import settings

    monkeypatch.setattr(settings, "trace_hash_key", "")
    assert _cli(pg_engine, hmn, tmp_path) == 2
    monkeypatch.setattr(settings, "trace_hash_key", KEY)
    assert _cli(pg_engine, hmn, tmp_path) == 0
    assert len(_rows(pg_engine)) == 1


def test_cli_run_writes_one_row_and_prints_the_same_output(pg_engine, hmn, tmp_path, capsys):
    code = _cli(pg_engine, hmn, tmp_path, trace_key=KEY)
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("전역 판정(일반공급): INELIGIBLE")
    assert "\n---\n" in out and "판정 " in out
    (row,) = _rows(pg_engine)
    assert row["status"] == "ok" and row["verdict"] == "INELIGIBLE"


def test_cli_unknown_notice_exits_2_and_leaves_an_error_row(pg_engine, tmp_path):
    assert _cli(pg_engine, "0000000000", tmp_path, trace_key=KEY) == 2
    (row,) = _rows(pg_engine)
    assert row["status"] == "error"


def test_cli_write_failure_prints_the_answer_then_exits_1(
    pg_engine, hmn, tmp_path, capsys, monkeypatch
):
    def boom(engine, row):
        raise OperationalError("INSERT", {}, Exception("연결 끊김"))

    monkeypatch.setattr(trace, "write", boom)
    code = _cli(pg_engine, hmn, tmp_path, trace_key=KEY)
    cap = capsys.readouterr()
    assert code == 1 and cap.out.startswith("전역 판정(일반공급)")
    assert "trace 행을 못 썼다" in cap.err
