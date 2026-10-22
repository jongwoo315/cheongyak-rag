from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from cheongyak_rag.config import settings


def test_pg_test_url_points_at_a_different_database(pg_test_url):
    assert make_url(pg_test_url).database == "cheongyak_test"
    assert make_url(pg_test_url).database != make_url(settings.database_url).database


def test_pg_test_url_is_migrated(pg_test_url):
    engine = create_engine(pg_test_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
