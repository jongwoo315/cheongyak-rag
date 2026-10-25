"""법제처 eflaw 목록 API를 흉내 내는 가짜 서버 (#78).

실측(2026-10-25): `lawSearch.do?target=eflaw`는 이름이 비슷한 다른 법령까지 섞어 주고(totalCnt 177),
행 하나의 `법령상세링크`에 OC가 그대로 들어 있다. 결과가 하나면 `law`가 dict로 온다.
"""

import json
from datetime import date

import httpx

from cheongyak_rag.ingest.law import LAW_NAME

FAKE_OC = "FAKEOC9"


def make_row(mst: str, eff: date, prom: date | None = None, name: str = LAW_NAME, **over) -> dict:
    prom = prom or eff
    row = {
        "현행연혁코드": "연혁",
        "법령일련번호": mst,
        "자법타법여부": "",
        "법령상세링크": f"/DRF/lawService.do?OC={FAKE_OC}&target=eflaw&MST={mst}"
        f"&type=HTML&mobileYn=&efYd={eff:%Y%m%d}",
        "법령명한글": name,
        "법령구분명": "국토교통부령",
        "소관부처명": "국토교통부",
        "공포번호": f"no-{mst}",
        "제개정구분명": "일부개정",
        "소관부처코드": "1613000",
        "id": "1",
        "법령ID": "008243",
        "공동부령정보": "",
        "시행일자": f"{eff:%Y%m%d}",
        "공포일자": f"{prom:%Y%m%d}",
        "법령약칭명": "",
    }
    row.update(over)
    return row


def make_rows(n: int, start_mst: int = 1000, name: str = LAW_NAME) -> list[dict]:
    """시행일이 하루씩 다른 n개 행. MST도 서로 다르다."""
    return [
        make_row(str(start_mst + i), date.fromordinal(date(2005, 3, 9).toordinal() + i), name=name)
        for i in range(n)
    ]


class FakeEflaw:
    """행 목록을 `display`개씩 잘라 page 순서대로 준다. 호출 기록이 `requests`에 남는다."""

    def __init__(self, rows: list[dict], total_count: int | None = None):
        self.rows = rows
        self.total_count = len(rows) if total_count is None else total_count
        self.requests: list[httpx.Request] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        p = request.url.params
        if p.get("OC") != FAKE_OC or p.get("target") != "eflaw":
            return httpx.Response(200, json={"result": "사용자 정보 검증에 실패하였습니다."})
        display, page = int(p["display"]), int(p["page"])
        chunk = self.rows[(page - 1) * display : page * display]
        law: list | dict | None = chunk
        if len(chunk) == 1:
            law = chunk[0]  # 하나면 dict로 온다
        body = {
            "LawSearch": {
                "target": "eflaw",
                "totalCnt": str(self.total_count),
                "page": str(page),
                "numOfRows": str(len(chunk)),
                "resultCode": "00",
                "resultMsg": "success",
                **({"law": law} if chunk else {}),  # 빈 페이지는 law 키가 없다
            }
        }
        return httpx.Response(200, content=json.dumps(body, ensure_ascii=False))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handler))
