"""법제처 국가법령정보 OPEN API에서 「주택공급에 관한 규칙」 현행 조문을 받는다 (#69)."""

import json
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
    resp = client.get(url, params=params)
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
            }
    raise LawApiError(f"검색 결과에 현행 「{LAW_NAME}」이 없다: {_snippet(json.dumps(body), oc)}")


def _check_name(body: dict, oc: str) -> dict:
    name = body.get("법령", {}).get("기본정보", {}).get("법령명_한글")
    if name != LAW_NAME:
        raise LawApiError(f"법령명이 {LAW_NAME!r}이 아니다: {name!r}")
    return body


def fetch_law(oc: str, mst: str, dest: Path, client: httpx.Client | None = None) -> dict:
    """dest에 캐시가 있으면 다시 받지 않는다. 검증을 통과한 응답만 캐시한다."""
    oc = _require_oc(oc)
    dest = Path(dest)
    if dest.exists():
        try:
            return _check_name(json.loads(dest.read_text(encoding="utf-8")), oc)
        except ValueError as e:
            raise LawApiError(f"캐시가 깨졌다. 지우고 다시 실행할 것: {dest} ({e})") from None
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
