from sqlalchemy import create_engine, inspect

from tests.conftest import alembic


def _objects(url: str) -> tuple[set[str], set[str]]:
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        return set(insp.get_table_names()), set(insp.get_view_names())
    finally:
        engine.dispose()


def test_upgrade_creates_table_and_view(pg_test_url):
    tables, views = _objects(pg_test_url)
    assert "law_versions" in tables
    assert "notice_law_versions" in views


def test_downgrade_removes_both_and_upgrade_restores(pg_test_url):
    alembic(pg_test_url, "downgrade", "0002")
    tables, views = _objects(pg_test_url)
    assert "law_versions" not in tables
    assert "notice_law_versions" not in views
    assert "notices" in tables  # 0002는 그대로다

    alembic(pg_test_url, "upgrade", "head")
    tables, views = _objects(pg_test_url)
    assert "law_versions" in tables
    assert "notice_law_versions" in views


def test_key_and_index_shape(pg_test_url):
    engine = create_engine(pg_test_url)
    try:
        insp = inspect(engine)
        assert insp.get_pk_constraint("law_versions")["constrained_columns"] == [
            "law_id",
            "mst",
            "effective_date",
        ]
        assert ["law_id", "effective_date"] in [
            i["column_names"] for i in insp.get_indexes("law_versions")
        ]
        view_cols = [c["name"] for c in insp.get_columns("notice_law_versions")]
        assert view_cols == [
            "house_manage_no",
            "pblanc_no",
            "rcrit_pblanc_de",
            "mst",
            "effective_date",
            "promulgation_date",
            "promulgation_no",
        ]
    finally:
        engine.dispose()
