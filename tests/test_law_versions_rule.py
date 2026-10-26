"""공고별 유효 버전을 고르는 규칙(view `notice_law_versions`, 설계 §1)을 다섯 경우로 고정한다.

값은 착수 때 법제처 eflaw 목록에서 잰 실측이다.
"""

from datetime import date

from sqlalchemy import text

from cheongyak_rag.ingest import notice
from tests.notice_fakes import make_notice

LAW = "008243"

# (mst, 시행일, 공포일)
V_OLDEST = ("100001", date(2005, 3, 9), date(2005, 3, 9))
V_SAME_DAY_EARLY = ("257091", date(2024, 7, 1), date(2023, 12, 20))
V_SAME_DAY_LATE = ("261483", date(2024, 7, 1), date(2024, 3, 25))
V_STAGED_1 = ("265605", date(2024, 10, 1), date(2024, 9, 30))
V_STAGED_2 = ("265605", date(2024, 11, 1), date(2024, 9, 30))


def _load(engine, versions, law_id=LAW):
    with engine.begin() as conn:
        for mst, eff, prom in versions:
            conn.execute(
                text(
                    "INSERT INTO law_versions (law_id, mst, effective_date, promulgation_date,"
                    " promulgation_no, raw) VALUES (:l, :m, :e, :p, :n, '{}')"
                ),
                {"l": law_id, "m": mst, "e": eff, "p": prom, "n": f"no-{mst}"},
            )


def _notices(engine, *dates):
    rows = [
        notice.to_notice_row(make_notice(i, de=d.isoformat())).row
        for i, d in enumerate(dates, start=1)
    ]
    notice.upsert(engine, notice.NOTICES, rows)


def _picked(engine):
    """모집공고일 → (mst, 시행일). 공고마다 한 행이다."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rcrit_pblanc_de, mst, effective_date FROM notice_law_versions")
        ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


ALL = [V_OLDEST, V_SAME_DAY_EARLY, V_SAME_DAY_LATE, V_STAGED_1, V_STAGED_2]


def test_effective_day_itself_applies(pg_engine):
    _load(pg_engine, ALL)
    _notices(pg_engine, date(2024, 10, 1))

    assert _picked(pg_engine) == {date(2024, 10, 1): ("265605", date(2024, 10, 1))}


def test_day_before_effective_date_keeps_the_previous_version(pg_engine):
    _load(pg_engine, ALL)
    _notices(pg_engine, date(2024, 9, 30))

    # 2024-10-01 시행분은 아직 아니다. 그 앞은 2024-07-01(같은 날 둘 중 공포가 늦은 쪽)이다
    assert _picked(pg_engine) == {date(2024, 9, 30): ("261483", date(2024, 7, 1))}


def test_staged_enforcement_of_one_mst_picks_the_latest_effective_date(pg_engine):
    _load(pg_engine, ALL)
    _notices(pg_engine, date(2024, 10, 31), date(2024, 11, 1))

    # 같은 MST 265605가 두 시행일로 있다. 단계 시행일이 지난 뒤에는 뒤 시행일 행이다
    assert _picked(pg_engine) == {
        date(2024, 10, 31): ("265605", date(2024, 10, 1)),
        date(2024, 11, 1): ("265605", date(2024, 11, 1)),
    }


def test_two_mst_on_the_same_day_picks_the_later_promulgated(pg_engine):
    # 넣는 순서를 거꾸로 해도 같아야 한다
    _load(pg_engine, [V_SAME_DAY_LATE, V_SAME_DAY_EARLY])
    _notices(pg_engine, date(2024, 7, 1))

    assert _picked(pg_engine) == {date(2024, 7, 1): ("261483", date(2024, 7, 1))}


def test_same_day_same_promulgation_picks_the_larger_mst(pg_engine):
    _load(
        pg_engine,
        [
            ("100", date(2020, 1, 1), date(2019, 12, 1)),
            ("200", date(2020, 1, 1), date(2019, 12, 1)),
        ],
    )
    _notices(pg_engine, date(2020, 1, 1))

    assert _picked(pg_engine) == {date(2020, 1, 1): ("200", date(2020, 1, 1))}


def test_mst_tie_break_compares_numbers_not_text(pg_engine):
    # 글자 순서로는 "99999" > "100001"이다
    _load(
        pg_engine,
        [
            ("99999", date(2010, 1, 1), date(2009, 12, 1)),
            ("100001", date(2010, 1, 1), date(2009, 12, 1)),
        ],
    )
    _notices(pg_engine, date(2010, 1, 1))

    assert _picked(pg_engine) == {date(2010, 1, 1): ("100001", date(2010, 1, 1))}


def test_missing_promulgation_date_loses_to_a_known_one(pg_engine):
    _load(
        pg_engine, [("900", date(2020, 1, 1), None), ("100", date(2020, 1, 1), date(2019, 12, 1))]
    )
    _notices(pg_engine, date(2020, 1, 1))

    assert _picked(pg_engine) == {date(2020, 1, 1): ("100", date(2020, 1, 1))}


def test_notice_before_the_oldest_version_has_no_version(pg_engine):
    _load(pg_engine, ALL)
    _notices(pg_engine, date(2005, 3, 8), date(2005, 3, 9))

    assert _picked(pg_engine) == {
        date(2005, 3, 8): (None, None),
        date(2005, 3, 9): ("100001", date(2005, 3, 9)),
    }


def test_view_carries_the_promulgation_date_and_number_of_the_picked_row(pg_engine):
    _load(pg_engine, ALL)
    _notices(pg_engine, date(2024, 7, 1), date(2024, 10, 31))

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rcrit_pblanc_de, promulgation_date, promulgation_no"
                " FROM notice_law_versions"
            )
        ).all()

    assert {r[0]: (r[1], r[2]) for r in rows} == {
        date(2024, 7, 1): (date(2024, 3, 25), "no-261483"),
        date(2024, 10, 31): (date(2024, 9, 30), "no-265605"),
    }
    assert len(rows) == 2  # 공고마다 한 행


def test_view_has_one_row_per_notice_even_without_versions(pg_engine):
    _notices(pg_engine, date(2026, 8, 1), date(2026, 8, 1), date(2026, 9, 1))  # 3 공고

    with pg_engine.connect() as conn:
        n_view = conn.execute(text("SELECT count(*) FROM notice_law_versions")).scalar()
        n_null = conn.execute(
            text("SELECT count(*) FROM notice_law_versions WHERE mst IS NULL")
        ).scalar()
    assert (n_view, n_null) == (3, 3)


def test_other_laws_are_ignored(pg_engine):
    _load(pg_engine, [V_OLDEST])
    _load(pg_engine, [("999", date(2025, 1, 1), date(2025, 1, 1))], law_id="000001")
    _notices(pg_engine, date(2026, 1, 1))

    assert _picked(pg_engine) == {date(2026, 1, 1): ("100001", date(2005, 3, 9))}
