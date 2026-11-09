from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic

COLUMNS = [("day", "date", False), ("count", "integer", False)]


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_table_with_a_date_pk_and_an_int_count(pg_test_url):
    engine = create_engine(pg_test_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
                    " WHERE table_name = 'verdict_daily_count' ORDER BY ordinal_position"
                )
            )
            assert [(r[0], r[1], r[2] == "YES") for r in rows] == COLUMNS
        pk = inspect(engine).get_pk_constraint("verdict_daily_count")
        assert pk["constrained_columns"] == ["day"]
    finally:
        engine.dispose()


def test_downgrade_removes_table_and_upgrade_restores(pg_test_url):
    alembic(pg_test_url, "downgrade", "0005")
    try:
        assert "verdict_daily_count" not in _tables(pg_test_url)
        assert "traces" in _tables(pg_test_url)  # 0005는 그대로다
    finally:
        # 실패해도 세션 공용 DB를 head로 돌려놓는다
        alembic(pg_test_url, "upgrade", "head")
    assert "verdict_daily_count" in _tables(pg_test_url)
