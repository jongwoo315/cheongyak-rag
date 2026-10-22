from sqlalchemy import create_engine, inspect

from tests.conftest import alembic


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_both_tables(pg_test_url):
    assert {"notices", "notice_models"} <= _tables(pg_test_url)


def test_downgrade_removes_tables_and_upgrade_restores(pg_test_url):
    alembic(pg_test_url, "downgrade", "0001")
    assert not {"notices", "notice_models"} & _tables(pg_test_url)

    alembic(pg_test_url, "upgrade", "head")
    assert {"notices", "notice_models"} <= _tables(pg_test_url)


def test_key_and_foreign_key_shape(pg_test_url):
    engine = create_engine(pg_test_url)
    try:
        insp = inspect(engine)
        assert insp.get_pk_constraint("notices")["constrained_columns"] == [
            "house_manage_no",
            "pblanc_no",
        ]
        assert insp.get_pk_constraint("notice_models")["constrained_columns"] == [
            "house_manage_no",
            "pblanc_no",
            "model_no",
        ]
        (fk,) = insp.get_foreign_keys("notice_models")
        assert fk["referred_table"] == "notices"
        assert fk["constrained_columns"] == ["house_manage_no", "pblanc_no"]
        assert fk["options"]["ondelete"] == "CASCADE"
        index_cols = [i["column_names"] for i in insp.get_indexes("notices")]
        assert ["rcrit_pblanc_de"] in index_cols
        assert ["subscrpt_area_nm"] in index_cols
    finally:
        engine.dispose()
