"""별표 1 점수표 상수를 원문 표와 대조한다 (#77 통과 기준 2).

원문은 `data/raw/law-008243-20260615.json`의 별표 1 `별표내용`이다.
상자 그림 문자로 그린 표를 파싱한 (항목, 구간, 점수) 40행이 코드 상수와 전부 같아야 한다.
"""

import pytest

from cheongyak_rag import profile
from cheongyak_rag.profile_check import (
    EXPECTED_ROWS,
    RAW_LAW,
    constant_rows,
    load_raw_rows,
    parse_bracket,
    table_mismatches,
)


@pytest.fixture(scope="module")
def rows():
    # 조용한 skip 금지 — 원문이 없으면 실패시킨다
    if not RAW_LAW.exists():
        pytest.fail(f"법령 원문 없음: {RAW_LAW}")
    return load_raw_rows(RAW_LAW)


def test_parsed_row_counts(rows):
    """파싱이 행을 빠뜨리면 아래 대조가 공허하게 참이 된다 — 행 수가 16 · 7 · 17이다."""
    counts = {k: sum(1 for r in rows if r[0] == k) for k in EXPECTED_ROWS}
    assert counts == {"homeless": 16, "dependents": 7, "savings": 17}
    assert len(rows) == 40


def test_constants_equal_raw_table(rows):
    """코드 상수 40행이 원문 표를 파싱한 40행과 같다."""
    assert table_mismatches(rows, constant_rows()) == []
    assert len(constant_rows()) == 40


def test_mismatch_is_detected(rows):
    """대조가 공허하지 않다 — 한 칸이 틀리면 잡는다."""
    broken = [
        (k, lo, hi, s + 1) if i == 3 else (k, lo, hi, s) for i, (k, lo, hi, s) in enumerate(rows)
    ]
    assert (
        len(table_mismatches(broken, constant_rows())) == 2
    )  # 원문에만 있는 행 + 상수에만 있는 행


@pytest.mark.parametrize(
    ("text", "bounds"),
    [
        ("1년 미만", (0, 12)),
        ("8년 이상～9년 미만", (96, 108)),
        ("15년 이상", (180, None)),
        ("6개월 미만", (0, 6)),
        ("6개월 이상～1년 미만", (6, 12)),
        ("0명", (0, 1)),
        ("4명", (4, 5)),
        ("6명이상", (6, None)),
    ],
)
def test_parse_bracket(text, bounds):
    assert parse_bracket(text) == bounds


def test_lookup_matches_table_rows(rows):
    """원문 표의 각 구간 시작 값과 끝 직전 값을 조회하면 그 행의 점수가 나온다."""
    lookups = {
        "homeless": profile.homeless_points,
        "dependents": profile.dependents_points,
        "savings": profile.savings_points,
    }
    for key, lo, hi, score in rows:
        assert lookups[key](lo) == score, (key, lo)
        if hi is not None:
            assert lookups[key](hi - 1) == score, (key, hi - 1)
