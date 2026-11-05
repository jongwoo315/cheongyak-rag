import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cheongyak_rag import api, trace
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


def test_contradicting_profile_is_422(make, hmn):
    client, _ = make()
    r = _post(client, hmn, {"ever_owned": False, "homeless_since": "2020-01-01"})
    assert r.status_code == 422


def test_body_that_is_not_an_object_is_422(make, hmn):
    client, _ = make()
    assert _post(client, hmn, [1, 2]).status_code == 422


def test_unknown_notice_is_404(make):
    client, _ = make()
    assert _post(client, "없는번호", {}).status_code == 404


def test_missing_trace_key_is_503_before_anything_runs(make, hmn, pg_engine):
    client, chat = make(key="")
    r = _post(client, hmn, {"birth_date": "1990-01-01"})
    assert r.status_code == 503 and "TRACE_HASH_KEY" in r.json()["detail"]
    assert chat.calls == [] and _n_traces(pg_engine) == 0


def test_hard_api_error_is_503(make, hmn):
    client, _ = make([HardApiError("insufficient_quota")])
    r = _post(client, hmn, {})
    assert r.status_code == 503 and "insufficient_quota" in r.json()["detail"]


def test_row_write_failure_still_returns_200_with_trace_error(make, hmn, monkeypatch):
    def boom(engine, row):
        raise RuntimeError("disk full")

    monkeypatch.setattr(trace, "write", boom)
    client, _ = make()
    r = _post(client, hmn, {})
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] is None and "disk full" in body["trace_error"]
    assert body["verdict"] == "INELIGIBLE"


def test_deps_without_an_openai_key_is_503(monkeypatch):
    monkeypatch.setattr(api.settings, "openai_api_key", "")
    api.get_verdict_deps.cache_clear()
    with pytest.raises(api.HTTPException) as e:
        api.get_verdict_deps()
    assert e.value.status_code == 503
