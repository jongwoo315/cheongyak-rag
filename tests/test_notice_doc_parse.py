from pathlib import Path

import pytest

from cheongyak_rag.ingest import notice_doc as nd

FIX = Path(__file__).parent / "fixtures"
DOC_URL = (
    "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do"
    "?houseManageNo=2026000517&pblancNo=2026000517&atchmnflSeqNo=2001261&atchmnflSn=6"
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        # RFC 5987: 실제 응답 꼴 (공백 %20, 한글 %EB…)
        (
            "attachment; filename*=UTF-8''2026000517%20GTX%EB%AC%B8.pdf",
            "2026000517 GTX문.pdf",
        ),
        ('attachment; filename="공고문.pdf"', "공고문.pdf"),
        ("attachment; filename=plain.hwp", "plain.hwp"),
        # 둘 다 있으면 filename*를 따른다 (순서와 무관)
        (
            "attachment; filename=\"old.hwp\"; filename*=UTF-8''new.pdf",
            "new.pdf",
        ),
        (
            "attachment; filename*=UTF-8''new.pdf; filename=\"old.hwp\"",
            "new.pdf",
        ),
        ("attachment", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_disposition(header, expected):
    assert nd.parse_disposition(header) == expected


def test_parse_disposition_bad_percent_falls_back_to_plain_filename():
    # filename*가 깨져도 filename=이 있으면 그것을 쓴다
    header = "attachment; filename*=UTF-8''%FF%FE.pdf; filename=\"ok.pdf\""
    assert nd.parse_disposition(header) == "ok.pdf"


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"%PDF-1.4\n...", "pdf"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "hwp"),
        (b"PK\x03\x04rest", "hwpx"),
        (b"<html>", "unknown"),
        (b"", "unknown"),
    ],
)
def test_magic_ext(head, expected):
    assert nd.magic_ext(head) == expected


def test_find_doc_links_reads_absolute_url_from_real_fragment():
    html = (FIX / "notice_doc_with_link.html").read_text(encoding="utf-8")
    assert nd.find_doc_links(html) == [DOC_URL]


def test_find_doc_links_empty_for_lh_fragment():
    html = (FIX / "notice_doc_no_link.html").read_text(encoding="utf-8")
    assert nd.find_doc_links(html) == []


def test_other_links_lists_external_links_without_doc_links():
    with_link = (FIX / "notice_doc_with_link.html").read_text(encoding="utf-8")
    no_link = (FIX / "notice_doc_no_link.html").read_text(encoding="utf-8")
    assert nd.other_links(with_link) == ["https://www.gtx운정중앙역시티프라디움.com"]
    assert nd.other_links(no_link) == ["https://apply.lh.or.kr/"]


def test_find_doc_links_dedups_and_keeps_order():
    html = (
        f'<a href="{DOC_URL}">a</a><a href="{DOC_URL}">b</a>'
        '<a href="https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?atchmnflSn=7">c</a>'
    )
    assert nd.find_doc_links(html) == [
        DOC_URL,
        "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?atchmnflSn=7",
    ]
