import os
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from cheongyak_rag.config import settings

PDF_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "faq-20240529.pdf"


@pytest.fixture(scope="session")
def faq_doc():
    # 조용한 skip 금지 — PDF가 없으면 실패시킨다
    if not PDF_PATH.exists():
        pytest.fail(f"FAQ PDF 없음: {PDF_PATH}")
    with pymupdf.open(PDF_PATH) as doc:
        yield doc


@pytest.fixture(scope="session")
def toc(faq_doc):
    from cheongyak_rag.ingest.faq import parse_toc

    return parse_toc(faq_doc)


@pytest.fixture(scope="session")
def pairs(faq_doc):
    from cheongyak_rag.ingest.faq import parse_body

    return parse_body(faq_doc)


TEST_DB = "cheongyak_test"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pg_test_url() -> str:
    """실제 적재 DB와 분리된 `cheongyak_test` DB의 URL. 없으면 만들고 마이그레이션까지 올린다.

    URL은 DATABASE_URL의 DB 이름을 바꿔서 만든다. 문자열에 `_test`를 덧붙이면 쿼리스트링이 있는
    URL에서 엉뚱한 곳이 바뀐다.
    """
    real = make_url(settings.database_url)
    test = real.set(database=TEST_DB)
    # 조용한 skip 금지 — Postgres가 없으면 실패시킨다
    admin = create_engine(real, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except OperationalError as e:
        pytest.fail(f"Postgres에 연결할 수 없다 ({real.host}:{real.port}): {type(e).__name__}")
    finally:
        admin.dispose()
    url = test.render_as_string(hide_password=False)
    alembic(url, "upgrade", "head")
    return url


def alembic(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


@pytest.fixture
def pg_engine(pg_test_url):
    """테스트마다 두 테이블을 비운 테스트 DB 엔진."""
    engine = create_engine(pg_test_url)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE notice_models, notices"))
    yield engine
    engine.dispose()
