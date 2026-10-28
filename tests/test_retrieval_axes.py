import json

import pytest
from sqlalchemy import text

from cheongyak_rag.retrieval import axes, index_db
from cheongyak_rag.retrieval.query import Index
from tests.fakes import FakeEmbedder
from tests.test_retrieval_query import FAQ, LAW

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


# ── search ───────────────────────────────────────────────────────────────


def _load_chunks(engine, *, other_mst=True):
    """공고 MST(286965) 조문 3개 + FAQ, 그리고 다른 MST(999) 조문 3개."""
    emb = FakeEmbedder(dim=1536)
    rows = index_db.build_rows(emb, "286965", "article", law_rows=LAW, faq_rows=FAQ)
    if other_mst:
        old = [
            {**r, "chunk_id": "old-" + r["chunk_id"], "law_mst": "999"}
            for r in rows
            if r["source"] == "law"
        ]
        rows += old
    index_db.load(engine, rows)
    return emb


def _setup(engine, **kw):
    _version(engine)
    hmn = _notice(engine, models=[(4, {"MNYCH_HSHLDCO": 4})], speclt_rdn_earth_at=True, **kw)
    return hmn, _load_chunks(engine)


def test_search_returns_only_on_axes(pg_engine):
    hmn, emb = _setup(pg_engine)
    res = axes.search(pg_engine, emb, hmn)
    assert [r.id for r in res] == IDS  # 이 공고는 7축이 다 켜진다
    hmn2 = _notice(pg_engine, 2, models=[(0, {})])
    res2 = axes.search(pg_engine, emb, hmn2)
    assert [r.id for r in res2] == ["homeless", "account", "residence"]


def test_search_law_hits_come_only_from_the_notice_mst(pg_engine):
    hmn, emb = _setup(pg_engine)
    for r in axes.search(pg_engine, emb, hmn):
        for h in r.hits:
            assert h.law and all(not c.chunk_id.startswith("old-") for c in h.law)
            assert h.law_pool == 3 and h.law_dense == 3


def test_search_counts_follow_k_and_faq_k(pg_engine):
    hmn, emb = _setup(pg_engine)
    for r in axes.search(pg_engine, emb, hmn, k=2, faq_k=1):
        for h in r.hits:
            assert len(h.law) == 2 and len(h.faq) == 1
            assert all(c.source == "law" for c in h.law) and all(c.source == "faq" for c in h.faq)


def test_search_chunk_has_the_same_fields_as_index(pg_engine):
    hmn, emb = _setup(pg_engine)
    c = axes.search(pg_engine, emb, hmn)[0].hits[0].law[0]
    assert c.label.startswith("제") and c.path and c.text and c.meta["title"]


def test_search_matches_the_in_memory_index(pg_engine):
    hmn, emb = _setup(pg_engine)
    index = Index("article", emb, law_rows=LAW, faq_rows=FAQ)
    for r in axes.search(pg_engine, emb, hmn, k=3, faq_k=3):
        for h in r.hits:
            want = index.search(h.query, 3, faq_k=3)
            assert [c.chunk_id for c in h.law] == [c.chunk_id for c in want["law"]]
            assert [c.chunk_id for c in h.faq] == [c.chunk_id for c in want["faq"]]


def test_search_embeds_all_queries_in_one_call_and_reuses_the_cache(pg_engine):
    hmn, emb = _setup(pg_engine)
    emb.calls.clear()
    cache = {}
    axes.search(pg_engine, emb, hmn, cache=cache)
    assert len(emb.calls) == 1
    assert set(cache) == {("law", "286965"), ("faq", None)}
    bm25 = cache[("law", "286965")].bm25
    axes.search(pg_engine, emb, hmn, cache=cache)
    assert cache[("law", "286965")].bm25 is bm25


def test_search_without_mst_has_no_law_hits(pg_engine):
    _version(pg_engine, effective="2027-01-01")
    hmn = _notice(pg_engine, models=[(0, {})])
    emb = _load_chunks(pg_engine)
    res = axes.search(pg_engine, emb, hmn)
    assert res and all(not h.law and h.faq for r in res for h in r.hits)


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_prints_all_axis_names_and_hit_lines(pg_engine, capsys):
    hmn, emb = _setup(pg_engine)
    assert axes.main([hmn, "-k", "2", "--faq-k", "1"], engine=pg_engine, embedder=emb) == 0
    out = capsys.readouterr().out
    assert "단지 1" in out and "286965" in out
    for a in axes.AXES:
        assert a.name in out
    assert "재당첨제한: 켜짐 — 투기과열지구 표시 참" in out
    assert "질의: " + axes.Q_HOMELESS in out
    assert "조문 상위 2개" in out and "FAQ 상위 1개" in out
    assert "1. 제" in out and "1. Q" in out


def test_cli_off_axis_has_no_result_section(pg_engine, capsys):
    _version(pg_engine)
    hmn = _notice(pg_engine, models=[(0, {})])
    emb = _load_chunks(pg_engine)
    assert axes.main([hmn], engine=pg_engine, embedder=emb) == 0
    out = capsys.readouterr().out
    assert "재당첨제한: 꺼짐 — " in out
    assert "## 재당첨제한" not in out and "## 무주택 여부·기간" in out


def test_cli_unknown_notice_exits_2(pg_engine, capsys):
    assert axes.main(["nope"], engine=pg_engine, embedder=FakeEmbedder(dim=1536)) == 2
    assert "nope" in capsys.readouterr().err
