"""국토교통부 「주택청약 FAQ」 PDF를 Q&A 쌍으로 파싱한다 (#70)."""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import pymupdf

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


# ── PDF 줄 추출 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Line:
    text: str
    font: str  # 첫 span의 글꼴
    size: float  # 줄 안 최대 글자 크기
    colors: frozenset[int]
    x0: float
    y0: float
    y1: float


def page_lines(page: pymupdf.Page) -> list[Line]:
    """쪽의 텍스트 줄을 위에서 아래, 왼쪽에서 오른쪽 순으로 돌려준다. 공백뿐인 줄은 뺀다."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for ln in block.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            lines.append(
                Line(
                    text="".join(s["text"] for s in ln["spans"]),
                    font=spans[0]["font"],
                    size=round(max(s["size"] for s in spans), 1),
                    colors=frozenset(s["color"] for s in spans),
                    x0=ln["bbox"][0],
                    y0=ln["bbox"][1],
                    y1=ln["bbox"][3],
                )
            )
    return sorted(lines, key=lambda x: (round(x.y0), x.x0))


def is_divider(lines: list[Line]) -> bool:
    """대분류 표지 쪽인가 — 큰 로마 숫자(KoPubBatangBold 30pt)가 있다."""
    return any(ln.font == "KoPubBatangBold" and ln.size >= 25 for ln in lines)


def join_wrapped(parts: list[str]) -> str:
    """줄바꿈으로 접힌 제목을 잇는다. 앞 줄 끝에 공백이 없으면 한 칸 넣는다."""
    out = ""
    for part in parts:
        out += part if not out or out.endswith(" ") else " " + part
    return re.sub(r"\s+", " ", out).strip()


# ── 목차 ─────────────────────────────────────────────────────────────────

LEADER = re.compile(r"\s*·{2,}\s*\d*\s*$")
Q_START = re.compile(r"^Q(\d+)\.\s*(.*)$")


@dataclass(frozen=True)
class TocEntry:
    q_no: int
    major: str  # `Ⅰ. 청약자격(공통)`
    middle: str  # `1. 청약신청지역` — 중분류가 없는 대분류는 ""
    minor: str  # `나. 청약신청지역 및 우선공급` — 소분류가 없으면 ""
    question: str


def parse_toc(doc: pymupdf.Document) -> list[TocEntry]:
    entries: list[TocEntry] = []
    major = middle = minor = ""
    roman = title = ""
    q_no: int | None = None
    q_parts: list[str] = []

    def flush() -> None:
        nonlocal q_no, q_parts
        if q_no is not None:
            entries.append(TocEntry(q_no, major, middle, minor, join_wrapped(q_parts)))
        q_no, q_parts = None, []

    for page in doc:
        lines = page_lines(page)
        if is_divider(lines):  # 첫 대분류 표지 쪽 앞까지가 목차다
            break
        for ln in lines:
            text = LEADER.sub("", ln.text)
            if ln.font == "KoPubBatangBold":  # 대분류 로마 숫자 (`Ⅰ.` 또는 점 없는 `Ⅳ`)
                flush()
                roman = text.strip().rstrip(".")
            elif ln.font == "KoPubDotumBold" and ln.size == 13.0:  # 대분류 제목
                flush()
                title = text.strip()
            elif ln.font == "KoPubDotumBold" and ln.size == 12.0:  # 중분류
                flush()
                middle, minor = text.strip(), ""
            elif ln.font == "KoPubDotumMedium" and ln.size == 10.5:  # 소분류
                flush()
                minor = text.strip()
            elif m := Q_START.match(text):
                flush()
                q_no, q_parts = int(m[1]), [m[2]]
            elif q_no is not None and ln.font != "KoPubDotumBold":  # 접힌 질문의 다음 줄
                q_parts.append(text)
            elif text.lstrip().startswith(("∙", "•")):  # `∙ 참고 …` 항목은 질문이 아니다
                flush()
            else:
                continue
            if roman and title:
                major, middle, minor = f"{roman}. {title}", "", ""
                roman = title = ""
    else:
        raise ValueError("대분류 표지 쪽을 못 찾았다")
    flush()
    return entries
