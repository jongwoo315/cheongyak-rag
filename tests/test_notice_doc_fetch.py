import hashlib
import itertools
from pathlib import Path

import httpx
import pymupdf
import pytest

from cheongyak_rag.ingest import notice_doc as nd

FIX = Path(__file__).parent / "fixtures"
HM = PB = "2026000517"
PAGE_URL = f"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo={HM}&pblancNo={PB}"
DOC_URL = (
    "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do"
    f"?houseManageNo={HM}&pblancNo={PB}&atchmnflSeqNo=2001261&atchmnflSn=6"
)
FILE_NAME = "2026000517_2026000517_2001261_6"
RFC5987 = "attachment; filename*=UTF-8''2026000517%20GTX%EB%AC%B8.pdf"
WITH_LINK = (FIX / "notice_doc_with_link.html").read_text(encoding="utf-8")
NO_LINK = (FIX / "notice_doc_no_link.html").read_text(encoding="utf-8")


def make_pdf(text: str | None = "Notice 123") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    return doc.tobytes()


class Site:
    """청약홈 흉내. 요청 순서대로 응답을 꺼내 쓰고, 요청 기록을 남긴다."""

    def __init__(self, page=WITH_LINK, doc=None):
        self.page = page
        self.doc = doc  # httpx.Response 하나 또는 그 목록(요청마다 하나씩 꺼낸다)
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.host == "www.applyhome.co.kr":
            page = self.page
            if isinstance(page, list):
                page = page.pop(0) if len(page) > 1 else page[0]
            if isinstance(page, httpx.Response):
                return page
            return httpx.Response(200, text=page)
        doc = self.doc
        if isinstance(doc, list):
            doc = doc.pop(0) if len(doc) > 1 else doc[0]
        return doc

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    @property
    def doc_requests(self) -> int:
        return sum("getAtchmnfl.do" in r for r in self.requests)


def attach(body: bytes, disposition: str | None = RFC5987, status: int = 200, **headers):
    h = {"Content-Type": "application/octet-stream;charset=UTF-8", **headers}
    if disposition is not None:
        # 서버가 날것의 UTF-8 바이트로 보내는 경우도 있다
        h["Content-Disposition"] = disposition.encode("utf-8")
    return httpx.Response(status, content=body, headers=h)


def run(site, tmp_path, previous=None, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return nd.collect_notice(
        site.client(),
        HM,
        PB,
        PAGE_URL,
        out_dir=tmp_path / "notices",
        previous=previous,
        sleep=sleeps.append,
    )


def test_rfc5987_header_saves_pdf_with_open_check(tmp_path):
    body = make_pdf()
    out = run(Site(doc=attach(body)), tmp_path)

    (row,) = out.rows
    assert out.result == "pdf" and row["result"] == "pdf"
    assert row["path"] == str(tmp_path / "notices" / f"{FILE_NAME}.pdf")
    assert Path(row["path"]).read_bytes() == body
    assert row["header_filename"] == "2026000517 GTX문.pdf"
    assert (row["header_ext"], row["magic_ext"], row["ext_mismatch"]) == ("pdf", "pdf", False)
    assert row["bytes"] == len(body) and row["sha256"] == hashlib.sha256(body).hexdigest()
    assert row["pages"] == 1 and row["text_chars"] > 0
    assert row["house_manage_no"] == HM and row["pblanc_no"] == PB and row["url"] == DOC_URL
    assert row["error"] is None and row["note"] is None and row["fetched_at"]
    assert (out.new_downloads, out.downloaded_bytes) == (1, len(body))


def test_plain_filename_header(tmp_path):
    out = run(Site(doc=attach(make_pdf(), 'attachment; filename="공고문.pdf"')), tmp_path)
    assert out.rows[0]["header_filename"] == "공고문.pdf" and out.rows[0]["result"] == "pdf"


def test_both_header_forms_follow_filename_star(tmp_path):
    header = "attachment; filename=\"old.hwp\"; filename*=UTF-8''new.pdf"
    out = run(Site(doc=attach(make_pdf(), header)), tmp_path)
    row = out.rows[0]
    assert row["header_filename"] == "new.pdf" and row["ext_mismatch"] is False


def test_no_header_uses_magic_bytes_and_notes_it(tmp_path):
    out = run(Site(doc=attach(make_pdf(), None)), tmp_path)
    row = out.rows[0]
    assert row["result"] == "pdf" and row["path"].endswith(f"{FILE_NAME}.pdf")
    assert row["header_filename"] is None and row["header_ext"] is None
    assert row["ext_mismatch"] is False and row["note"] == "헤더 없음"


@pytest.mark.parametrize(
    ("body", "result", "ext"),
    [
        (b"\xd0\xcf\x11\xe0" + b"\0" * 64, "hwp", "hwp"),
        (b"PK\x03\x04" + b"\0" * 64, "hwp", "hwpx"),
        (b"<html>not a notice</html>", "other", "bin"),
    ],
)
def test_non_pdf_goes_to_quarantine_and_is_not_opened(tmp_path, body, result, ext):
    out = run(Site(doc=attach(body, "attachment; filename=x.hwp")), tmp_path)
    row = out.rows[0]
    assert out.result == result and row["result"] == result
    assert row["path"] == str(tmp_path / "notices" / "quarantine" / f"{FILE_NAME}.{ext}")
    assert Path(row["path"]).read_bytes() == body
    assert row["pages"] is None and row["text_chars"] is None and row["error"] is None
    assert not (tmp_path / "notices" / f"{FILE_NAME}.pdf").exists()


def test_extension_mismatch_follows_magic_bytes(tmp_path):
    out = run(Site(doc=attach(make_pdf(), "attachment; filename=real.hwp")), tmp_path)
    row = out.rows[0]
    assert row["result"] == "pdf" and row["path"].endswith(".pdf")
    assert (row["header_ext"], row["magic_ext"], row["ext_mismatch"]) == ("hwp", "pdf", True)


def test_pdf_that_does_not_open_is_error_and_keeps_no_file(tmp_path):
    body = b"%PDF-1.4\nthis is not a pdf at all"
    out = run(Site(doc=attach(body)), tmp_path)
    row = out.rows[0]
    assert out.result == "error" and row["result"] == "error"
    assert "PDF" in row["error"] and row["path"] is None
    assert row["bytes"] == len(body) and row["sha256"] == hashlib.sha256(body).hexdigest()
    assert not list((tmp_path / "notices").glob("*.pdf"))


def test_pdf_without_text_is_pdf_with_zero_chars(tmp_path):
    out = run(Site(doc=attach(make_pdf(None))), tmp_path)
    row = out.rows[0]
    assert row["result"] == "pdf" and row["pages"] == 1 and row["text_chars"] == 0


def test_size_limit_stops_download_and_counts_error(tmp_path, monkeypatch):
    monkeypatch.setattr(nd, "MAX_BYTES", 100)
    out = run(Site(doc=attach(b"%PDF-" + b"x" * 500)), tmp_path)
    row = out.rows[0]
    assert row["result"] == "error" and "50MB" in row["error"] and row["path"] is None
    assert out.new_downloads == 0


def test_429_then_success_backs_off(tmp_path):
    site = Site(doc=[attach(b"", None, status=429), attach(make_pdf())])
    sleeps: list[float] = []
    out = run(site, tmp_path, sleeps=sleeps)
    assert out.rows[0]["result"] == "pdf" and site.doc_requests == 2
    # 요청 사이 0.5초(페이지·첨부·재시도 첨부) + 첫 재시도 전 1초
    assert sleeps == [0.5, 0.5, 1, 0.5]


def test_5xx_four_retries_then_error(tmp_path):
    site = Site(doc=attach(b"", None, status=503))
    sleeps: list[float] = []
    out = run(site, tmp_path, sleeps=sleeps)
    row = out.rows[0]
    assert row["result"] == "error" and "503" in row["error"] and "4" in row["error"]
    assert site.doc_requests == 5
    assert [s for s in sleeps if s != 0.5] == [1, 2, 4, 8]


def test_connection_error_is_retried(tmp_path):
    calls = []

    def handler(request):
        if request.url.host == "www.applyhome.co.kr":
            return httpx.Response(200, text=WITH_LINK)
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        return attach(make_pdf())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = nd.collect_notice(client, HM, PB, PAGE_URL, out_dir=tmp_path / "n", sleep=lambda _s: None)
    assert out.rows[0]["result"] == "pdf" and len(calls) == 2


def test_404_is_not_retried(tmp_path):
    site = Site(doc=attach(b"", None, status=404))
    out = run(site, tmp_path)
    assert out.rows[0]["result"] == "error" and "404" in out.rows[0]["error"]
    assert site.doc_requests == 1


def test_rerun_does_not_download_again(tmp_path):
    site = Site(doc=attach(make_pdf()))
    first = run(site, tmp_path)
    previous = {r["url"]: r for r in first.rows}

    site2 = Site(doc=attach(b"should not be requested"))
    second = run(site2, tmp_path, previous=previous)

    assert site2.doc_requests == 0
    assert (second.new_downloads, second.downloaded_bytes) == (0, 0)
    assert second.result == first.result and second.rows == first.rows


def test_rerun_downloads_again_when_file_changed_or_gone(tmp_path):
    first = run(Site(doc=attach(make_pdf())), tmp_path)
    previous = {r["url"]: r for r in first.rows}
    path = Path(first.rows[0]["path"])

    path.write_bytes(path.read_bytes() + b"tamper")  # 크기·sha256이 목록과 다르다
    site = Site(doc=attach(make_pdf()))
    assert run(site, tmp_path, previous=previous).new_downloads == 1 and site.doc_requests == 1

    path.unlink()  # 파일이 없다
    site = Site(doc=attach(make_pdf()))
    assert run(site, tmp_path, previous=previous).new_downloads == 1 and site.doc_requests == 1


def test_rerun_retries_previous_error(tmp_path):
    failed = run(Site(doc=attach(b"", None, status=404)), tmp_path)
    previous = {r["url"]: r for r in failed.rows}
    site = Site(doc=attach(make_pdf()))
    out = run(site, tmp_path, previous=previous)
    assert out.result == "pdf" and site.doc_requests == 1


def test_no_link_notice_keeps_one_row_with_other_links_in_note(tmp_path):
    site = Site(page=NO_LINK)
    out = run(site, tmp_path)
    (row,) = out.rows
    assert out.result == "no_link" and row["result"] == "no_link" and row["url"] is None
    assert row["error"] is None and "https://apply.lh.or.kr/" in row["note"]
    assert row["path"] is None and site.doc_requests == 0


def test_page_failure_is_error_row(tmp_path):
    site = Site(page=httpx.Response(404, text="not found"))
    out = run(site, tmp_path)
    (row,) = out.rows
    assert out.result == "error" and row["url"] is None and "404" in row["error"]


def test_netfunnel_page_waits_30s_then_retries(tmp_path):
    wait = "<html><script src='/netfunnel/netfunnel.js'></script>NetFUNNEL 대기</html>"
    site = Site(page=[wait, WITH_LINK], doc=attach(make_pdf()))
    sleeps: list[float] = []
    out = run(site, tmp_path, sleeps=sleeps)
    assert out.result == "pdf" and 30 in sleeps


def test_netfunnel_page_twice_is_error(tmp_path):
    wait = "<html>NetFUNNEL 대기</html>"
    out = run(Site(page=wait), tmp_path)
    assert out.result == "error" and "NetFUNNEL" in out.rows[0]["error"]


def test_notice_result_is_the_worst_of_its_links(tmp_path):
    two = WITH_LINK.replace(
        "</dl>",
        f'<dd><a href="{DOC_URL.replace("atchmnflSn=6", "atchmnflSn=7")}">second</a></dd></dl>',
    )
    site = Site(page=two, doc=[attach(make_pdf()), attach(b"\xd0\xcf\x11\xe0" + b"\0" * 8)])
    out = run(site, tmp_path)
    assert [r["result"] for r in out.rows] == ["pdf", "hwp"]
    assert out.result == "hwp"
    assert out.rows[1]["path"].endswith("2026000517_2026000517_2001261_7.hwp")


def test_content_length_over_limit_is_refused_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(nd, "MAX_BYTES", 100)
    out = run(Site(doc=attach(make_pdf())), tmp_path)  # make_pdf()는 100바이트를 넘는다
    assert out.rows[0]["result"] == "error" and "받기 전에" in out.rows[0]["error"]


def test_netfunnel_page_in_place_of_attachment_is_error_not_other(tmp_path):
    body = b"<html><script src='/netfunnel.js'></script>NetFUNNEL</html>"
    out = run(Site(doc=attach(body, None)), tmp_path)
    row = out.rows[0]
    assert row["result"] == "error" and "NetFUNNEL" in row["error"] and row["path"] is None
    assert not (tmp_path / "notices" / "quarantine").exists()


def test_total_time_limit_counts_as_timeout_and_retries(tmp_path, monkeypatch):
    ticks = itertools.count(0, 500)  # 부를 때마다 500초가 지난다
    monkeypatch.setattr(nd.time, "monotonic", lambda: next(ticks))
    out = run(Site(doc=attach(make_pdf())), tmp_path)
    assert out.rows[0]["result"] == "error" and "ReadTimeout" in out.rows[0]["error"]


def test_second_link_crash_keeps_first_links_row(tmp_path, monkeypatch):
    two = WITH_LINK.replace(
        "</dl>",
        f'<dd><a href="{DOC_URL.replace("atchmnflSn=6", "atchmnflSn=7")}">second</a></dd></dl>',
    )
    real_save = nd._save
    calls = []

    def flaky(path, body):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real_save(path, body)

    monkeypatch.setattr(nd, "_save", flaky)
    out = run(Site(page=two, doc=attach(make_pdf())), tmp_path)
    assert [r["result"] for r in out.rows] == ["pdf", "error"]
    assert out.rows[1]["url"].endswith("atchmnflSn=7") and "disk full" in out.rows[1]["error"]
    assert out.new_downloads == 1  # 저장된 첫 링크는 센다
