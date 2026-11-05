import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cheongyak_rag import api
from cheongyak_rag.main import app
from tests.test_retrieval_axes import _notice


@pytest.fixture
def client(pg_engine):
    app.dependency_overrides[api.get_engine] = lambda: pg_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def _set(engine, hmn, **cols):
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE notices SET {sets} WHERE house_manage_no = :h"), {"h": hmn, **cols}
        )


def test_list_is_newest_notice_date_first_with_summary_fields(client, pg_engine):
    a = _notice(pg_engine, 1, de="2026-09-01")
    b = _notice(pg_engine, 2, de="2026-10-01", area="서울")
    _set(pg_engine, b, rcept_bgnde="2026-10-10", rcept_endde="2026-10-12")
    body = client.get("/api/notices").json()
    assert [n["house_manage_no"] for n in body] == [b, a]
    assert body[0] == {
        "house_manage_no": b,
        "pblanc_no": b,
        "house_nm": "단지 2",
        "subscrpt_area_nm": "서울",
        "rcrit_pblanc_de": "2026-10-01",
        "rcept_bgnde": "2026-10-10",
        "rcept_endde": "2026-10-12",
    }
    assert body[1]["rcept_bgnde"] is None  # 값이 없으면 null


def test_detail_has_notice_fields_and_model_rows(client, pg_engine):
    hmn = _notice(pg_engine, 1, models=[(4, {}), (0, {})])
    _set(
        pg_engine,
        hmn,
        hssply_adres="경기도 성남시",
        tot_suply_hshldco=120,
        przwner_presnatn_de="2026-11-01",
        pblanc_url="https://www.applyhome.co.kr/x",
    )
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE notice_models SET house_ty = '084.9500A', suply_ar = 84.95,"
                " suply_hshldco = 50, lttot_top_amount = 90000 WHERE model_no = '01'"
            )
        )
    r = client.get(f"/api/notices/{hmn}")
    assert r.status_code == 200
    body = r.json()
    assert body["house_nm"] == "단지 1" and body["hssply_adres"] == "경기도 성남시"
    assert body["tot_suply_hshldco"] == 120 and body["przwner_presnatn_de"] == "2026-11-01"
    assert body["pblanc_url"] == "https://www.applyhome.co.kr/x"
    assert len(body["models"]) == 2
    assert body["models"][0] == {
        "model_no": "01",
        "house_ty": "084.9500A",
        "suply_ar": 84.95,
        "suply_hshldco": 50,
        "spsply_hshldco": 4,
        "lttot_top_amount": 90000,
    }
    assert body["models"][1]["model_no"] == "02" and body["models"][1]["house_ty"] is None


def test_detail_of_a_notice_without_models_has_an_empty_list(client, pg_engine):
    hmn = _notice(pg_engine, 1)
    assert client.get(f"/api/notices/{hmn}").json()["models"] == []


def test_unknown_house_manage_no_is_404(client, pg_engine):
    assert client.get("/api/notices/없는번호").status_code == 404


def test_health_route_is_still_there():
    assert "/health" in app.openapi()["paths"]
