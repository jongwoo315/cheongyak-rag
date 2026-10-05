"""법제처 국가법령정보 OPEN API에서 「주택공급에 관한 규칙」 현행 조문을 받는다 (#69)."""

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
LAW_NAME = "주택공급에 관한 규칙"
SNIPPET = 200


class LawApiError(RuntimeError):
    """API가 정상 응답을 주지 않았다. 재시도로 풀리지 않는다 — 키·IP 등록·서버 상태를 본다."""


def _require_oc(oc: str) -> str:
    # 비면 OC=test 같은 공용 값으로 대신하지 않는다. 대신하면 키 검증이 조용히 통과한다
    if not oc.strip():
        raise LawApiError("LAW_OC가 비어 있다. .env에 법제처 OPEN API 인증값을 넣을 것")
    return oc.strip()


def _snippet(text: str, oc: str) -> str:
    return text.replace(oc, "***")[:SNIPPET]


def _get_json(client: httpx.Client, url: str, params: dict, oc: str) -> dict:
    """호출 → 상태 코드 + JSON 파싱 + 오류 본문 검사. 실패면 응답 앞 200자를 붙여 예외."""
    try:
        resp = client.get(url, params=params)
    except httpx.HTTPError as e:  # 연결 실패·시간 초과. httpx 로그에는 URL(OC 포함)이 찍힐 수 있다
        raise LawApiError(f"{type(e).__name__}: {_snippet(str(e), oc)}") from None
    if resp.status_code != 200:
        raise LawApiError(f"HTTP {resp.status_code}: {_snippet(resp.text, oc)}")
    try:
        body = resp.json()
    except ValueError:
        raise LawApiError(f"JSON이 아닌 응답: {_snippet(resp.text, oc)}") from None
    # 실측: 키가 틀려도 HTTP 200 + {"result": 오류 문구, "msg": ...}가 온다
    if isinstance(body, dict) and "result" in body:
        raise LawApiError(f"API 오류 응답: {_snippet(json.dumps(body, ensure_ascii=False), oc)}")
    return body


def search_current(oc: str, client: httpx.Client | None = None) -> dict[str, str]:
    """검색 응답에서 현행 버전을 고른다. MST를 코드에 박지 않는다 — 개정되면 바뀐다."""
    oc = _require_oc(oc)
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        params = {"OC": oc, "target": "law", "query": LAW_NAME.replace(" ", ""), "type": "JSON"}
        body = _get_json(client, SEARCH_URL, params, oc)
    finally:
        if own:
            client.close()
    found = body.get("LawSearch", {}).get("law", [])
    for entry in [found] if isinstance(found, dict) else found:  # 결과가 하나면 dict로 온다
        if entry.get("현행연혁코드") == "현행" and entry.get("법령명한글") == LAW_NAME:
            d = entry["시행일자"]
            return {
                "mst": entry["법령일련번호"],
                "law_id": entry["법령ID"],
                "effective_date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                "promulgation_no": entry.get("공포번호", ""),
            }
    raise LawApiError(f"검색 결과에 현행 「{LAW_NAME}」이 없다: {_snippet(json.dumps(body), oc)}")


def _check_name(body: dict, oc: str) -> dict:
    name = body.get("법령", {}).get("기본정보", {}).get("법령명_한글")
    if name != LAW_NAME:
        raise LawApiError(f"법령명이 {LAW_NAME!r}이 아니다: {name!r}")
    return body


def _law_key(body: dict) -> str | None:
    return body.get("법령", {}).get("법령키")


def fetch_law(
    oc: str,
    mst: str,
    dest: Path,
    client: httpx.Client | None = None,
    version_key: str | None = None,
) -> dict:
    """dest에 캐시가 있으면 다시 받지 않는다. 검증을 통과한 응답만 캐시한다.

    version_key(`법령키` = 법령ID + 시행일 + 공포번호)가 주어지고 캐시의 값과 다르면 같은 시행일에
    다시 공포된 판본이라 캐시를 버리고 다시 받는다.
    """
    oc = _require_oc(oc)
    dest = Path(dest)
    if dest.exists():
        try:
            cached = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError as e:
            raise LawApiError(f"캐시가 깨졌다. 지우고 다시 실행할 것: {dest} ({e})") from None
        if not isinstance(cached, dict):
            raise LawApiError(f"캐시가 법령 응답이 아니다. 지우고 다시 실행할 것: {dest}")
        if version_key is None or _law_key(cached) == version_key:
            return _check_name(cached, oc)
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        params = {"OC": oc, "target": "law", "MST": mst, "type": "JSON"}
        body = _check_name(_get_json(client, SERVICE_URL, params, oc), oc)
    finally:
        if own:
            client.close()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return body


# ── 조문 파싱 ────────────────────────────────────────────────────────────


@dataclass
class Subitem:
    no: str  # 목 `가`
    text: str


@dataclass
class Item:
    no: str  # 호 `1`, 가지면 `2의2`
    text: str
    subitems: list[Subitem] = field(default_factory=list)


@dataclass
class Paragraph:
    no: str  # 항 `①`. 번호·본문 없이 호만 든 항(항이 dict로 오는 조문)은 ""
    text: str
    amendments: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)


@dataclass
class Article:
    law_id: str
    mst: str
    effective_date: str
    article_no: int
    branch_no: int  # 가지번호. 없으면 0
    label: str  # `제4조`, 가지면 `제4조의2`
    title: str | None
    chapter: str | None
    section: str | None
    article_effective_date: str
    deleted: bool
    text: str  # 조문내용 그대로. 항이 있는 조문은 `제3조(적용대상)` 머리만 든다
    paragraphs: list[Paragraph]
    amendments: list[str]  # 조문 전체(조문내용·항·호·목)의 `<개정·신설 …>` 날짜, ISO 오름차순


_D = r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?"  # 조문은 `2016.5.19`, 별표·부칙은 `2024. 12. 18.`
AMENDMENT_TAG = re.compile(rf"(?:<|&lt;)(?:(?:개정|신설)\s+)?({_D}(?:\s*,\s*{_D})*)(?:>|&gt;)")
DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")
CHAPTER = re.compile(r"^제\d+장(?:\s|$)")
SECTION = re.compile(r"^제\d+절(?:의\d+)?(?:\s|$)")
DELETED = re.compile(r"^제\d+조(?:의\d+)?\s*삭제")


def extract_amendments(text: str) -> list[str]:
    """`<개정 2016.5.19, …>` · `<신설 …>` · `삭제 <2016.12.30>`의 날짜를 ISO 오름차순으로 뽑는다."""
    dates = {
        f"{y}-{int(m):02d}-{int(d):02d}"
        for tag in AMENDMENT_TAG.finditer(text)
        for y, m, d in DATE.findall(tag[1])
    }
    return sorted(dates)


def _as_list(node) -> list:
    """항·호·목은 하나면 dict로, 없으면 키 자체가 빠져서 온다. 셋을 하나로 맞춘다."""
    if node is None:
        return []
    return [node] if isinstance(node, dict) else node


def _lines(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for n in node:
            yield from _lines(n)


def _text(node) -> str:
    """내용 필드는 문자열이거나, 줄 목록, 줄 목록의 목록(`목내용`)으로 온다."""
    return "\n".join(ln.strip() for ln in _lines(node) if ln.strip())


def _no(num: str, branch: str | None) -> str:
    base = num.strip().rstrip(".")
    return f"{base}의{branch}" if branch else base


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _parse_subitem(node: dict) -> Subitem:
    return Subitem(no=_no(node["목번호"], None), text=_text(node["목내용"]))


def _parse_item(node: dict) -> Item:
    return Item(
        no=_no(node["호번호"], node.get("호가지번호")),
        text=_text(node["호내용"]),
        subitems=[_parse_subitem(m) for m in _as_list(node.get("목"))],
    )


def _parse_paragraph(node: dict) -> Paragraph:
    text = _text(node.get("항내용", ""))
    return Paragraph(
        no=node.get("항번호", "").strip(),
        text=text,
        amendments=extract_amendments(text),
        items=[_parse_item(h) for h in _as_list(node.get("호"))],
    )


def _all_text(art: Article) -> str:
    parts = [art.text]
    for p in art.paragraphs:
        parts.append(p.text)
        for i in p.items:
            parts.append(i.text)
            parts.extend(s.text for s in i.subitems)
    return "\n".join(parts)


def parse_articles(law_json: dict, mst: str = "") -> list[Article]:
    """`법령.조문.조문단위`를 조문 하나당 `Article` 하나로 바꾼다. 계층(항·호·목)은 그대로 둔다."""
    law = law_json["법령"]
    info = law["기본정보"]
    law_id, effective = info["법령ID"], _iso(info["시행일자"])
    chapter = section = None
    articles = []
    for unit in _as_list(law["조문"]["조문단위"]):
        text = _text(unit["조문내용"])
        if unit["조문여부"] == "전문":  # 장·절 제목. 뒤따르는 조문들의 소속이다
            if CHAPTER.match(text):
                chapter, section = text, None
            elif SECTION.match(text):
                section = text
            else:
                raise ValueError(f"알 수 없는 전문(장·절이 아니다): {text!r}")
            continue
        no, branch = int(unit["조문번호"]), int(unit.get("조문가지번호") or 0)
        art = Article(
            law_id=law_id,
            mst=mst,
            effective_date=effective,
            article_no=no,
            branch_no=branch,
            label=f"제{no}조" + (f"의{branch}" if branch else ""),
            title=unit.get("조문제목"),
            chapter=chapter,
            section=section,
            article_effective_date=_iso(unit["조문시행일자"]),
            deleted=bool(DELETED.match(text)),
            text=text,
            paragraphs=[_parse_paragraph(h) for h in _as_list(unit.get("항"))],
            amendments=[],
        )
        art.amendments = extract_amendments(_all_text(art))
        articles.append(art)
    return articles


# ── CLI ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
FAQ_JSONL = OUT_DIR / "faq-20240529.jsonl"


def write_jsonl(rows: list[dict], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _stamp(path: Path) -> tuple[int, int] | None:
    """파일이 교체됐는지 보는 값. 없으면 None."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_ino, st.st_mtime_ns


def main(
    oc: str | None = None,
    raw_dir: Path = RAW_DIR,
    out_dir: Path = OUT_DIR,
    faq_path: Path = FAQ_JSONL,
    client: httpx.Client | None = None,
) -> int:
    from . import law_report

    if oc is None:
        from ..config import settings

        oc = settings.law_oc
    try:
        current = search_current(oc, client)  # 매번 한다. 현행 MST가 바뀌었는지 보는 호출이다
        stem = f"law-{current['law_id']}-{current['effective_date'].replace('-', '')}"
        raw = Path(raw_dir) / f"{stem}.json"
        before = _stamp(raw)
        key = None
        if current["promulgation_no"]:
            key = (
                current["law_id"]
                + current["effective_date"].replace("-", "")
                + current["promulgation_no"]
            )
        law_json = fetch_law(oc, current["mst"], raw, client, version_key=key)
        cached = (
            before is not None and _stamp(raw) == before
        )  # 판본이 달라 다시 받았으면 캐시가 아니다
    except LawApiError as e:
        print(f"API 오류: {e}", file=sys.stderr)
        return 1
    print(f"검색: 현행 MST {current['mst']} (시행 {current['effective_date']})")
    print(f"본문: {'캐시 사용' if cached else '다운로드'} {raw}")

    rows = [asdict(a) for a in parse_articles(law_json, current["mst"])]
    result = law_report.check(law_json, rows)
    out = Path(out_dir) / f"{stem}.jsonl"
    # 검증에 걸리면 이전 JSONL을 덮어쓰지 않는다. 다음 단계(#73)가 깨진 파일을 읽게 된다
    if result.ok:
        write_jsonl(rows, out)
        print(f"JSONL: {len(rows)}조문 → {out}")
    else:
        print(f"JSONL: 검증 실패라 쓰지 않았다 ({out})", file=sys.stderr)
    # FAQ 대조는 보조 항목이다. FAQ 파일이 깨져도 위 출력과 리포트는 막지 않는다
    cross = None
    if Path(faq_path).exists():
        try:
            lines = Path(faq_path).read_text(encoding="utf-8").splitlines()
            faq_rows = [json.loads(ln) for ln in lines if ln.strip()]
            cross = law_report.faq_cross(rows, faq_rows)
        except (ValueError, KeyError, TypeError) as e:
            print(f"FAQ JSONL을 읽지 못해 FAQ 인용 대조를 건너뛴다: {e!r}", file=sys.stderr)
    print()
    print(law_report.format_report(current, result, law_report.appendix_summary(law_json), cross))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
