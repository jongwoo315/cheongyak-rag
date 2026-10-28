import json

import pytest
from sqlalchemy import text

from cheongyak_rag.retrieval import axes

IDS = [a.id for a in axes.AXES]


def _version(engine, mst="286965", effective="2026-06-15"):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO law_versions (law_id, mst, effective_date, raw)"
                " VALUES ('008243', :m, :e, '{}')"
            ),
            {"m": mst, "e": effective},
        )


def _notice(engine, n=1, area="경기", de="2026-10-01", models=(), **flags):
    """공고 하나 + 주택형. models는 주택형마다 (spsply_hshldco, 유형별 세대수 dict)."""
    hmn = f"2026{n:06d}"
    cols = {
        "speclt_rdn_earth_at": False,
        "mdat_trget_area_secd": False,
        "parcprc_uls_at": False,
        "public_house_earth_at": False,
    } | flags
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notices (house_manage_no, pblanc_no, house_nm, subscrpt_area_nm,"
                " rcrit_pblanc_de, speclt_rdn_earth_at, mdat_trget_area_secd, parcprc_uls_at,"
                " public_house_earth_at, raw) VALUES (:h, :h, :nm, :a, :de, :f1, :f2, :f3, :f4,"
                " '{}')"
            ),
            {
                "h": hmn,
                "nm": f"단지 {n}",
                "a": area,
                "de": de,
                "f1": cols["speclt_rdn_earth_at"],
                "f2": cols["mdat_trget_area_secd"],
                "f3": cols["parcprc_uls_at"],
                "f4": cols["public_house_earth_at"],
            },
        )
        for i, (special, by_type) in enumerate(models, start=1):
            conn.execute(
                text(
                    "INSERT INTO notice_models (house_manage_no, pblanc_no, model_no,"
                    " spsply_hshldco, raw) VALUES (:h, :h, :m, :s, CAST(:raw AS jsonb))"
                ),
                {"h": hmn, "m": f"{i:02d}", "s": special, "raw": json.dumps(by_type)},
            )
    return hmn


def _on(plans):
    return {p.id: p.on for p in plans}


def test_seven_axes_in_design_order():
    assert IDS == [
        "homeless",
        "account",
        "residence",
        "income_asset",
        "rewin",
        "householder",
        "special_type",
    ]
    assert all(a.expected for a in axes.AXES)


def test_plan_returns_seven_axes_with_reason_and_mst(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    plans = axes.plan(pg_engine, hmn)
    assert [p.id for p in plans] == IDS
    assert all(p.reason for p in plans)
    assert {p.law_mst for p in plans} == {"286965"}


def test_always_on_axes_have_one_query_each(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, area="인천", models=[(0, {})])
    by_id = {p.id: p for p in axes.plan(pg_engine, hmn)}
    for axis_id in ("homeless", "account", "residence"):
        assert by_id[axis_id].on and len(by_id[axis_id].queries) == 1
    assert "인천" in by_id["residence"].queries[0]


def test_special_axes_follow_the_sum_of_special_households(pg_engine):
    _version(pg_engine)
    off = _notice(pg_engine, 1, models=[(0, {}), (0, {})])
    on = _notice(pg_engine, 2, models=[(0, {}), (3, {"MNYCH_HSHLDCO": 3})])
    for hmn, want in ((off, False), (on, True)):
        got = _on(axes.plan(pg_engine, hmn))
        assert got["income_asset"] is want and got["special_type"] is want


def test_special_type_has_one_query_per_type_with_households(pg_engine):
    _version(pg_engine)
    hmn = _notice(
        pg_engine,
        models=[
            (5, {"MNYCH_HSHLDCO": 2, "NWWDS_HSHLDCO": 3, "LFE_FRST_HSHLDCO": 0}),
            (4, {"NWWDS_HSHLDCO": 1, "YGMN_HSHLDCO": 3}),
        ],
    )
    special = {p.id: p for p in axes.plan(pg_engine, hmn)}["special_type"]
    assert len(special.queries) == 3
    joined = " ".join(special.queries)
    assert "다자녀가구" in joined and "신혼부부" in joined and "청년" in joined
    assert "생애최초" not in joined


def test_special_type_falls_back_to_one_sentence_when_no_type_counts(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(4, {})])
    special = {p.id: p for p in axes.plan(pg_engine, hmn)}["special_type"]
    assert special.on and special.queries == [axes.Q_SPECIAL_NO_TYPE]


@pytest.mark.parametrize(
    "flag",
    ["speclt_rdn_earth_at", "mdat_trget_area_secd", "parcprc_uls_at", "public_house_earth_at"],
)
def test_rewin_turns_on_for_each_regulation_flag(pg_engine, flag):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})], **{flag: True})
    rewin = {p.id: p for p in axes.plan(pg_engine, hmn)}["rewin"]
    assert rewin.on and len(rewin.queries) == 1
    assert dict(axes.REGULATION_FLAGS)[flag] in rewin.reason


def test_rewin_off_when_all_flags_false(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    rewin = {p.id: p for p in axes.plan(pg_engine, hmn)}["rewin"]
    assert not rewin.on and rewin.queries == []
    assert rewin.reason == "투기과열·청약과열·분양가상한제·공공택지 표시 모두 거짓"
    assert rewin.line == "재당첨제한: 꺼짐 — 투기과열·청약과열·분양가상한제·공공택지 표시 모두 거짓"


def test_householder_follows_overheated_area_or_old_parents(pg_engine):
    _version(pg_engine)
    cases = [
        (_notice(pg_engine, 1, models=[(0, {})]), False),
        (_notice(pg_engine, 2, models=[(0, {})], speclt_rdn_earth_at=True), True),
        (_notice(pg_engine, 3, models=[(0, {})], mdat_trget_area_secd=True), True),
        (_notice(pg_engine, 4, models=[(0, {})], parcprc_uls_at=True), False),  # 세대주 요건 아님
        (_notice(pg_engine, 5, models=[(2, {"OLD_PARNTS_SUPORT_HSHLDCO": 2})]), True),
    ]
    for hmn, want in cases:
        assert _on(axes.plan(pg_engine, hmn))["householder"] is want, hmn


def test_notice_without_models_has_special_axes_off(pg_engine):
    _version(pg_engine)
    hmn = _notice(pg_engine)
    got = _on(axes.plan(pg_engine, hmn))
    assert not got["income_asset"] and not got["special_type"]


def test_law_mst_is_none_when_no_version_covers_the_notice(pg_engine):
    _version(pg_engine, effective="2027-01-01")  # 공고일보다 늦다
    hmn = _notice(pg_engine, models=[(0, {})])
    assert {p.law_mst for p in axes.plan(pg_engine, hmn)} == {None}


def test_unknown_notice_raises_lookup_error(pg_engine):
    with pytest.raises(LookupError):
        axes.plan(pg_engine, "no-such")
