"""Neon 적재 스크립트 (#85). 대상은 같은 컨테이너에 만든 임시 DB다. 원본 DB는 읽기만 한다."""

import os
import subprocess

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from cheongyak_rag import deploy_load as dl
from cheongyak_rag.config import settings


def test_same_database_by_host_and_name_with_local_aliases():
    a = make_url("postgresql+psycopg://u:p@localhost:5433/cheongyak")
    assert dl.same_database(a, make_url("postgresql://x:y@127.0.0.1:5432/cheongyak"))
    assert dl.same_database(a, make_url("postgresql://x:y@host.docker.internal/cheongyak"))
    assert not dl.same_database(a, make_url("postgresql://u:p@localhost:5433/other"))
    assert not dl.same_database(a, make_url("postgresql://u:p@ep-x.neon.tech/cheongyak"))
    neon = make_url("postgresql://u:p@ep-x.neon.tech/cheongyak")
    assert dl.same_database(neon, make_url("postgresql://u2:p2@EP-X.neon.tech:5432/cheongyak"))


def test_normalize_and_libpq_keep_the_query_string():
    u = dl.normalize("postgres://u:p@h/db?sslmode=require")
    assert u.drivername == "postgresql+psycopg"
    assert dl.to_libpq(u) == "postgresql://u:p@h/db?sslmode=require"


def test_container_url_rewrites_only_local_hosts():
    local = dl.container_url(make_url("postgresql://u:p@localhost:5433/db"))
    assert local.host == "host.docker.internal" and local.port == 5433
    assert dl.container_url(make_url("postgresql://u:p@ep-x.neon.tech/db")).host == "ep-x.neon.tech"


def test_redact_hides_password_and_url():
    u = make_url("postgresql://user:s3cr3t@h/db")
    assert "s3cr3t" not in dl.redact("fail postgresql://user:s3cr3t@h/db (s3cr3t)", u)


def test_compare_flags_a_different_count_and_a_missing_table():
    lines, ok = dl.compare({"a": 2, "b": 3}, {"a": 2, "b": 1})
    assert not ok and "다르다" in lines[2]
    lines, ok = dl.compare({"a": 2}, {})
    assert not ok and lines[1].rstrip().endswith("다르다")
    assert dl.compare({"a": 2}, {"a": 2})[1]


def test_refuses_the_source_database_without_running_anything(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("아무것도 실행하면 안 된다")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    out: list[str] = []
    assert dl.run(settings.database_url, out=out.append) == 1
    assert "거부" in out[0]
    # 같은 호스트의 다른 표기(127.0.0.1)로 적어도 막는다
    alias = make_url(settings.database_url).set(host="127.0.0.1")
    assert dl.run(alias.render_as_string(hide_password=False), out=out.append) == 1


@pytest.fixture
def target_url():
    """원본과 같은 컨테이너에 임시 DB를 만들고 지운다. 이름은 cheongyak_test_load_<pid>."""
    real = make_url(settings.database_url)
    name = f"cheongyak_test_load_{os.getpid()}"
    assert name != real.database
    admin = sa.create_engine(real, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    except sa.exc.OperationalError as e:
        admin.dispose()
        pytest.fail(f"Postgres에 연결할 수 없다: {type(e).__name__}")  # 조용한 skip 금지
    try:
        yield real.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _counts(url: str, tables: list[str]) -> dict[str, int]:
    engine = sa.create_engine(url)
    try:
        return dl.count_rows(engine, tables)
    finally:
        engine.dispose()


def test_load_copies_every_movable_table_and_skips_the_three_excluded(target_url):
    out: list[str] = []
    assert dl.run(target_url, out=out.append) == 0, "\n".join(out)
    src = sa.create_engine(settings.database_url)
    try:
        tables = dl.movable_tables(src)
        want = dl.count_rows(src, tables)
    finally:
        src.dispose()
    assert {"notices", "notice_models", "law_versions", "chunks"} <= set(tables)
    assert not (dl.EXCLUDED & set(tables))
    assert _counts(target_url, tables) == want and all(want.values())
    # 옮기지 않는 테이블은 대상에서 비어 있다(traces·하루 판정 한도)
    assert _counts(target_url, ["traces", "verdict_daily_count"]) == {
        "traces": 0,
        "verdict_daily_count": 0,
    }
    text = "\n".join(out)
    # 대상 URL·비밀번호는 출력에 없다 (로컬 비밀번호가 사용자명과 같아 `:비밀번호@` 꼴로 본다)
    assert target_url not in text and f":{make_url(target_url).password}@" not in text
    assert "전부 같다" in text


def test_second_load_into_a_filled_target_is_refused_and_leaves_counts_alone(target_url):
    assert dl.run(target_url, out=lambda s: None) == 0
    tables = ["notices", "notice_models", "law_versions", "chunks"]
    before = _counts(target_url, tables)
    out: list[str] = []
    assert dl.run(target_url, out=out.append) == 1
    assert "이미 행이 있다" in "\n".join(out)
    assert _counts(target_url, tables) == before


def test_count_mismatch_after_copy_exits_nonzero(target_url, monkeypatch):
    monkeypatch.setattr(dl, "copy_data", lambda *a, **kw: None)  # 아무것도 안 옮긴다
    out: list[str] = []
    assert dl.run(target_url, out=out.append) == 1
    assert "다르다" in "\n".join(out)


def test_main_requires_target_url():
    with pytest.raises(SystemExit):
        dl.main([])
