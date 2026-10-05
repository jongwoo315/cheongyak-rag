import json

import httpx
import pytest

from cheongyak_rag.ingest import law

NAME = "주택공급에 관한 규칙"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _search_body(laws) -> dict:
    return {"LawSearch": {"law": laws, "resultCode": "00", "totalCnt": "1"}}


CURRENT = {
    "현행연혁코드": "현행",
    "법령일련번호": "286965",
    "법령명한글": NAME,
    "법령ID": "008243",
    "시행일자": "20260615",
}


def test_search_current_picks_current_version_from_list():
    old = {**CURRENT, "현행연혁코드": "연혁", "법령일련번호": "111", "시행일자": "20240101"}
    other = {**CURRENT, "법령명한글": "주택공급에 관한 규칙 시행세칙", "법령일련번호": "222"}
    client = _client(lambda r: httpx.Response(200, json=_search_body([old, other, CURRENT])))

    assert law.search_current("key", client) == {
        "mst": "286965",
        "law_id": "008243",
        "effective_date": "2026-06-15",
    }


def test_search_current_accepts_single_dict_result():
    # DRF는 결과가 하나면 list가 아니라 dict로 보낸다
    client = _client(lambda r: httpx.Response(200, json=_search_body(CURRENT)))

    assert law.search_current("key", client)["mst"] == "286965"


def test_search_sends_oc_and_query():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json=_search_body(CURRENT))

    law.search_current("mykey", _client(handler))

    assert seen[0]["OC"] == "mykey"
    assert seen[0]["target"] == "law"
    assert seen[0]["type"] == "JSON"


def test_search_without_current_version_raises():
    old = {**CURRENT, "현행연혁코드": "연혁"}
    client = _client(lambda r: httpx.Response(200, json=_search_body([old])))

    with pytest.raises(law.LawApiError, match="현행"):
        law.search_current("key", client)


def test_bad_key_is_http_200_with_error_body():
    # 실측: 키가 틀려도 HTTP 200 + {"result": 오류 문구}가 온다
    body = {"result": "사용자 정보 검증에 실패하였습니다.", "msg": "IP를 등록해 주세요."}
    client = _client(lambda r: httpx.Response(200, json=body))

    with pytest.raises(law.LawApiError, match="사용자 정보 검증"):
        law.search_current("badkey", client)


def test_http_error_status_raises_with_body_prefix():
    client = _client(lambda r: httpx.Response(500, text="x" * 500))

    with pytest.raises(law.LawApiError) as exc:
        law.search_current("key", client)
    assert "500" in str(exc.value)
    assert "x" * 200 in str(exc.value)
    assert "x" * 201 not in str(exc.value)


def test_non_json_response_raises_with_body_prefix():
    client = _client(lambda r: httpx.Response(200, text="<html>점검 중</html>"))

    with pytest.raises(law.LawApiError, match="점검 중"):
        law.search_current("key", client)


def test_error_message_does_not_leak_oc():
    client = _client(lambda r: httpx.Response(200, text="oops secretkey oops"))

    with pytest.raises(law.LawApiError) as exc:
        law.search_current("secretkey", client)
    assert "secretkey" not in str(exc.value)


@pytest.mark.parametrize("oc", ["", "  "])
def test_empty_oc_raises_without_calling_api(oc):
    def boom(request):
        raise AssertionError("OC가 비었는데 호출했다")

    with pytest.raises(law.LawApiError, match="LAW_OC"):
        law.search_current(oc, _client(boom))
    with pytest.raises(law.LawApiError, match="LAW_OC"):
        law.fetch_law(oc, "286965", "x.json", _client(boom))


def _law_body(name: str = NAME) -> dict:
    return {"법령": {"기본정보": {"법령명_한글": name}, "조문": {"조문단위": []}}}


def test_fetch_law_downloads_validates_and_caches(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json=_law_body())

    dest = tmp_path / "raw" / "law.json"
    result = law.fetch_law("key", "286965", dest, _client(handler))

    assert result["법령"]["기본정보"]["법령명_한글"] == NAME
    assert json.loads(dest.read_text(encoding="utf-8")) == result
    assert seen[0]["MST"] == "286965"
    assert seen[0]["OC"] == "key"


def test_fetch_law_uses_cache_without_network(tmp_path):
    dest = tmp_path / "law.json"
    dest.write_text(json.dumps(_law_body(), ensure_ascii=False), encoding="utf-8")

    def boom(request):
        raise AssertionError("캐시가 있는데 다시 받았다")

    assert law.fetch_law("key", "286965", dest, _client(boom)) == _law_body()


def test_fetch_law_rejects_wrong_law_name_and_caches_nothing(tmp_path):
    client = _client(lambda r: httpx.Response(200, json=_law_body("다른 법")))
    dest = tmp_path / "law.json"

    with pytest.raises(law.LawApiError, match="법령명"):
        law.fetch_law("key", "286965", dest, client)
    assert not dest.exists()


def test_fetch_law_error_body_is_not_cached(tmp_path):
    body = {"result": "사용자 정보 검증에 실패하였습니다."}
    client = _client(lambda r: httpx.Response(200, json=body))
    dest = tmp_path / "law.json"

    with pytest.raises(law.LawApiError, match="사용자 정보 검증"):
        law.fetch_law("key", "286965", dest, client)
    assert not dest.exists()


def test_corrupt_cache_is_rejected(tmp_path):
    dest = tmp_path / "law.json"
    dest.write_text("<html>", encoding="utf-8")

    with pytest.raises(law.LawApiError, match="캐시"):
        law.fetch_law("key", "286965", dest, _client(lambda r: httpx.Response(200)))
