from sqlalchemy import text

from cheongyak_rag.ingest import notice
from tests.notice_fakes import make_model, make_notice


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def _rows(raws, conv):
    return [conv(r).row for r in raws]


def test_upsert_twice_keeps_row_count(pg_engine):
    notices = [make_notice(i) for i in range(1, 4)]
    models = [make_model(n, "01") for n in notices] + [make_model(notices[0], "02")]
    n_rows, m_rows = _rows(notices, notice.to_notice_row), _rows(models, notice.to_model_row)

    assert notice.upsert(pg_engine, notice.NOTICES, n_rows) == (3, 0)
    assert notice.upsert(pg_engine, notice.MODELS, m_rows) == (4, 0)
    assert notice.upsert(pg_engine, notice.NOTICES, n_rows) == (0, 3)
    assert notice.upsert(pg_engine, notice.MODELS, m_rows) == (0, 4)

    assert _count(pg_engine, "notices") == 3
    assert _count(pg_engine, "notice_models") == 4


def test_upsert_updates_changed_values_and_fetched_at(pg_engine):
    n = make_notice(1)
    notice.upsert(pg_engine, notice.NOTICES, _rows([n], notice.to_notice_row))
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE notices SET fetched_at = '2000-01-01'"))

    n2 = make_notice(1, HOUSE_NM="정정된 이름", TOT_SUPLY_HSHLDCO=7)
    notice.upsert(pg_engine, notice.NOTICES, _rows([n2], notice.to_notice_row))

    with pg_engine.connect() as conn:
        name, hh, raw_nm, fetched_year = conn.execute(
            text(
                "SELECT house_nm, tot_suply_hshldco, raw->>'HOUSE_NM',"
                " extract(year from fetched_at) FROM notices"
            )
        ).one()
    assert (name, hh, raw_nm) == ("정정된 이름", 7, "정정된 이름")
    assert fetched_year > 2000


def test_upsert_stores_raw_with_every_key_and_types(pg_engine):
    n = make_notice(1, RCEPT_BGNDE="")
    notice.upsert(pg_engine, notice.NOTICES, _rows([n], notice.to_notice_row))

    with pg_engine.connect() as conn:
        raw, bgn, de, flag = conn.execute(
            text("SELECT raw, rcept_bgnde, rcrit_pblanc_de, parcprc_uls_at FROM notices")
        ).one()
    assert raw == n
    assert bgn is None and str(de) == "2026-10-01" and flag is False


def test_upsert_splits_into_chunks_and_still_counts_every_row(pg_engine):
    # CHUNK 500 기준으로 세 덩어리다
    rows = _rows([make_notice(i) for i in range(1, 1201)], notice.to_notice_row)

    assert notice.upsert(pg_engine, notice.NOTICES, rows) == (1200, 0)
    assert notice.upsert(pg_engine, notice.NOTICES, rows) == (0, 1200)

    assert _count(pg_engine, "notices") == 1200


def test_upsert_collapses_the_same_pk_inside_one_batch(pg_engine):
    # 안 합치면 Postgres가 "cannot affect row a second time"으로 거부한다
    first = make_notice(1, HOUSE_NM="앞")
    last = make_notice(1, HOUSE_NM="뒤")

    rows = _rows([first, last], notice.to_notice_row)

    assert notice.upsert(pg_engine, notice.NOTICES, rows) == (1, 0)

    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT house_nm FROM notices")).scalar() == "뒤"


def test_upsert_empty_is_a_noop(pg_engine):
    assert notice.upsert(pg_engine, notice.NOTICES, []) == (0, 0)


def test_models_need_their_notice_first(pg_engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    orphan = notice.to_model_row(make_model(make_notice(9), "01")).row
    with pytest.raises(IntegrityError):
        notice.upsert(pg_engine, notice.MODELS, [orphan])


def test_deleting_a_notice_cascades_to_its_models(pg_engine):
    n = make_notice(1)
    notice.upsert(pg_engine, notice.NOTICES, _rows([n], notice.to_notice_row))
    notice.upsert(pg_engine, notice.MODELS, _rows([make_model(n, "01")], notice.to_model_row))

    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM notices"))

    assert _count(pg_engine, "notice_models") == 0
