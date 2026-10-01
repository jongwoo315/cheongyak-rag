"""국토교통부 「주택청약 FAQ」 PDF를 Q&A 쌍으로 파싱한다 (#70)."""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
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
        if not resp.content.startswith(b"%PDF"):  # 쿠키 실패·공지 페이지는 200 HTML로 온다
            raise ValueError(f"PDF가 아닌 응답을 받았다: {resp.headers.get('content-type')}")
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
    """줄바꿈으로 접힌 제목을 잇는다. 줄 끝 공백은 그대로 둔다.

    단어 중간에서 접힌 줄(청년 / 주택드림)이 있어 공백을 끼우지 않는다. 단어 경계에서 접히고
    공백이 빠진 줄은 붙어 버린다(질문 15건 안팎) — 텍스트만으로는 둘을 가를 수 없다.
    """
    return re.sub(r"\s+", " ", "".join(parts)).strip()


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
            elif text.lstrip().startswith(("∙", "•")):  # `∙ 참고 …` 항목은 질문이 아니다
                flush()
            elif m := Q_START.match(text):
                flush()
                q_no, q_parts = int(m[1]), [m[2]]
            elif q_no is not None and ln.font != "KoPubDotumBold":  # 접힌 질문의 다음 줄
                q_parts.append(text)
            else:
                continue
            if roman and title:
                major, middle, minor = f"{roman}. {title}", "", ""
                roman = title = ""
    else:
        raise ValueError("대분류 표지 쪽을 못 찾았다")
    flush()
    return entries


# ── 본문 ─────────────────────────────────────────────────────────────────

AS_OF = "2024-05-29"
WHITE, QUESTION_BLUE, MIDDLE_GRAY = 0xFFFFFF, 0x0F70B7, 0x262626
ARTICLE = re.compile(r"제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?")


@dataclass
class FaqPair:
    q_no: int
    major: str
    middle: str
    minor: str
    question: str
    answer: str
    page_start: int  # 1-base 물리 쪽
    as_of: str
    cited_articles: list[str]


@dataclass
class BodyStats:
    """파싱하면서 같이 센 값. 대조 리포트가 쓴다."""

    skipped_pages: set[int] = field(
        default_factory=set
    )  # `가. 주요내용` 등 질문 없는 본문이 있는 쪽
    skipped_chars: int = 0
    table_q_nos: set[int] = field(default_factory=set)  # 9pt 미만 글자(표 칸)가 섞인 답변


def cite_articles(text: str) -> list[str]:
    """`제4조제1항` 꼴 인용을 등장 순서대로, 중복 없이 뽑는다. 줄바꿈으로 갈린 인용도 잇는다."""
    return list(dict.fromkeys(ARTICLE.findall(text.replace("\n", ""))))


def _is_digits(ln: Line, size: float, color: int) -> bool:
    return (
        ln.font == "KoPubDotumBold"
        and ln.size == size
        and ln.colors == {color}
        and ln.text.strip().isdigit()
    )


def _is_noise(ln: Line) -> bool:
    """쪽 머리말(대분류 제목 반복)과 쪽 번호."""
    header = ln.size == 8.5 and ln.y0 < 80
    page_no = ln.font == "KoPubDotumBold" and ln.size == 11.0 and ln.text.strip().isdigit()
    return header or page_no


def parse_body(doc: pymupdf.Document, stats: BodyStats | None = None) -> list[FaqPair]:
    """본문에서 Q&A 쌍을 읽는다. 섹션은 본문 제목에서 읽고 목차는 보지 않는다."""
    stats = stats if stats is not None else BodyStats()
    pairs: list[FaqPair] = []
    major = middle = minor = ""
    started = False
    cur: dict | None = None  # 지금 읽고 있는 쌍
    mid_num, mid_parts = "", []

    def close() -> None:
        nonlocal cur
        if cur:
            answer = "\n".join(cur["answer"])
            pairs.append(
                FaqPair(
                    q_no=cur["q_no"],
                    major=cur["major"],
                    middle=cur["middle"],
                    minor=cur["minor"],
                    question=join_wrapped(cur["question"]),
                    answer=answer,
                    page_start=cur["page"],
                    as_of=AS_OF,
                    cited_articles=cite_articles(answer),
                )
            )
        cur = None

    def commit_middle() -> None:
        nonlocal middle, minor, mid_num, mid_parts
        if mid_num and mid_parts:
            close()
            middle, minor = f"{mid_num}. {join_wrapped(mid_parts)}", ""
        mid_num, mid_parts = "", []

    for pno, page in enumerate(doc, start=1):
        lines = page_lines(page)
        if is_divider(lines):
            started = True
            close()
            roman = next(ln.text for ln in lines if ln.font == "KoPubBatangBold").strip()
            title = join_wrapped([ln.text for ln in lines if ln.size == 34.0])
            major, middle, minor = f"{roman.rstrip('.')}. {title}", "", ""
            continue
        if not started:
            continue
        # 질문 번호 칸은 질문 텍스트와 같은 줄이지만 y가 1~2pt 아래라 먼저 오게 당긴다
        lines.sort(key=lambda ln: (ln.y0 - (5 if _is_digits(ln, 10.0, WHITE) else 0), ln.x0))
        for ln in lines:
            if _is_noise(ln):
                continue
            if _is_digits(ln, 19.0, WHITE):
                mid_num = ln.text.strip()
            elif ln.colors == {MIDDLE_GRAY}:
                mid_parts.append(ln.text)
            else:
                commit_middle()
                if _is_digits(ln, 10.0, WHITE):
                    close()
                    cur = {
                        "q_no": int(ln.text),
                        "page": pno,
                        "major": major,
                        "middle": middle,
                        "minor": minor,
                        "question": [],
                        "answer": [],
                    }
                elif ln.font == "NanumSquareB" and ln.size == 13.0 and ln.colors == {WHITE}:
                    close()
                    minor = join_wrapped([ln.text])
                elif cur is not None and ln.colors == {QUESTION_BLUE} and not cur["answer"]:
                    cur["question"].append(ln.text)
                elif cur is not None:
                    cur["answer"].append(ln.text.rstrip())
                    if ln.size < 9.0:
                        stats.table_q_nos.add(cur["q_no"])
                else:  # 질문이 없는 설명 본문
                    stats.skipped_pages.add(pno)
                    stats.skipped_chars += len(ln.text.strip())
        commit_middle()
    close()
    return pairs


# ── CLI ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]
PDF_PATH = ROOT / "data" / "raw" / "faq-20240529.pdf"
JSONL_PATH = ROOT / "data" / "processed" / "faq-20240529.jsonl"


def write_jsonl(pairs: list[FaqPair], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")


def count_warnings(text: str) -> int:
    """MuPDF 경고 문자열의 건수. `... repeated N times...` 줄은 N건으로 센다."""
    total = 0
    for line in text.splitlines():
        m = re.match(r"\.\.\. repeated (\d+) times", line)
        total += int(m[1]) if m else 1 if line.strip() else 0
    return total


def main(pdf: Path = PDF_PATH, out: Path = JSONL_PATH) -> int:
    from .faq_report import build_report, format_report

    print(f"PDF: {'캐시 사용' if pdf.exists() else '다운로드'} {pdf}")
    pymupdf.TOOLS.mupdf_warnings()  # 이전 경고를 비운다
    with pymupdf.open(fetch_pdf(pdf)) as doc:
        toc = parse_toc(doc)
        stats = BodyStats()
        pairs = parse_body(doc, stats)
    warnings = count_warnings(pymupdf.TOOLS.mupdf_warnings())
    report = build_report(toc, pairs, stats, warnings)
    # 검증에 걸리면 이전 JSONL을 덮어쓰지 않는다. 다음 단계(#73)가 깨진 파일을 읽게 된다
    ok = report.q_no_ok and report.pair_count == len(toc) and not report.mismatches
    if ok:
        write_jsonl(pairs, out)
        print(f"JSONL: {len(pairs)}쌍 → {out}")
    else:
        print(f"JSONL: 검증 실패라 쓰지 않았다 ({out})", file=sys.stderr)
    print()
    print(format_report(report))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
