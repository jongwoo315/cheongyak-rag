from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic

INDEXES = {
    "traces_created_at_idx": "(created_at)",
    "traces_notice_idx": "(house_manage_no, pblanc_no)",
    "traces_profile_hash_idx": "(profile_hash)",
}
# 설계 §`traces` 칸: (이름, 타입, null 가능)
COLUMNS = [
    ("id", "bigint", False),
    ("created_at", "timestamp with time zone", False),
    ("house_manage_no", "text", False),
    ("pblanc_no", "text", True),
    ("profile_hash", "text", False),
    ("status", "text", False),
    ("error", "text", True),
    ("verdict", "text", True),
    ("model", "text", False),
    ("system_sha", "text", False),
    ("seconds", "double precision", False),
    ("steps", "jsonb", False),
    ("answer", "jsonb", True),
]


def _indexdefs(url: str) -> dict[str, str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'traces'")
            )
            return {r[0]: r[1] for r in rows}
    finally:
        engine.dispose()


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_table_with_design_columns(pg_test_url):
    engine = create_engine(pg_test_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
                    " WHERE table_name = 'traces' ORDER BY ordinal_position"
                )
            )
            got = [(r[0], r[1], r[2] == "YES") for r in rows]
        assert got == COLUMNS
        assert inspect(engine).get_pk_constraint("traces")["constrained_columns"] == ["id"]
    finally:
        engine.dispose()


def test_created_at_defaults_to_now(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO traces (house_manage_no, profile_hash, status, model, system_sha,"
                " seconds, steps) VALUES ('h', 'p', 'ok', 'm', 's', 0.5, '{}'::jsonb)"
            )
        )
        n = conn.execute(text("SELECT count(*) FROM traces WHERE created_at IS NOT NULL")).scalar()
    assert n == 1


def test_three_indexes_have_the_designed_columns(pg_test_url):
    defs = _indexdefs(pg_test_url)
    for name, cols in INDEXES.items():
        assert name in defs and cols in defs[name]


def test_downgrade_removes_table_and_upgrade_restores(pg_test_url):
    alembic(pg_test_url, "downgrade", "0004")
    try:
        assert "traces" not in _tables(pg_test_url)
        assert "chunks" in _tables(pg_test_url)  # 0004는 그대로다
    finally:
        # 실패해도 세션 공용 DB를 head로 돌려놓는다
        alembic(pg_test_url, "upgrade", "head")
    assert "traces" in _tables(pg_test_url)
    assert INDEXES.keys() <= _indexdefs(pg_test_url).keys()
