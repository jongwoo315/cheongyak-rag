import json
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from cheongyak_rag.ingest import law_versions
from cheongyak_rag.ingest.law import LawApiError
from tests.law_version_fakes import FAKE_OC, FakeEflaw, make_row, make_rows


@pytest.fixture(autouse=True)
def oc(monkeypatch):
    monkeypatch.setattr(law_versions.settings, "law_oc", FAKE_OC)


def _api_with_other_laws() -> FakeEflaw:
    """우리 법령 129행 + 이름이 비슷한 다른 법령 48행 = 177행, 2페이지(100 + 77)."""
    ours = make_rows(129)
    others = make_rows(48, start_mst=5000, name="주택공급에 관한 규칙 일부개정령")
    mixed = [r for pair in zip(ours[:48], others, strict=True) for r in pair] + ours[48:]
    return FakeEflaw(mixed, total_count=177)


def test_reads_every_page_and_keeps_only_the_exact_law_name():
    api = _api_with_other_laws()

    rows, pages = law_versions.fetch_versions(FAKE_OC, api.client())

    assert (len(rows), pages) == (129, 2)
    assert {r["법령명한글"] for r in rows} == {"주택공급에 관한 규칙"}
    assert [r.url.params["page"] for r in api.requests] == ["1", "2"]
    assert {r.url.params["display"] for r in api.requests} == {"100"}


def test_a_page_of_exactly_100_rows_asks_for_one_more_page():
    api = FakeEflaw(make_rows(100))

    rows, pages = law_versions.fetch_versions(FAKE_OC, api.client())

    assert (len(rows), pages) == (100, 2)  # 둘째 페이지는 비어 있다


def test_single_row_comes_as_a_dict():
    api = FakeEflaw(make_rows(1))

    rows, pages = law_versions.fetch_versions(FAKE_OC, api.client())

    assert (len(rows), pages) == (1, 1)


def test_same_mst_and_date_twice_is_an_error():
    # 페이지 사이에 목록이 밀리면 같은 행이 두 번 오고 다른 행이 빠진다. 일부만 넣지 않는다
    rows = make_rows(100)
    rows[99] = rows[0]
    api = FakeEflaw(rows + make_rows(5, start_mst=9000))

    with pytest.raises(LawApiError, match="중복"):
        law_versions.fetch_versions(FAKE_OC, api.client())


def test_a_page_with_an_unexpected_shape_is_an_error_not_the_end_of_the_list():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(
                200, json={"LawSearch": {"totalCnt": "200", "law": make_rows(100)}}
            )
        return httpx.Response(200, json={})  # LawSearch가 없다

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(LawApiError, match="LawSearch"):
        law_versions.fetch_versions(FAKE_OC, client)


def test_fewer_rows_than_total_count_is_an_error():
    # 101행뿐인데 totalCnt는 200이다. 일부만 넣고 성공으로 끝내지 않는다
    api = FakeEflaw(make_rows(101), total_count=200)

    with pytest.raises(LawApiError, match="totalCnt"):
        law_versions.fetch_versions(FAKE_OC, api.client())


def test_no_matching_row_is_an_error():
    api = FakeEflaw(make_rows(3, name="주택공급에 관한 규칙 일부개정령"))

    with pytest.raises(LawApiError, match="하나도 없다"):
        law_versions.fetch_versions(FAKE_OC, api.client())


def test_never_ending_pages_stop_with_an_error():
    def endless(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        search = {"totalCnt": "100000", "law": make_rows(100, page * 1000)}
        return httpx.Response(200, json={"LawSearch": search})

    client = httpx.Client(transport=httpx.MockTransport(endless))

    with pytest.raises(LawApiError, match="페이지"):
        law_versions.fetch_versions(FAKE_OC, client)


def test_row_conversion_parses_dates_and_keeps_raw_without_the_key():
    raw = make_row("265605", date(2024, 10, 1), date(2024, 9, 30))

    row = law_versions.to_row(raw, FAKE_OC)

    assert row["law_id"] == "008243" and row["mst"] == "265605"
    assert row["effective_date"] == date(2024, 10, 1)
    assert row["promulgation_date"] == date(2024, 9, 30)
    assert row["promulgation_no"] == "no-265605"
    assert (row["law_name"], row["revision_kind"], row["status"]) == (
        "주택공급에 관한 규칙",
        "일부개정",
        "연혁",
    )
    assert FAKE_OC not in json.dumps(row["raw"], ensure_ascii=False)
    assert "OC=***" in row["raw"]["법령상세링크"]


def test_row_conversion_allows_a_blank_promulgation_date_but_not_a_blank_effective_date():
    assert (
        law_versions.to_row(make_row("1", date(2020, 1, 1), 공포일자=""), FAKE_OC)[
            "promulgation_date"
        ]
        is None
    )
    with pytest.raises(LawApiError, match="시행일자"):
        law_versions.to_row(make_row("1", date(2020, 1, 1), 시행일자=""), FAKE_OC)


def _count(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM law_versions")).scalar()


def _run(api, engine, out, **kw):
    return law_versions.main(["--out", str(out)], client=api.client(), engine=engine, **kw)


def test_main_loads_rows_and_reports(pg_engine, tmp_path, capsys):
    out = tmp_path / "law_versions.json"

    assert _run(_api_with_other_laws(), pg_engine, out) == 0

    assert _count(pg_engine) == 129
    s = json.loads(out.read_text(encoding="utf-8"))
    assert (s["received"], s["pages"], s["calls"]) == (129, 2, 2)
    assert (s["inserted"], s["updated"], s["rows_after"]) == (129, 0, 129)
    assert s["duplicates"] == 0 and s["previous"] is None
    assert (s["oldest"], s["newest"]) == ("2005-03-09", "2005-07-15")
    shown = capsys.readouterr().out
    assert "129" in shown and "넣은" in shown


def test_second_run_adds_nothing_and_keeps_the_pk_set(pg_engine, tmp_path):
    out = tmp_path / "law_versions.json"
    api = _api_with_other_laws()
    _run(api, pg_engine, out)
    first = json.loads(out.read_text(encoding="utf-8"))

    assert _run(api, pg_engine, out) == 0
    second = json.loads(out.read_text(encoding="utf-8"))

    assert (second["inserted"], second["updated"]) == (0, 129)
    assert second["rows_after"] == first["rows_after"] == 129
    assert second["pk_digest"] == first["pk_digest"]
    assert second["previous"]["pk_digest"] == first["pk_digest"]
    assert second["previous"]["inserted"] == 129


def test_main_lists_days_with_more_than_one_mst(pg_engine, tmp_path):
    rows = [
        make_row("261483", date(2024, 7, 1), date(2024, 3, 25)),
        make_row("257091", date(2024, 7, 1), date(2023, 12, 20)),
        make_row("265605", date(2024, 10, 1), date(2024, 9, 30)),
        make_row("265605", date(2024, 11, 1), date(2024, 9, 30)),  # 같은 MST의 단계 시행은 아니다
    ]
    out = tmp_path / "law_versions.json"

    assert _run(FakeEflaw(rows), pg_engine, out) == 0

    s = json.loads(out.read_text(encoding="utf-8"))
    assert s["same_day_multi_mst"] == [
        {"effective_date": "2024-07-01", "msts": ["257091", "261483"]}
    ]


def test_main_never_shows_the_key(pg_engine, tmp_path, capsys):
    out = tmp_path / "law_versions.json"
    _run(_api_with_other_laws(), pg_engine, out)
    shown = capsys.readouterr()

    assert FAKE_OC not in shown.out + shown.err
    assert FAKE_OC not in out.read_text(encoding="utf-8")
    with pg_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM law_versions WHERE raw::text LIKE :k"),
                {"k": f"%{FAKE_OC}%"},
            ).scalar()
            == 0
        )


def test_api_error_exits_1_without_the_key(pg_engine, tmp_path, capsys):
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"upstream {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    out = tmp_path / "law_versions.json"

    assert law_versions.main(["--out", str(out)], client=client, engine=pg_engine) == 1

    shown = capsys.readouterr()
    assert "API 오류" in shown.err
    assert FAKE_OC not in shown.out + shown.err
    assert _count(pg_engine) == 0 and not out.exists()


def test_empty_oc_exits_1(pg_engine, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(law_versions.settings, "law_oc", " ")

    assert _run(FakeEflaw([]), pg_engine, tmp_path / "x.json") == 1
    assert "LAW_OC" in capsys.readouterr().err
