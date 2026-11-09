"""청약홈 공고 상세 페이지에서 공고문 첨부를 받아 `data/raw/notices/`에 둔다 (#72).

공고 목록은 실제 DB `notices`에서 읽기만 한다. 공고마다 상세 페이지를 받아 공고문 링크를 찾고,
링크마다 첨부를 받아 앞 바이트로 확장자를 정한다. PDF는 `data/raw/notices/`, 그 밖은
`data/raw/notices/quarantine/`에 두고 목록(`manifest.jsonl`)에 한 줄씩 남긴다.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pymupdf
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings

PACE = 0.5  # 요청 사이 간격(초)
BACKOFF = (1, 2, 4, 8)  # 429·5xx·연결 오류 재시도 대기(초). 최대 4회
RETRY_STATUS = (429, *range(500, 600))
MAX_BYTES = 50 * 1024 * 1024
PAGE_TIMEOUT = 30.0
FILE_TIMEOUT = 120.0
NETFUNNEL_WAIT = 30
NOTICE_DIR = Path("data/raw/notices")
DEFAULT_OUT = Path("runs/72/last_run.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RESULTS = ("pdf", "hwp", "other", "no_link", "error")
_SEVERITY = {"pdf": 0, "hwp": 1, "other": 2, "error": 3}  # 공고 결과는 가장 나쁜 줄을 따른다

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


# ── 받기 ─────────────────────────────────────────────────────────────────


class FetchError(RuntimeError):
    """받기가 실패했다. 문구가 그대로 목록의 `error`가 된다."""


def _read_body(resp: httpx.Response, timeout: float) -> bytes:
    declared = resp.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise FetchError("첨부가 50MB를 넘는다(받기 전에 멈춤)")
    buf = bytearray()
    deadline = time.monotonic() + timeout
    for chunk in resp.iter_bytes():
        buf += chunk
        if len(buf) > MAX_BYTES:
            raise FetchError("첨부가 50MB를 넘는다(받다 멈춤)")
        if time.monotonic() > deadline:
            raise httpx.ReadTimeout(f"전체 {timeout:g}초 안에 다 못 받았다")
    return bytes(buf)


def _download(client: httpx.Client, url: str, timeout: float, sleep) -> tuple[httpx.Headers, bytes]:
    """GET 한 번. 429·5xx·연결 오류는 BACKOFF만큼 쉬며 다시 시도한다."""
    problem = ""
    for attempt in range(len(BACKOFF) + 1):
        sleep(PACE)
        try:
            with client.stream("GET", url, timeout=timeout) as resp:
                if resp.status_code == 200:
                    return resp.headers, _read_body(resp, timeout)
                problem = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUS:
                    raise FetchError(problem)
        except httpx.HTTPError as e:
            problem = f"{type(e).__name__}: {str(e)[:200]}"
        if attempt == len(BACKOFF):
            raise FetchError(f"재시도 {len(BACKOFF)}회 뒤에도 실패: {problem}")
        sleep(BACKOFF[attempt])
    raise AssertionError("unreachable")


def _is_wait_page(html: str) -> bool:
    return "netfunnel" in html.lower() and "pop_btn_txt" not in html


def _fetch_page(client: httpx.Client, url: str, sleep) -> str:
    for attempt in range(2):
        _, body = _download(client, url, PAGE_TIMEOUT, sleep)
        html = body.decode("utf-8", errors="replace")
        if not _is_wait_page(html):
            return html
        if attempt == 0:
            sleep(NETFUNNEL_WAIT)
    raise FetchError("NetFUNNEL 대기 페이지가 30초 뒤에도 온다")


# ── 공고 하나 ─────────────────────────────────────────────────────────────


@dataclass
class NoticeResult:
    rows: list[dict]
    result: str
    new_downloads: int = 0
    downloaded_bytes: int = 0


def _row(hm: str, pb: str, url: str | None, **kw) -> dict:
    row = {
        "house_manage_no": hm,
        "pblanc_no": pb,
        "url": url,
        "header_filename": None,
        "header_ext": None,
        "magic_ext": None,
        "ext_mismatch": None,
        "result": None,
        "path": None,
        "bytes": None,
        "sha256": None,
        "pages": None,
        "text_chars": None,
        "error": None,
        "note": None,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return row | kw


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reusable(prev: dict | None) -> bool:
    """목록에 받은 줄이 있고 파일의 크기·sha256이 그 줄과 같으면 다시 받지 않는다."""
    if not prev or prev.get("result") not in ("pdf", "hwp", "other") or not prev.get("path"):
        return False
    path = Path(prev["path"])
    return (
        path.is_file()
        and path.stat().st_size == prev.get("bytes")
        and _sha256_file(path) == prev.get("sha256")
    )


def _inspect_pdf(body: bytes) -> tuple[int, int]:
    """(쪽수, 공백을 뺀 글자 수). 안 열리거나 쪽수가 0이면 예외."""
    with pymupdf.open(stream=body, filetype="pdf") as doc:
        if doc.page_count < 1:
            raise ValueError("쪽수가 0이다")
        return doc.page_count, sum(len("".join(page.get_text().split())) for page in doc)


def _save(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_bytes(body)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _collect_link(
    client: httpx.Client, hm: str, pb: str, url: str, out_dir: Path, sleep
) -> tuple[dict, int | None]:
    """링크 하나 → (목록 줄, 새로 받은 바이트. 못 받았으면 None)."""
    query = parse_qs(urlparse(url).query)
    seq, sn = (query.get(k, [""])[0] for k in ("atchmnflSeqNo", "atchmnflSn"))
    if not (seq and sn):
        return _row(
            hm, pb, url, result="error", error="링크에 atchmnflSeqNo·atchmnflSn이 없다"
        ), None
    try:
        headers, body = _download(client, url, FILE_TIMEOUT, sleep)
    except FetchError as e:
        return _row(hm, pb, url, result="error", error=str(e)), None

    disposition = headers.get("content-disposition")
    filename = parse_disposition(disposition)
    suffix = Path(filename).suffix.lstrip(".").lower() if filename else ""
    header_ext = suffix or None
    magic = magic_ext(body[:8])
    note = None
    if disposition is None:
        note = "헤더 없음"
    elif filename is None:
        note = "헤더에 파일 이름 없음"
    row = _row(
        hm,
        pb,
        url,
        header_filename=filename,
        header_ext=header_ext,
        magic_ext=magic,
        ext_mismatch=header_ext is not None and header_ext != magic,
        bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        note=note,
    )
    if magic == "unknown" and b"netfunnel" in body[:4096].lower():
        # 대기 페이지를 공고문으로 저장하면 이후 실행이 계속 재사용한다
        return row | {"result": "error", "error": "NetFUNNEL 대기 페이지가 첨부 대신 왔다"}, None
    stem = f"{hm}_{pb}_{seq}_{sn}"
    if magic == "pdf":
        try:
            pages, chars = _inspect_pdf(body)
        except Exception as e:  # noqa: BLE001 — 깨진 파일이 어떤 예외를 내든 이 공고만 오류로 센다
            return row | {
                "result": "error",
                "error": f"PDF를 열 수 없다: {type(e).__name__}: {str(e)[:200]}",
            }, len(body)
        path = out_dir / f"{stem}.pdf"
        row |= {"result": "pdf", "pages": pages, "text_chars": chars}
    else:
        ext = magic if magic != "unknown" else "bin"
        path = out_dir / "quarantine" / f"{stem}.{ext}"
        row["result"] = "hwp" if magic in ("hwp", "hwpx") else "other"
    _save(path, body)
    return row | {"path": str(path)}, len(body)


def collect_notice(
    client: httpx.Client,
    hm: str,
    pb: str,
    page_url: str,
    out_dir: Path = NOTICE_DIR,
    previous: dict[str, dict] | None = None,
    sleep=time.sleep,
) -> NoticeResult:
    """공고 하나: 상세 페이지 → 링크 → 첨부. `previous`는 지난 목록의 줄(링크 URL이 열쇠)이다."""
    try:
        html = _fetch_page(client, page_url, sleep)
    except FetchError as e:
        return NoticeResult([_row(hm, pb, None, result="error", error=str(e))], "error")

    links = find_doc_links(html)
    if not links:
        others = other_links(html)
        note = "다른 외부 링크: " + ", ".join(others) if others else "다른 외부 링크 없음"
        return NoticeResult([_row(hm, pb, None, result="no_link", note=note)], "no_link")

    rows, new, received = [], 0, 0
    for url in links:
        prev = (previous or {}).get(url)
        if _reusable(prev):
            rows.append(dict(prev))
            continue
        row, got = _collect_link(client, hm, pb, url, out_dir, sleep)
        rows.append(row)
        if got is not None:
            new += 1
            received += got
    worst = max((r["result"] for r in rows), key=_SEVERITY.__getitem__)
    return NoticeResult(rows, worst, new, received)


# ── 실행 ─────────────────────────────────────────────────────────────────


def _read_manifest(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        return []


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_notices(engine: Engine, limit: int | None) -> list[tuple[str, str, str | None]]:
    """실제 DB `notices`를 읽기만 한다."""
    stmt = "SELECT house_manage_no, pblanc_no, pblanc_url FROM notices ORDER BY 1, 2"
    params = {}
    if limit is not None:
        stmt += " LIMIT :n"
        params["n"] = limit
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(stmt), params)]


def main(argv=None, client=None, engine=None, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description="청약홈 공고문 첨부를 받아 data/raw/notices/에 둔다")
    ap.add_argument("--limit", type=int, default=None, help="앞에서부터 N개 공고만")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="실행 요약 JSON 경로")
    ap.add_argument("--dir", type=Path, default=NOTICE_DIR, help="공고문을 두는 폴더")
    args = ap.parse_args(argv)

    own_client, own_engine = client is None, engine is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    engine = engine or sa.create_engine(settings.database_url)
    try:
        notices = _load_notices(engine, args.limit)
    finally:
        if own_engine:
            engine.dispose()
    if not notices:
        print("DB `notices`에 공고가 없다. #71 수집을 먼저 돌릴 것", file=sys.stderr)
        if own_client:
            client.close()
        return 1

    manifest_path = args.dir / "manifest.jsonl"
    old_rows = _read_manifest(manifest_path)
    previous = {r["url"]: r for r in old_rows if r.get("url")}
    started = datetime.now().astimezone()
    t0 = time.monotonic()
    new_rows: list[dict] = []
    results: dict[str, int] = dict.fromkeys(RESULTS, 0)
    by_result: dict[str, list[str]] = {r: [] for r in RESULTS}
    new_downloads = received = 0
    page_failed: set[tuple[str, str]] = (
        set()
    )  # 링크를 알기 전에 실패한 공고. 지난 줄을 지우지 않는다
    try:
        for hm, pb, url in notices:
            try:
                if not url:
                    out = NoticeResult(
                        [
                            _row(
                                hm, pb, None, result="error", error="notices.pblanc_url이 비어 있다"
                            )
                        ],
                        "error",
                    )
                else:
                    out = collect_notice(client, hm, pb, url, args.dir, previous, sleep)
            except Exception as e:  # noqa: BLE001 — 공고 하나가 예상 밖으로 죽어도 나머지를 계속한다
                out = NoticeResult(
                    [
                        _row(
                            hm,
                            pb,
                            None,
                            result="error",
                            error=f"{type(e).__name__}: {str(e)[:200]}",
                        )
                    ],
                    "error",
                )
            if out.result == "error" and out.rows[0]["url"] is None:
                page_failed.add((hm, pb))
            new_rows += out.rows
            results[out.result] += 1
            by_result[out.result].append(f"{hm}/{pb}")
            new_downloads += out.new_downloads
            received += out.downloaded_bytes
    finally:
        # 중간에 끊겨도 지금까지 받은 줄은 남긴다. 안 남기면 다음 실행이 받은 파일을 다시 받는다
        done = {(r["house_manage_no"], r["pblanc_no"]) for r in new_rows} - page_failed
        # 페이지 실패가 되풀이되면 지난 실행의 실패 줄(url 없는 error)은 새 줄로 바꾼다
        kept = [
            r
            for r in old_rows
            if (r["house_manage_no"], r["pblanc_no"]) not in done
            and not (
                (r["house_manage_no"], r["pblanc_no"]) in page_failed
                and r["url"] is None
                and r["result"] == "error"
            )
        ]
        merged = sorted(
            kept + new_rows,
            key=lambda r: (r["house_manage_no"], r["pblanc_no"], r["url"] or ""),
        )
        _write_atomic(
            manifest_path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged)
        )
        if own_client:
            client.close()

    ended = datetime.now().astimezone()
    summary = {
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"),
        "elapsed_sec": round(time.monotonic() - t0, 1),
        "limit": args.limit,
        "notices": len(notices),
        "results": results,
        "errors": results["error"],
        "with_link": len(notices) - results["no_link"],
        "link_rows": len(new_rows),
        "new_downloads": new_downloads,
        "downloaded_bytes": received,
        "error_notices": by_result["error"],
        "no_link_notices": by_result["no_link"],
    }
    _write_atomic(args.out, json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        f"공고 {summary['notices']}건 · 결과 "
        + " · ".join(f"{k} {v}" for k, v in results.items())
        + f" · 새 다운로드 {new_downloads} · {received}바이트 · {summary['elapsed_sec']}초"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
