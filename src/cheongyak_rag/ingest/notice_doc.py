"""청약홈 공고 상세 페이지에서 공고문 첨부를 받아 `data/raw/notices/`에 둔다 (#72).

공고 목록은 실제 DB `notices`에서 읽기만 한다. 공고마다 상세 페이지를 받아 공고문 링크를 찾고,
링크마다 첨부를 받아 앞 바이트로 확장자를 정한다. PDF는 `data/raw/notices/`, 그 밖은
`data/raw/notices/quarantine/`에 두고 목록(`manifest.jsonl`)에 한 줄씩 남긴다.
"""

import re
from html.parser import HTMLParser
from urllib.parse import unquote

# ── 헤더·앞 바이트·링크 ───────────────────────────────────────────────────

_DOC_PATH = "getAtchmnfl.do"
_EXT_STAR = re.compile(r"filename\*\s*=\s*([^;]*)", re.IGNORECASE)
_EXT_PLAIN = re.compile(r'(?<![\w*])filename\s*=\s*("([^"]*)"|[^;]*)', re.IGNORECASE)


def parse_disposition(header: str | None) -> str | None:
    """`Content-Disposition`의 파일 이름. `filename*`(RFC 5987)를 `filename`보다 먼저 따른다."""
    if not header:
        return None
    star = _EXT_STAR.search(header)
    if star:
        # charset'lang'퍼센트인코딩 — 깨졌으면 filename= 꼴로 넘어간다
        parts = star.group(1).strip().split("'", 2)
        if len(parts) == 3:
            charset = parts[0] or "utf-8"
            try:
                name = unquote(parts[2], encoding=charset, errors="strict").strip()
            except (LookupError, UnicodeDecodeError):
                name = ""
            if name:
                return name
    plain = _EXT_PLAIN.search(header)
    if plain:
        name = (plain.group(2) if plain.group(2) is not None else plain.group(1)).strip()
        return name or None
    return None


def magic_ext(head: bytes) -> str:
    """파일 앞 바이트로 `pdf` · `hwp`(OLE) · `hwpx`(zip) · `unknown`을 정한다."""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if head.startswith(b"PK\x03\x04"):
        return "hwpx"
    return "unknown"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href.strip())


def _hrefs(html: str) -> list[str]:
    parser = _Links()
    parser.feed(html)
    return parser.hrefs


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def find_doc_links(html: str) -> list[str]:
    """상세 페이지의 공고문 링크(`getAtchmnfl.do` 절대 URL). 순서를 지키고 겹치면 하나만."""
    return _dedup(
        [h for h in _hrefs(html) if h.startswith(("http://", "https://")) and _DOC_PATH in h]
    )


def other_links(html: str) -> list[str]:
    """공고문 링크가 아닌 외부 링크. 링크 없음 공고의 `note`에 적는다."""
    return _dedup(
        [h for h in _hrefs(html) if h.startswith(("http://", "https://")) and _DOC_PATH not in h]
    )
