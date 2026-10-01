from pathlib import Path

import pymupdf
import pytest

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
