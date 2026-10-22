from datetime import date

import httpx
import pytest

from cheongyak_rag.ingest import notice
from tests.notice_fakes import (
    DETAIL,
    KEY_DECODED,
    KEY_ENCODED,
    MODELS,
    FakeApi,
    make_model,
    make_notice,
)

COND = {"cond[RCRIT_PBLANC_DE::GTE]": "2026-07-22"}


def _no_sleep(_s):
    pass


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 10, 22), date(2026, 7, 22)),
        (date(2026, 10, 31), date(2026, 7, 31)),
        (date(2026, 5, 31), date(2026, 2, 28)),  # 2월에 31일이 없다
        (date(2024, 5, 31), date(2024, 2, 29)),  # 윤년
        (date(2026, 1, 15), date(2025, 10, 15)),  # 해를 넘긴다
    ],
)
def test_since_is_calendar_months_back_clamped_to_month_end(today, expected):
    assert notice.since(today, 3) == expected


def test_since_months_is_adjustable():
    assert notice.since(date(2026, 10, 22), 12) == date(2025, 10, 22)


def test_fetch_all_pages_by_match_count_and_ignores_total_count():
    # totalCount는 필터와 무관한 전체 건수다. 페이지 수는 matchCount로 정한다
    api = FakeApi([make_notice(i) for i in range(2500)], total_count=2909)

    rows, match, calls = notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=_no_sleep)

    assert (len(rows), match, calls) == (2500, 2500, 3)
    assert [p["page"] for _, p in api.requests] == ["1", "2", "3"]
    assert {p["perPage"] for _, p in api.requests} == {"1000"}


def test_fetch_all_with_no_match_makes_one_call():
    api = FakeApi([make_notice(1, de="2020-01-01")])

    rows, match, calls = notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, COND, sleep=_no_sleep)

    assert (rows, match, calls) == ([], 0, 1)


def test_fetch_all_sends_date_condition_and_unquoted_key():
    api = FakeApi([make_notice(1, de="2026-10-01"), make_notice(2, de="2026-01-01")])

    rows, match, _ = notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, COND, sleep=_no_sleep)

    ((op, params),) = api.requests
    assert op == DETAIL
    assert params["cond[RCRIT_PBLANC_DE::GTE]"] == "2026-07-22"
    assert params["serviceKey"] == KEY_DECODED  # 한 번 풀린 값이 가고, httpx가 한 번만 인코딩한다
    assert (match, [r["HOUSE_MANAGE_NO"] for r in rows]) == (1, ["2026000001"])


def test_fetch_all_models_per_notice_condition():
    a, b = make_notice(1), make_notice(2)
    api = FakeApi([a, b], [make_model(a, "01"), make_model(a, "02"), make_model(b, "01")])
    cond = {
        "cond[HOUSE_MANAGE_NO::EQ]": a["HOUSE_MANAGE_NO"],
        "cond[PBLANC_NO::EQ]": a["PBLANC_NO"],
    }

    rows, match, calls = notice.fetch_all(MODELS, api.client(), KEY_ENCODED, cond, sleep=_no_sleep)

    assert (len(rows), match, calls) == (2, 2, 1)
    assert api.requests[0][1]["cond[HOUSE_MANAGE_NO::EQ]"] == a["HOUSE_MANAGE_NO"]


def test_fetch_all_paces_requests():
    api = FakeApi([make_notice(i) for i in range(2500)])
    slept = []

    notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=slept.append)

    assert slept == [0.1, 0.1, 0.1]


def test_retries_429_with_exponential_wait_and_counts_calls():
    api = FakeApi([make_notice(1)])
    api.fail_with = [httpx.Response(429), httpx.Response(503)]
    slept = []

    rows, match, calls = notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=slept.append)

    assert (len(rows), match, calls) == (1, 1, 3)  # 재시도 포함
    assert [s for s in slept if s >= 1] == [1, 2]


def test_gives_up_after_four_retries():
    api = FakeApi([make_notice(1)])
    api.fail_with = [httpx.Response(500)] * 10
    slept = []

    with pytest.raises(notice.NoticeApiError, match="HTTP 500"):
        notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=slept.append)

    assert len(api.requests) == 5
    assert [s for s in slept if s >= 1] == [1, 2, 4, 8]


def test_retries_connection_errors():
    api = FakeApi([make_notice(1)])
    api.fail_with = [httpx.ConnectError("boom")]

    rows, _, calls = notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=_no_sleep)

    assert (len(rows), calls) == (1, 2)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_fail_immediately(status):
    api = FakeApi([make_notice(1)])
    api.fail_with = [httpx.Response(status, text="denied")]

    with pytest.raises(notice.NoticeApiError, match=f"HTTP {status}"):
        notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=_no_sleep)

    assert len(api.requests) == 1


def test_wrong_key_is_401_from_the_server():
    api = FakeApi([make_notice(1)])

    with pytest.raises(notice.NoticeApiError, match="HTTP 401"):
        notice.fetch_all(DETAIL, api.client(), "other%2Bkey", {}, sleep=_no_sleep)


def test_key_never_appears_in_exceptions():
    leaks = [
        httpx.Response(401, text=f"bad key {KEY_DECODED} / {KEY_ENCODED}"),
        httpx.ConnectError(f"https://x/?serviceKey={KEY_ENCODED} refused"),
        httpx.Response(200, text=f"not json {KEY_DECODED}"),
    ]
    for leak in leaks:
        api = FakeApi([make_notice(1)])
        api.fail_with = [leak] * 10

        with pytest.raises(notice.NoticeApiError) as err:
            notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=_no_sleep)

        text = str(err.value) + repr(err.value) + repr(err.value.__cause__)
        assert KEY_DECODED not in text and KEY_ENCODED not in text
        assert err.value.__suppress_context__  # 키가 든 원래 예외가 traceback에 붙지 않는다


def test_malformed_body_is_an_error_not_an_empty_result():
    api = FakeApi([])
    api.fail_with = [httpx.Response(200, json={"hello": "world"})]

    with pytest.raises(notice.NoticeApiError, match="matchCount"):
        notice.fetch_all(DETAIL, api.client(), KEY_ENCODED, {}, sleep=_no_sleep)
