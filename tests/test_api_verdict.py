from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cheongyak_rag import api, trace
from cheongyak_rag.config import settings
from cheongyak_rag.generate.answer import GenCache, HardApiError
from cheongyak_rag.main import app
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_generate_verdict import MODEL, _reply
from tests.test_retrieval_axes import _load_chunks, _notice, _version

KEY = "test-key-1"


@pytest.fixture
def hmn(pg_engine):
    _version(pg_engine)
    h = _notice(pg_engine, models=[(7, {"MNYCH_HSHLDCO": 4, "NWWDS_HSHLDCO": 3})])
    _load_chunks(pg_engine, other_mst=False)
    return h


@pytest.fixture
def make(pg_engine, tmp_path):
    """가짜 임베더·클라이언트를 단 TestClient. OpenAI를 부르지 않는다."""

    def build(replies=None, key=KEY):
        chat = FakeChat(replies or [_reply("INELIGIBLE")])
        deps = api.VerdictDeps(
            FakeEmbedder(dim=1536), chat, GenCache(tmp_path / "gen.jsonl"), MODEL, key
        )
        app.dependency_overrides[api.get_engine] = lambda: pg_engine
        app.dependency_overrides[api.get_verdict_deps] = lambda: deps
        return TestClient(app), chat

    yield build
    app.dependency_overrides.clear()


def _n_traces(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM traces")).scalar_one()


def _post(client, hmn, body):
    return client.post(f"/api/notices/{hmn}/verdict", json=body)


def test_ok_returns_the_answer_and_writes_one_trace_row(make, hmn, pg_engine):
    client, chat = make()
    r = _post(client, hmn, {"birth_date": "1990-01-01", "married": False})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "INELIGIBLE" and body["house_manage_no"] == hmn
    assert body["general"]["key"] == "general" and body["checklist"] and chat.calls
    assert body["trace_error"] is None and isinstance(body["trace_id"], int)
    assert _n_traces(pg_engine) == 1


def test_empty_profile_is_fine(make, hmn):
    client, _ = make()
    assert _post(client, hmn, {}).status_code == 200


def test_unknown_profile_field_is_422(make, hmn, pg_engine):
    client, chat = make()
    r = _post(client, hmn, {"shoe_size": 270})
    assert r.status_code == 422 and "shoe_size" in r.json()["detail"]
    assert chat.calls == [] and _n_traces(pg_engine) == 0


def test_bad_date_is_422(make, hmn):
    client, _ = make()
    r = _post(client, hmn, {"birth_date": "1990/01/01"})
    assert r.status_code == 422 and "birth_date" in r.json()["detail"]


def test_contradicting_profile_is_422_and_leaves_no_trace_row(make, hmn, pg_engine):
    client, chat = make()
    r = _post(client, hmn, {"ever_owned": False, "homeless_since": "2020-01-01"})
    assert r.status_code == 422
    assert chat.calls == [] and _n_traces(pg_engine) == 0


def test_body_that_is_not_an_object_is_422(make, hmn):
    client, _ = make()
    assert _post(client, hmn, [1, 2]).status_code == 422


def test_unknown_notice_is_404_and_leaves_no_trace_row(make, pg_engine):
    client, chat = make()
    assert _post(client, "없는번호", {}).status_code == 404
    assert chat.calls == [] and _n_traces(pg_engine) == 0


def test_missing_trace_key_is_503_before_anything_runs(make, hmn, pg_engine):
    client, chat = make(key="")
    r = _post(client, hmn, {"birth_date": "1990-01-01"})
    assert r.status_code == 503 and "TRACE_HASH_KEY" in r.json()["detail"]
    assert chat.calls == [] and _n_traces(pg_engine) == 0


def test_hard_api_error_is_503(make, hmn):
    client, _ = make([HardApiError("insufficient_quota")])
    r = _post(client, hmn, {})
    assert r.status_code == 503 and r.json()["detail"] == api.NO_DETAIL  # 내부 오류 문구를 숨긴다
    assert "insufficient_quota" not in r.text


def test_db_error_is_503_with_only_the_class_name(make, hmn, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def boom(*a, **kw):
        raise OperationalError("SELECT secret_column", {}, Exception("dsn=postgres://u:pw@h"))

    monkeypatch.setattr(trace, "run_traced", boom)
    client, _ = make()
    r = _post(client, hmn, {})
    assert r.status_code == 503 and r.json()["detail"] == "DB 오류: OperationalError"
    assert "secret_column" not in r.text and "pw@h" not in r.text


def test_failed_checklist_item_error_text_is_hidden(make, hmn):
    client, _ = make([_reply("INELIGIBLE"), RuntimeError("org-secret-123")])
    r = _post(client, hmn, {})
    assert r.status_code == 200 and "org-secret-123" not in r.text
    errors = [i["error"] for i in r.json()["checklist"] if i["error"]]
    assert errors and set(errors) == {api.ITEM_FAILED}


def test_all_items_failing_is_503_not_a_null_verdict(make, hmn):
    client, _ = make([RuntimeError("org-secret-123")])
    r = _post(client, hmn, {})
    assert r.status_code == 503 and r.json()["detail"] == api.NO_DETAIL
    assert "org-secret-123" not in r.text


def test_row_write_failure_still_returns_200_with_trace_error(make, hmn, monkeypatch):
    def boom(engine, row):
        raise RuntimeError("disk full")

    monkeypatch.setattr(trace, "write", boom)
    client, _ = make()
    r = _post(client, hmn, {})
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] is None and body["trace_error"]
    assert "disk full" not in r.text  # DB 오류 문구를 숨긴다
    assert body["verdict"] == "INELIGIBLE"


def test_deps_without_an_openai_key_is_503(monkeypatch):
    monkeypatch.setattr(api.settings, "openai_api_key", "")
    api.get_verdict_deps.cache_clear()
    with pytest.raises(api.HTTPException) as e:
        api.get_verdict_deps()
    assert e.value.status_code == 503


# ── 하루 판정 한도 (#85) ─────────────────────────────────────────────────


@pytest.fixture
def spy(monkeypatch):
    """`run_traced`가 불린 횟수."""
    calls = []
    real = trace.run_traced

    def wrapped(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(trace, "run_traced", wrapped)
    return calls


def _count_rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT day, count FROM verdict_daily_count")).all()


def test_third_request_over_a_limit_of_two_is_429_and_never_reaches_the_flow(
    make, hmn, monkeypatch, spy
):
    monkeypatch.setattr(settings, "verdict_daily_limit", 2)
    client, chat = make()
    assert _post(client, hmn, {}).status_code == 200
    assert _post(client, hmn, {}).status_code == 200
    n_calls = len(chat.calls)
    r = _post(client, hmn, {})
    assert r.status_code == 429
    assert r.json()["detail"] == "오늘 판정 한도(2건)를 다 썼다. 내일 다시 시도해 달라"
    assert len(spy) == 2 and len(chat.calls) == n_calls


def test_404_and_422_requests_do_not_move_the_counter(make, hmn, pg_engine, monkeypatch, spy):
    monkeypatch.setattr(settings, "verdict_daily_limit", 1)
    client, _ = make()
    assert _post(client, "없는번호", {}).status_code == 404
    assert _post(client, hmn, {"shoe_size": 270}).status_code == 422
    assert (
        _post(client, hmn, {"ever_owned": False, "homeless_since": "2020-01-01"}).status_code == 422
    )
    assert _count_rows(pg_engine) == []
    assert _post(client, hmn, {}).status_code == 200  # 한도 1건이 그대로 남아 있었다
    assert [r[1] for r in _count_rows(pg_engine)] == [1] and len(spy) == 1


def test_missing_trace_key_does_not_move_the_counter(make, hmn, pg_engine):
    client, _ = make(key="")
    assert _post(client, hmn, {}).status_code == 503
    assert _count_rows(pg_engine) == []


def test_a_new_korean_day_starts_a_new_count(make, hmn, pg_engine, monkeypatch):
    monkeypatch.setattr(settings, "verdict_daily_limit", 1)
    client, _ = make()
    monkeypatch.setattr(api, "today_kst", lambda: date(2026, 11, 9))
    assert _post(client, hmn, {}).status_code == 200
    assert _post(client, hmn, {}).status_code == 429
    monkeypatch.setattr(api, "today_kst", lambda: date(2026, 11, 10))
    assert _post(client, hmn, {}).status_code == 200
    assert sorted(_count_rows(pg_engine)) == [(date(2026, 11, 9), 2), (date(2026, 11, 10), 1)]


def test_today_kst_is_the_seoul_date_not_the_utc_date():
    utc_evening = datetime(2026, 11, 9, 16, 0, tzinfo=UTC)  # 서울은 11-10 01:00
    assert api.today_kst(utc_evening) == date(2026, 11, 10)
    assert api.today_kst(datetime(2026, 11, 9, 14, 59, tzinfo=UTC)) == date(2026, 11, 9)


# ── 판정 잠금 대기 제한 (#85) ────────────────────────────────────────────


def test_busy_lock_is_503_after_the_timeout_and_never_reaches_the_flow(make, hmn, monkeypatch, spy):
    monkeypatch.setattr(settings, "verdict_lock_timeout_s", 0.05)
    client, chat = make()
    assert api._LOCK.acquire(timeout=1)  # 앞 판정이 진행 중인 것처럼 잠근다
    try:
        r = _post(client, hmn, {})
    finally:
        api._LOCK.release()
    assert r.status_code == 503
    assert r.json()["detail"] == "다른 판정이 진행 중이다. 잠시 뒤 다시 시도해 달라"
    assert spy == [] and chat.calls == []
    assert _post(client, hmn, {}).status_code == 200  # 풀리면 다시 받는다


def test_lock_is_released_when_the_flow_raises(make, hmn, monkeypatch):
    def boom(*a, **kw):
        raise HardApiError("insufficient_quota")

    monkeypatch.setattr(trace, "run_traced", boom)
    client, _ = make()
    assert _post(client, hmn, {}).status_code == 503
    assert api._LOCK.acquire(timeout=1)  # 예외 뒤에도 잠금이 풀려 있다
    api._LOCK.release()
