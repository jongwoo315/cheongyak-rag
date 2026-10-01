"""국토교통부 「주택청약 FAQ」 PDF를 Q&A 쌍으로 파싱한다 (#70)."""

from pathlib import Path

import httpx

PDF_URL = "https://www.molit.go.kr/portal/common/download/DownloadMltm2.jsp"
PDF_PARAMS = {
    "FilePath": "portal/DextUpload/202405/20240529_165121_948.pdf",
    "FileName": "★ 2024 주택청약 FAQ.pdf",
}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0"


def fetch_pdf(dest: Path, client: httpx.Client | None = None) -> Path:
    """dest에 PDF가 있으면 그대로 돌려주고, 없으면 받는다."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    # httpx.Client는 쿠키를 유지한다. molit.go.kr은 쿠키 없이 리다이렉트를 무한 반복한다
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=60)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        resp = client.get(PDF_URL, params=PDF_PARAMS, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
        if own:
            client.close()
    return dest
