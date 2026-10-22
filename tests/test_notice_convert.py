from datetime import date
from decimal import Decimal

import pytest

from cheongyak_rag.ingest import notice
from tests.notice_fakes import make_model, make_notice


def test_notice_row_maps_columns_and_types():
    raw = make_notice(1)

    conv = notice.to_notice_row(raw)

    row = conv.row
    assert row["house_manage_no"] == "2026000001"
    assert row["subscrpt_area_nm"] == "경기"  # SUBSCRPT_AREA_CODE_NM
    assert row["tot_suply_hshldco"] == 101
    assert row["rcrit_pblanc_de"] == date(2026, 10, 1)
    assert row["mvn_prearnge_ym"] == "202912"  # 연월은 문자열로 둔다
    assert row["speclt_rdn_earth_at"] is False
    assert row["raw"] is raw
    assert conv.failed == [] and conv.empty == 0


def test_empty_values_become_null_and_are_counted_apart_from_failures():
    raw = make_notice(1, RCEPT_BGNDE="", PRZWNER_PRESNATN_DE=None, PARCPRC_ULS_AT="")

    conv = notice.to_notice_row(raw)

    assert conv.row["rcept_bgnde"] is None
    assert conv.row["przwner_presnatn_de"] is None
    assert conv.row["parcprc_uls_at"] is None
    assert conv.empty == 3
    assert conv.failed == []


def test_unparseable_values_become_null_and_are_listed():
    raw = make_notice(
        1,
        RCEPT_BGNDE="2026/11/02",
        RCEPT_ENDDE="2026-13-45",
        PARCPRC_ULS_AT="X",
        TOT_SUPLY_HSHLDCO="많음",
    )

    conv = notice.to_notice_row(raw)

    assert conv.row["rcept_bgnde"] is None and conv.row["rcept_endde"] is None
    assert conv.row["parcprc_uls_at"] is None and conv.row["tot_suply_hshldco"] is None
    assert sorted(conv.failed) == sorted(
        [
            ("RCEPT_BGNDE", "2026/11/02"),
            ("RCEPT_ENDDE", "2026-13-45"),
            ("PARCPRC_ULS_AT", "X"),
            ("TOT_SUPLY_HSHLDCO", "많음"),
        ]
    )


@pytest.mark.parametrize("value, expected", [("Y", True), ("N", False)])
def test_yes_no_columns(value, expected):
    assert (
        notice.to_notice_row(make_notice(1, MDAT_TRGET_AREA_SECD=value)).row["mdat_trget_area_secd"]
        is expected
    )


def test_numeric_strings_convert():
    conv = notice.to_notice_row(make_notice(1, TOT_SUPLY_HSHLDCO="1,542"))
    assert conv.row["tot_suply_hshldco"] is None  # 쉼표 낀 값은 규칙 밖이다. 조용히 고치지 않는다
    assert conv.failed == [("TOT_SUPLY_HSHLDCO", "1,542")]

    assert (
        notice.to_notice_row(make_notice(1, TOT_SUPLY_HSHLDCO="1542")).row["tot_suply_hshldco"]
        == 1542
    )


def test_model_row_maps_amount_and_area():
    conv = notice.to_model_row(make_model(make_notice(1), "01"))

    row = conv.row
    assert row["model_no"] == "01"
    assert row["house_ty"] == "084.3522A"
    assert row["suply_ar"] == Decimal("109.7246")
    assert row["lttot_top_amount"] == 53600
    assert (row["suply_hshldco"], row["spsply_hshldco"]) == (132, 159)
    assert conv.failed == []


def test_model_row_bad_amount_is_listed():
    conv = notice.to_model_row(
        make_model(make_notice(1), "01", LTTOT_TOP_AMOUNT="미정", SUPLY_AR="NaN")
    )

    assert conv.row["lttot_top_amount"] is None and conv.row["suply_ar"] is None
    assert sorted(conv.failed) == [("LTTOT_TOP_AMOUNT", "미정"), ("SUPLY_AR", "NaN")]


def test_missing_key_field_fails_loudly():
    raw = make_notice(1)
    del raw["HOUSE_NM"]
    with pytest.raises(ValueError, match="HOUSE_NM"):
        notice.to_notice_row(raw)
    with pytest.raises(ValueError, match="MODEL_NO"):
        notice.to_model_row({"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "1"})
