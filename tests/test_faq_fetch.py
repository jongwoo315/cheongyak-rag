import httpx
import pytest

from cheongyak_rag.ingest import faq


def test_cached_file_skips_network(tmp_path, monkeypatch):
    dest = tmp_path / "faq.pdf"
    dest.write_bytes(b"%PDF-cached")

    def boom(*args, **kwargs):
        raise AssertionError("네트워크를 탔다")

    monkeypatch.setattr(httpx, "Client", boom)

    assert faq.fetch_pdf(dest) == dest
    assert dest.read_bytes() == b"%PDF-cached"


def test_downloads_with_user_agent_and_cookie_jar(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "ck" not in request.headers.get("cookie", ""):
            # molit.go.kr은 쿠키 없이 오면 리다이렉트를 반복한다
            return httpx.Response(302, headers={"location": str(request.url), "set-cookie": "ck=1"})
        return httpx.Response(200, content=b"%PDF-new")

    dest = tmp_path / "raw" / "faq.pdf"
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    assert faq.fetch_pdf(dest, client=client) == dest
    assert dest.read_bytes() == b"%PDF-new"
    assert all("python-httpx" not in r.headers["user-agent"] for r in seen)


def test_failed_download_leaves_no_file(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    dest = tmp_path / "faq.pdf"

    with pytest.raises(httpx.HTTPStatusError):
        faq.fetch_pdf(dest, client=client)
    assert not dest.exists()


def test_non_pdf_200_response_is_not_cached(tmp_path):
    html = httpx.Response(200, content=b"<html>x</html>", headers={"content-type": "text/html"})
    client = httpx.Client(transport=httpx.MockTransport(lambda r: html))
    dest = tmp_path / "faq.pdf"

    with pytest.raises(ValueError, match="PDF가 아닌"):
        faq.fetch_pdf(dest, client=client)
    assert not dest.exists()
