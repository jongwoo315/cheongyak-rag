import json
import re
from datetime import date

import pytest
from sqlalchemy import text

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import answer as ans
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.chunk import Chunk
from tests.fakes import FakeChat
from tests.test_retrieval_axes import _load_chunks, _notice, _version

MODEL = "gpt-5.4-mini"
LABEL = re.compile(r"^\[([^\]]+)\] ", re.M)


def _reply(verdict="ELIGIBLE", citations=("제2조",), **kw):
    body = {
        "verdict": verdict,
        "reason": "문맥대로다.",
        "conditions": [],
        "need_info": [],
        "citations": list(citations),
    } | kw
    return json.dumps(body, ensure_ascii=False)


def _hits(law=("제2조", "제3조"), faq=("Q1",)):
    return axes.QueryHits(
        "무주택 질의",
        [Chunk(f"law:{x}", x, x, f"{x}(제목)\n{x} 본문", "law", {"title": "제목"}) for x in law],
        [Chunk(f"faq:{x}", x, x, f"{x} 질문\n답", "faq") for x in faq],
    )


def _notice_info(mst="286965"):
    facts = axes.Facts("경기", dict.fromkeys((c for c, _ in axes.REGULATION_FLAGS), False), 0,
                       {k: 0 for k, _ in axes.SPECIAL_TYPES}, mst)  # fmt: skip
    return vd.NoticeInfo("2026000001", "2026000001", "단지 1", date(2026, 10, 1), facts)


def _payload(**fields):
    p = prof.Profile(birth_date=date(1990, 1, 1), **fields)
    return vd.profile_payload(p, prof.score(p, date(2026, 10, 1)))


AXIS = axes.AXIS_BY_ID["homeless"]


def _call(client, hits=None, cache=None, engine=None, notice=None, axis=AXIS, payload=None):
    return vd.judge_one(
        axis,
        hits or _hits(),
        notice or _notice_info(),
        payload or _payload(),
        client,
        MODEL,
        cache,
        engine,
    )


@pytest.fixture
def engine_with_chunks(pg_engine):
    _version(pg_engine)
    _notice(pg_engine, models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    return pg_engine


# ── Task 1: schema · 프롬프트 ────────────────────────────────────────────


def test_schema_has_the_five_verdicts_and_forbids_extra_keys():
    props = vd.SCHEMA["properties"]
    assert props["verdict"]["enum"] == [
        "ELIGIBLE",
        "INELIGIBLE",
        "CONDITIONAL",
        "NEED_INFO",
        "UNVERIFIABLE",
    ]
    assert vd.SCHEMA["additionalProperties"] is False
    assert set(vd.SCHEMA["required"]) == set(props) == {
        "verdict", "reason", "conditions", "need_info", "citations"
    }  # fmt: skip


def test_request_uses_strict_json_schema(engine_with_chunks):
    seen = {}

    def grab(kw):
        seen.update(kw)
        return _reply()

    _call(FakeChat([grab]), engine=engine_with_chunks)
    fmt = seen["response_format"]["json_schema"]
    assert fmt["strict"] is True and fmt["schema"] == vd.SCHEMA


def test_system_prompt_defines_every_axis_and_the_split_rule():
    for a in axes.AXES:
        assert a.id in vd.AXIS_DEFS and a.name in vd.SYSTEM
    for v in vd.VERDICTS:
        assert v in vd.SYSTEM
    assert "CONDITIONAL" in vd.SYSTEM and "NEED_INFO" in vd.SYSTEM


def test_user_message_is_byte_identical_for_the_same_input_and_ordered():
    a = vd.build_messages(AXIS, _hits(), _notice_info(), _payload())
    b = vd.build_messages(AXIS, _hits(), _notice_info(), _payload())
    assert a == b and [m["role"] for m in a] == ["system", "user"]
    user = a[1]["content"]
    order = [user.index(x) for x in ("무주택 여부·기간", "단지 1", "birth_date", "[제2조]")]
    assert order == sorted(order)  # 축·질의 → 공고 → 프로필 → 문맥
    assert "[제2조] 제2조(제목)\n제2조 본문" in user and "[Q1] Q1 질문\n답" in user
    assert "무주택 질의" in user and "missing" in user


# ── Task 2: judge_one · guardrail ────────────────────────────────────────


def test_no_context_skips_the_call_and_is_unverifiable():
    client = FakeChat([_reply()])
    v = _call(client, hits=_hits(law=(), faq=()))
    assert client.calls == []
    assert (v.verdict, v.no_context, v.forced) == ("UNVERIFIABLE", True, False)
    assert v.citations == [] and v.reason


def test_citation_outside_the_context_is_rejected(engine_with_chunks):
    client = FakeChat([_reply(citations=["제2조", "제99조", "[Q1]"])])
    v = _call(client, engine=engine_with_chunks, payload=_payload(homeless_now=True))
    assert v.citations == ["제2조", "Q1"] and v.invalid_citations == ["제99조"]
    assert (v.verdict, v.forced) == ("ELIGIBLE", False)


def test_citation_missing_from_chunks_table_is_rejected(engine_with_chunks):
    """문맥에는 있는데 chunks에서 다시 조회하면 없는 라벨 — 행을 빼서 만든다."""
    with engine_with_chunks.begin() as conn:
        conn.execute(text("DELETE FROM chunks WHERE source = 'law' AND label = '제2조'"))
    client = FakeChat([_reply(citations=["제2조", "제3조", "Q1"])])
    v = _call(client, engine=engine_with_chunks)
    assert v.invalid_citations == ["제2조"] and v.citations == ["제3조", "Q1"]


def test_law_citation_from_another_mst_is_rejected(engine_with_chunks):
    client = FakeChat([_reply(citations=["제2조"])])
    v = _call(client, engine=engine_with_chunks, notice=_notice_info(mst="999"))
    assert v.invalid_citations == ["제2조"] and v.forced is True


def test_no_remaining_citation_turns_the_verdict_into_unverifiable(engine_with_chunks):
    client = FakeChat([_reply("INELIGIBLE", citations=["제99조"])])
    v = _call(client, engine=engine_with_chunks)
    assert (v.verdict, v.forced, v.original_verdict) == ("UNVERIFIABLE", True, "INELIGIBLE")
    assert v.invalid_citations == ["제99조"]


@pytest.mark.parametrize("verdict", ["ELIGIBLE", "INELIGIBLE", "CONDITIONAL", "NEED_INFO"])
def test_every_verdict_but_unverifiable_needs_a_citation(engine_with_chunks, verdict):
    v = _call(FakeChat([_reply(verdict, citations=[])]), engine=engine_with_chunks)
    assert (v.verdict, v.forced) == ("UNVERIFIABLE", True)


def test_unverifiable_without_citations_is_not_forced(engine_with_chunks):
    v = _call(FakeChat([_reply("UNVERIFIABLE", citations=[])]), engine=engine_with_chunks)
    assert (v.verdict, v.forced, v.original_verdict) == ("UNVERIFIABLE", False, None)


def test_conditions_and_need_info_are_kept(engine_with_chunks):
    reply = _reply("CONDITIONAL", conditions=["전입해야 한다"], need_info=["무주택 기간"])
    v = _call(FakeChat([reply]), engine=engine_with_chunks)
    assert v.conditions == ["전입해야 한다"] and v.need_info == ["무주택 기간"]
    assert v.input_tokens == 1000 and v.output_tokens == 100 and v.usd > 0


def test_second_call_comes_from_the_cache(tmp_path, engine_with_chunks):
    path = tmp_path / "verdict.jsonl"
    kw = {"engine": engine_with_chunks, "payload": _payload(homeless_now=True)}
    first = _call(FakeChat([_reply()]), cache=ans.GenCache(path), **kw)
    client = FakeChat([_reply("INELIGIBLE")])
    second = _call(client, cache=ans.GenCache(path), **kw)
    assert client.calls == [] and second.cached and not first.cached
    assert second.verdict == first.verdict == "ELIGIBLE"


@pytest.mark.parametrize("content", ["{깨짐", None, "[]", json.dumps({"verdict": "MAYBE"})])
def test_bad_response_is_recorded_as_error_and_not_cached(tmp_path, content):
    cache = ans.GenCache(tmp_path / "v.jsonl")
    v = _call(FakeChat([content]), cache=cache)
    assert v.error and v.verdict is None and cache.rows == {}


def test_api_error_is_recorded_and_hard_error_propagates():
    v = _call(FakeChat([RuntimeError("boom")]))
    assert "boom" in v.error and v.verdict is None
    with pytest.raises(ans.HardApiError):
        _call(FakeChat([ans.HardApiError("insufficient_quota")]))


# ── ELIGIBLE guard ───────────────────────────────────────────────────────

NO_FIELD_AXES = ("residence", "income_asset", "rewin", "special_type")
FIELD = {
    "homeless": ("homeless_now", True),
    "account": ("savings_join_date", date(2014, 3, 1)),
    "householder": ("is_household_head", True),
}


def test_guard_tables_cover_exactly_the_axes():
    """축을 더하고 표를 안 고치면 ELIGIBLE이 나오는 순간 KeyError가 난다."""
    assert set(vd.REQUIRED_FIELDS) == set(vd.NEED_INFO_TEXT) == set(axes.AXIS_BY_ID)


@pytest.mark.parametrize("axis_id", NO_FIELD_AXES)
def test_guard_turns_eligible_into_need_info_on_axes_without_a_profile_field(
    engine_with_chunks, axis_id
):
    """꽉 찬 프로필이어도 #77에 칸이 없는 축은 ELIGIBLE이 남지 않는다."""
    full = _payload(**dict(FIELD.values()))
    v = _call(
        FakeChat([_reply("ELIGIBLE", citations=["제2조"])]),
        engine=engine_with_chunks,
        axis=axes.AXIS_BY_ID[axis_id],
        payload=full,
    )
    assert (v.verdict, v.guarded, v.original_verdict) == ("NEED_INFO", True, "ELIGIBLE")
    assert v.need_info == [vd.NEED_INFO_TEXT[axis_id]] and v.forced is False
    assert v.citations == ["제2조"]  # 인용은 그대로 둔다


@pytest.mark.parametrize("axis_id", list(FIELD))
def test_guard_needs_the_axis_field_value(engine_with_chunks, axis_id):
    name, value = FIELD[axis_id]
    axis = axes.AXIS_BY_ID[axis_id]
    missing = _call(FakeChat([_reply("ELIGIBLE")]), engine=engine_with_chunks, axis=axis)
    assert (missing.verdict, missing.guarded) == ("NEED_INFO", True)
    assert missing.need_info == [vd.NEED_INFO_TEXT[axis_id]]
    kept = _call(
        FakeChat([_reply("ELIGIBLE")]),
        engine=engine_with_chunks,
        axis=axis,
        payload=_payload(**{name: value}),
    )
    assert (kept.verdict, kept.guarded, kept.original_verdict) == ("ELIGIBLE", False, None)


def test_guard_counts_false_as_a_value(engine_with_chunks):
    """`homeless_now=False`는 사용자가 답한 값이다. 모르는 값은 None뿐이다."""
    v = _call(
        FakeChat([_reply("ELIGIBLE")]),
        engine=engine_with_chunks,
        payload=_payload(homeless_now=False),
    )
    assert (v.verdict, v.guarded) == ("ELIGIBLE", False)


@pytest.mark.parametrize("verdict", ["INELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE"])
@pytest.mark.parametrize("axis_id", [*NO_FIELD_AXES, *FIELD])
def test_guard_leaves_every_other_verdict_alone(engine_with_chunks, axis_id, verdict):
    v = _call(
        FakeChat([_reply(verdict, need_info=["x"])]),
        engine=engine_with_chunks,
        axis=axes.AXIS_BY_ID[axis_id],
    )
    assert (v.verdict, v.guarded, v.forced) == (verdict, False, False)
    assert v.need_info == ["x"]


def test_guard_does_not_touch_a_forced_verdict(engine_with_chunks):
    """인용이 기각돼 UNVERIFIABLE이 된 판정은 원래 판정(ELIGIBLE)을 forced가 쥔다."""
    v = _call(
        FakeChat([_reply("ELIGIBLE", citations=["제99조"])]),
        engine=engine_with_chunks,
        axis=axes.AXIS_BY_ID["residence"],
    )
    assert (v.verdict, v.forced, v.guarded, v.original_verdict) == (
        "UNVERIFIABLE",
        True,
        False,
        "ELIGIBLE",
    )
    assert v.need_info == []


def test_guard_reads_the_raw_profile_not_the_score(engine_with_chunks):
    """guard는 `profile.score` 결과가 아니라 프로필 원본의 칸을 본다."""
    payload = _payload()
    assert payload["profile"]["homeless_now"] is None
    v = _call(FakeChat([_reply("ELIGIBLE")]), engine=engine_with_chunks, payload=payload)
    assert (v.verdict, v.guarded) == ("NEED_INFO", True)


def test_guard_is_applied_after_the_cache(tmp_path, engine_with_chunks):
    """캐시에는 모델 응답 원본이 있고 guard는 읽은 뒤에 건다."""
    path = tmp_path / "v.jsonl"
    _call(FakeChat([_reply("ELIGIBLE")]), cache=ans.GenCache(path), engine=engine_with_chunks)
    again = _call(FakeChat([]), cache=ans.GenCache(path), engine=engine_with_chunks)
    assert again.cached and (again.verdict, again.guarded) == ("NEED_INFO", True)


# ── Task 3: judge ────────────────────────────────────────────────────────


def _echo(verdict="ELIGIBLE"):
    """사용자 메시지의 첫 문맥 라벨을 인용하는 가짜 응답."""

    def reply(kw):
        labels = LABEL.findall(kw["messages"][1]["content"])
        return _reply(verdict, citations=labels[:1])

    return reply


def _judge(engine, client, p=None, hmn=None, cache=None):
    from tests.fakes import FakeEmbedder

    return vd.judge(
        engine, FakeEmbedder(dim=1536), client, MODEL, hmn, p or prof.Profile(), cache=cache
    )


def test_judge_does_not_call_the_client_for_off_axes(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])  # 특별공급 0·규제 표시 없음 → 3축만 켜진다
    _load_chunks(pg_engine, other_mst=False)
    client = FakeChat([_echo()])
    info, plans, verdicts = _judge(pg_engine, client, hmn=hmn)
    assert [p.id for p in plans if p.on] == ["homeless", "account", "residence"]
    assert len(plans) == 7 and len(client.calls) == len(verdicts) == 3
    assert {v.axis for v in verdicts} == {"homeless", "account", "residence"}
    assert info.name == "단지 1" and str(info.as_of) == "2026-10-01"


def test_judge_gives_one_verdict_per_special_type(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(7, {"MNYCH_HSHLDCO": 4, "NWWDS_HSHLDCO": 3})])
    _load_chunks(pg_engine, other_mst=False)
    _, plans, verdicts = _judge(pg_engine, FakeChat([_echo()]), hmn=hmn)
    special = [v for v in verdicts if v.axis == "special_type"]
    assert len(special) == 2 and len({v.query for v in special}) == 2
    assert next(p for p in plans if p.id == "special_type").queries == [v.query for v in special]


def test_judge_scores_the_profile_on_the_notice_date(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, de="2026-03-02", models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    client = FakeChat([_echo()])
    p = prof.Profile(birth_date=date(1990, 1, 1))
    _judge(pg_engine, client, p, hmn)
    user = client.calls[0]["messages"][1]["content"]
    assert '"as_of": "2026-03-02"' in user and '"birth_date": "1990-01-01"' in user


def test_judge_lets_profile_errors_through(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    late = prof.Profile(savings_join_date=date(2030, 1, 1))
    with pytest.raises(prof.ProfileError):
        _judge(pg_engine, FakeChat([_echo()]), late, hmn)


def test_judge_unknown_notice_raises(pg_engine):
    with pytest.raises(axes.NoticeNotFound):
        _judge(pg_engine, FakeChat([_echo()]), hmn="없음")


# ── Task 4: CLI ──────────────────────────────────────────────────────────


def test_cli_prints_seven_axes_and_each_verdict_line(pg_engine, tmp_path, capsys):
    from tests.fakes import FakeEmbedder

    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    pf = tmp_path / "p.json"
    pf.write_text('{"birth_date": "1990-01-01"}', encoding="utf-8")
    code = vd.main(
        [hmn, "--profile", str(pf)],
        engine=pg_engine,
        embedder=FakeEmbedder(dim=1536),
        client=FakeChat([_echo()]),
        cache_path=tmp_path / "c.jsonl",
    )
    out = capsys.readouterr().out
    assert code == 0
    for a in axes.AXES:
        assert a.name in out
    assert out.count("꺼짐 —") == 4 and out.count("켜짐 —") == 3
    assert "ELIGIBLE" in out and "인용" in out and "단지 1" in out


def test_cli_prints_the_guarded_verdict_with_the_original_one(pg_engine, tmp_path, capsys):
    from tests.fakes import FakeEmbedder

    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    _load_chunks(pg_engine, other_mst=False)
    pf = tmp_path / "p.json"
    pf.write_text("{}", encoding="utf-8")  # 빈 프로필
    code = vd.main(
        [hmn, "--profile", str(pf)],
        engine=pg_engine,
        embedder=FakeEmbedder(dim=1536),
        client=FakeChat([_echo("ELIGIBLE")]),
        cache_path=tmp_path / "c.jsonl",
    )
    out = capsys.readouterr().out
    assert code == 0 and "판정: ELIGIBLE" not in out
    assert out.count("프로필 값이 없어 코드가 바꿈 — 모델 판정 ELIGIBLE") == 3
    assert "필요한 정보: 무주택세대구성원 판정 값(homeless_now)" in out


def test_cli_exits_2_for_unknown_notice_and_bad_profile(pg_engine, tmp_path):
    from tests.fakes import FakeEmbedder

    pf = tmp_path / "p.json"
    pf.write_text("{}", encoding="utf-8")
    kw = {"engine": pg_engine, "embedder": FakeEmbedder(dim=1536), "client": FakeChat([_echo()])}
    assert vd.main(["없음", "--profile", str(pf)], cache_path=tmp_path / "c", **kw) == 2
    pf.write_text('{"nope": 1}', encoding="utf-8")
    assert vd.main(["없음", "--profile", str(pf)], cache_path=tmp_path / "c", **kw) == 2


# ── 리뷰 지적 ────────────────────────────────────────────────────────────


def test_cached_value_that_no_longer_parses_is_called_again(tmp_path, engine_with_chunks):
    cache = ans.GenCache(tmp_path / "v.jsonl")
    probe = FakeChat([_reply()])
    _call(probe, cache=cache, engine=engine_with_chunks)
    (key,) = cache.rows
    cache.rows[key] = {**cache.rows[key], "content": "{깨짐"}  # 스키마가 바뀐 뒤 옛 응답
    client = FakeChat([_reply("INELIGIBLE")])
    v = _call(client, cache=cache, engine=engine_with_chunks)
    assert len(client.calls) == 1 and v.error is None and v.verdict == "INELIGIBLE"
    assert not v.cached and json.loads(cache.rows[key]["content"])["verdict"] == "INELIGIBLE"


def test_cli_shows_the_original_verdict_of_a_guarded_verdict():
    v = vd.Verdict(
        "residence", "거주", "q", verdict="NEED_INFO", reason="경기로 확인되어",
        need_info=["거주 지역·기간"], guarded=True, original_verdict="ELIGIBLE",
    )  # fmt: skip
    out = vd.format_verdict(v)
    assert "판정: NEED_INFO (프로필 값이 없어 코드가 바꿈 — 모델 판정 ELIGIBLE)" in out
    assert "이유(모델): 경기로 확인되어" in out and "필요한 정보: 거주 지역·기간" in out


def test_cli_summary_does_not_charge_cached_verdicts():
    cached = vd.Verdict("homeless", "무주택", "q", verdict="ELIGIBLE", cached=True,
                        input_tokens=1000, output_tokens=100, usd=0.5)  # fmt: skip
    fresh = vd.Verdict("homeless", "무주택", "q2", verdict="ELIGIBLE",
                       input_tokens=10, output_tokens=1, usd=0.25)  # fmt: skip
    plan = axes.AxisPlan("homeless", "무주택", True, "r", ["q", "q2"], "1")
    out = vd.format_report(_notice_info(), [plan], [cached, fresh])
    assert "호출 1 · 캐시 1" in out and "$0.2500" in out and "토큰 입력 10 " in out
