import pymupdf
import pytest
from sqlalchemy import text

from cheongyak_rag.golden.text import article_text, norm, pdf_pages, quote_in


@pytest.fixture
def two_page_pdf(tmp_path):
    path = tmp_path / "a.pdf"
    doc = pymupdf.open()
    for body in ("first page alpha", "second page beta gamma"):
        doc.new_page().insert_text((72, 72), body)
    doc.save(path)
    doc.close()
    return path


def test_pdf_pages_one_string_per_page(two_page_pdf):
    pages = pdf_pages(two_page_pdf)
    assert len(pages) == 2
    assert "alpha" in pages[0] and "beta" in pages[1]


def test_norm_collapses_whitespace_runs():
    assert norm("a \n\t b   c") == "a b c"
    assert norm("  x  ") == "x"


def test_quote_in_ignores_whitespace_only():
    assert quote_in("가입 기간", "청약통장 가입\n기간이 필요")
    assert quote_in("가입기간", "청약통장 가입 기간이 필요")  # 공백이 아예 없는 쪽도 같다
    assert not quote_in("가입 기간", "청약통장 납입 기간")


def test_quote_in_empty_quote_is_false():
    assert not quote_in("   ", "아무 글자")


def test_article_text_reads_chunk_body(pg_engine):
    cols = (
        "chunk_id, source, label, path, title, text, text_sha256, law_mst, embed_model,"
        " embedding, tokens"
    )
    tail = ", 'm', array_fill(0.1::real, ARRAY[1536])::vector, to_tsvector('simple', 'a')"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO chunks ({cols}) VALUES"
                f" ('law:제53조', 'law', '제53조', '제53조', '판', '본문 53', 'x', '286965'{tail}),"
                f" ('law:제53조@9', 'law', '제53조', '제53조', '판', '다른 판', 'y', '999'{tail})"
            )
        )
    assert article_text(pg_engine, "286965", "제53조") == "본문 53"
    assert article_text(pg_engine, "286965", "제999조") is None
