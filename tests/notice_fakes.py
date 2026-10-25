"""청약홈 분양정보 API를 흉내 내는 가짜 서버 (#71)."""

import httpx

DETAIL = "getAPTLttotPblancDetail"
MODELS = "getAPTLttotPblancMdl"
KEY_ENCODED = "ab%2Bcd%3D"  # data.go.kr Encoding 키 꼴
KEY_DECODED = "ab+cd="


def make_notice(n: int, de: str = "2026-10-01", **over) -> dict:
    row = {
        "HOUSE_MANAGE_NO": f"2026{n:06d}",
        "PBLANC_NO": f"2026{n:06d}",
        "HOUSE_NM": f"단지 {n}",
        "HOUSE_SECD": "01",
        "HOUSE_SECD_NM": "APT",
        "HOUSE_DTL_SECD": "01",
        "RENT_SECD": "0",
        "SUBSCRPT_AREA_CODE": "410",
        "SUBSCRPT_AREA_CODE_NM": "경기",
        "HSSPLY_ADRES": "경기도 어딘가",
        "TOT_SUPLY_HSHLDCO": 100 + n,
        "RCRIT_PBLANC_DE": de,
        "RCEPT_BGNDE": "2026-11-02",
        "RCEPT_ENDDE": "2026-11-04",
        "PRZWNER_PRESNATN_DE": "2026-11-10",
        "MVN_PREARNGE_YM": "202912",
        "SPECLT_RDN_EARTH_AT": "N",
        "MDAT_TRGET_AREA_SECD": "N",
        "PARCPRC_ULS_AT": "N",
        "PUBLIC_HOUSE_EARTH_AT": "N",
        "PBLANC_URL": f"https://www.applyhome.co.kr/x?no={n}",
        "BSNS_MBY_NM": "시행사",
    }
    row.update(over)
    return row


def make_model(notice: dict, no: str, **over) -> dict:
    row = {
        "HOUSE_MANAGE_NO": notice["HOUSE_MANAGE_NO"],
        "PBLANC_NO": notice["PBLANC_NO"],
        "MODEL_NO": no,
        "HOUSE_TY": "084.3522A",
        "SUPLY_AR": "109.7246",
        "SUPLY_HSHLDCO": 132,
        "SPSPLY_HSHLDCO": 159,
        "LTTOT_TOP_AMOUNT": "53600",
        "ETC_HSHLDCO": 0,
    }
    row.update(over)
    return row


class FakeApi:
    """상세·주택형 두 operation을 받는다. 날짜·EQ 조건과 페이지 넘김을 실제처럼 처리한다."""

    def __init__(self, notices, models=None, total_count=999_999):
        self.notices = notices
        self.models = models or []
        self.total_count = total_count
        self.requests: list[tuple[str, dict]] = []
        self.fail_with: list[httpx.Response | Exception] = []  # 앞에서부터 하나씩 소모

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        op = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        self.requests.append((op, params))
        if self.fail_with:
            out = self.fail_with.pop(0)
            if isinstance(out, Exception):
                raise out
            return out
        if params.get("serviceKey") != KEY_DECODED:
            return httpx.Response(401, json={"code": -4, "msg": "등록되지 않은 인증키 입니다."})
        rows = self.notices if op == DETAIL else self.models
        for k, v in params.items():
            if k.startswith("cond[") and k.endswith("::GTE]"):
                col = k[5 : -len("::GTE]")]
                rows = [r for r in rows if r[col] >= v]
            elif k.startswith("cond[") and k.endswith("::EQ]"):
                col = k[5 : -len("::EQ]")]
                rows = [r for r in rows if r[col] == v]
        per, page = int(params["perPage"]), int(params["page"])
        chunk = rows[(page - 1) * per : page * per]
        return httpx.Response(
            200,
            json={
                "currentCount": len(chunk),
                "matchCount": len(rows),
                "page": page,
                "perPage": per,
                "totalCount": self.total_count,
                "data": chunk,
            },
        )
