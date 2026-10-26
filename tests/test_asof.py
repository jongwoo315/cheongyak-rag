import json
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from cheongyak_rag import asof
from cheongyak_rag.ingest import law_versions, notice
from cheongyak_rag.ingest.law import LAW_NAME
from tests.law_version_fakes import FAKE_OC, make_row
from tests.notice_fakes import make_notice

CURRENT = ("286965", date(2026, 6, 15), date(2026, 6, 15))
OLD = ("265605", date(2024, 10, 1), date(2024, 9, 30))
SAME_DAY_A = ("261483", date(2024, 7, 1), date(2024, 3, 25))
SAME_DAY_B = ("257091", date(2024, 7, 1), date(2023, 12, 20))


@pytest.fixture(autouse=True)
def oc(monkeypatch):
    monkeypatch.setattr(asof.settings, "law_oc", FAKE_OC)


class FakeService:
    """lawService.do 본문 조회. `wrong`에 든 MST는 공포번호를 다르게 준다."""

    def __init__(self, wrong=(), leak=False):
        self.wrong = set(wrong)
        self.leak = leak
        self.requests: list[httpx.Request] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        p = request.url.params
        assert p["OC"] == FAKE_OC and p["target"] == "eflaw" and p["type"] == "JSON"
        info = {
            "법령명_한글": LAW_NAME,
            "시행일자": p["efYd"],
            "공포번호": FAKE_OC
            if self.leak
            else "no-other"
            if p["MST"] in self.wrong
            else f"no-{p['MST']}",
        }
        return httpx.Response(200, json={"법령": {"기본정보": info}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self._handler))


def _load_versions(engine, *versions):
    rows = [law_versions.to_row(make_row(m, e, p), FAKE_OC) for m, e, p in versions]
    notice.upsert(engine, law_versions.LAW_VERSIONS, rows)


def _load_notices(engine, *dates):
    rows = [
        notice.to_notice_row(make_notice(i, de=d.isoformat())).row
        for i, d in enumerate(dates, start=1)
    ]
    notice.upsert(engine, notice.NOTICES, rows)


@pytest.fixture
def paths(tmp_path):
    return {
        "raw": tmp_path / "raw",
        "run": tmp_path / "runs" / "last_run.json",
        "md": tmp_path / "docs" / "78-asof.md",
        "versions_run": tmp_path / "runs" / "law_versions.json",
    }


def run(engine, paths, client=None):
    argv = [
        "--raw-dir", str(paths["raw"]),
        "--run", str(paths["run"]),
        "--out", str(paths["md"]),
        "--versions-run", str(paths["versions_run"]),
    ]  # fmt: skip
    return asof.main(argv, client=client or FakeService().client(), engine=engine)


def _setup(engine):
    _load_versions(engine, CURRENT, OLD, SAME_DAY_A, SAME_DAY_B)
    _load_notices(engine, date(2026, 8, 1), date(2026, 9, 1))


def test_all_notices_resolve_to_one_version_and_it_is_compared(pg_engine, paths, capsys):
    _setup(pg_engine)
    api = FakeService()

    assert run(pg_engine, paths, api.client()) == 0

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert (s["notices"], s["decided"], s["unresolved"]) == (2, 2, [])
    assert s["by_version"] == [
        {
            "mst": "286965",
            "effective_date": "2026-06-15",
            "promulgation_no": "no-286965",
            "notices": 2,
        }
    ]
    (c,) = s["compare"]
    assert c["ok"] and c["source"] == "api" and c["notices"] == 2
    assert s["calls"] == 1 and len(api.requests) == 1
    assert api.requests[0].url.params["efYd"] == "20260615"
    assert api.requests[0].url.params["MST"] == "286965"
    first = paths["md"].read_text(encoding="utf-8").splitlines()[0]
    assert first == (
        "공고 2/2건의 버전이 정해졌고, 고른 버전은 1개이며, 본문 대조는 1/1건 일치한다."
    )
    assert "1/1" in capsys.readouterr().out


def test_the_body_is_saved_and_the_next_run_does_not_call_the_api(pg_engine, paths):
    _setup(pg_engine)
    run(pg_engine, paths)
    saved = paths["raw"] / "law-008243-20260615.json"
    assert saved.exists()

    api = FakeService()
    assert run(pg_engine, paths, api.client()) == 0

    assert api.requests == []
    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert s["calls"] == 0 and s["compare"][0]["source"] == "cache"


def test_an_existing_raw_file_is_used_without_calling_the_api(pg_engine, paths):
    _setup(pg_engine)
    paths["raw"].mkdir(parents=True)
    body = {
        "법령": {
            "기본정보": {"법령명_한글": LAW_NAME, "시행일자": "20260615", "공포번호": "no-286965"}
        }
    }
    (paths["raw"] / "law-008243-20260615.json").write_text(json.dumps(body), encoding="utf-8")
    api = FakeService()

    assert run(pg_engine, paths, api.client()) == 0
    assert api.requests == []


def test_a_body_that_differs_from_the_row_exits_1_and_is_not_cached(pg_engine, paths):
    _setup(pg_engine)

    assert run(pg_engine, paths, FakeService(wrong={"286965"}).client()) == 1

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    (c,) = s["compare"]
    assert not c["ok"]
    assert c["expected"] == {"시행일자": "20260615", "공포번호": "no-286965"}
    assert c["actual"] == {"시행일자": "20260615", "공포번호": "no-other"}
    assert not (paths["raw"] / "law-008243-20260615.json").exists()
    assert "0/1건 일치" in paths["md"].read_text(encoding="utf-8").splitlines()[0]


def test_notices_older_than_the_oldest_version_are_listed_as_unresolved(pg_engine, paths):
    _load_versions(pg_engine, CURRENT, OLD)
    _load_notices(pg_engine, date(2024, 9, 30), date(2026, 8, 1), date(2024, 10, 1))

    assert run(pg_engine, paths) == 0

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert (s["notices"], s["decided"]) == (3, 2)
    (u,) = s["unresolved"]
    assert u["rcrit_pblanc_de"] == "2024-09-30"
    assert [v["mst"] for v in s["by_version"]] == ["286965", "265605"]
    md = paths["md"].read_text(encoding="utf-8")
    assert "공고 2/3건" in md.splitlines()[0]
    assert "2024-09-30" in md


def test_four_unresolved_notices_exit_1_but_the_report_is_written(pg_engine, paths, capsys):
    _load_versions(pg_engine, CURRENT, OLD)
    _load_notices(pg_engine, *[date(2024, 9, 29)] * 4, date(2026, 8, 1))

    assert run(pg_engine, paths) == 1

    assert "공고 1/5건" in paths["md"].read_text(encoding="utf-8").splitlines()[0]
    assert "미완" in capsys.readouterr().err


def test_no_notice_resolved_exits_1(pg_engine, paths):
    _load_versions(pg_engine, CURRENT)
    _load_notices(pg_engine, date(2020, 1, 1))

    assert run(pg_engine, paths) == 1


def test_same_day_report_names_the_mst_the_view_picks(pg_engine, paths):
    _setup(pg_engine)
    _load_notices(pg_engine, date(2024, 7, 1))  # 같은 날 둘인 날에 걸린 공고도 하나 둔다
    with pg_engine.connect() as conn:
        picked = conn.execute(
            text("SELECT mst FROM notice_law_versions WHERE rcrit_pblanc_de = '2024-07-01'")
        ).scalar()

    run(pg_engine, paths)

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert s["same_day_multi_mst"] == [
        {"effective_date": "2024-07-01", "msts": ["257091", "261483"], "picked": picked}
    ]
    assert picked == "261483"


def test_same_day_report_matches_the_view_on_ties_and_missing_dates(pg_engine, paths):
    # 리포트의 picked는 view 정렬을 SQL로 다시 적은 것이다. 동률·NULL에서도 view와 같아야 한다
    d1, d2 = date(2010, 1, 1), date(2011, 1, 1)
    _load_versions(
        pg_engine,
        ("99999", d1, date(2009, 12, 1)),  # 공포일 동률 — 글자 순서로는 99999가 크다
        ("100001", d1, date(2009, 12, 1)),
        ("100", d2, date(2010, 12, 1)),
    )
    with pg_engine.begin() as conn:  # make_row는 공포일 None을 시행일로 채우므로 SQL로 넣는다
        conn.execute(
            text(
                "INSERT INTO law_versions (law_id, mst, effective_date, raw)"
                " VALUES ('008243', '900', :d, '{}')"
            ),
            {"d": d2},
        )  # 공포일 NULL은 뒤로 간다
    _load_notices(pg_engine, d1, d2)
    with pg_engine.connect() as conn:
        viewed = dict(
            conn.execute(text("SELECT rcrit_pblanc_de, mst FROM notice_law_versions")).all()
        )

    run(pg_engine, paths)

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert {e["effective_date"]: e["picked"] for e in s["same_day_multi_mst"]} == {
        d1.isoformat(): viewed[d1],
        d2.isoformat(): viewed[d2],
    }
    assert (viewed[d1], viewed[d2]) == ("100001", "100")


def test_without_collected_versions_it_stops(pg_engine, paths, capsys):
    _load_notices(pg_engine, date(2026, 8, 1))

    assert run(pg_engine, paths) == 1
    assert "law_versions" in capsys.readouterr().err
    assert not paths["md"].exists()


def test_collection_summary_feeds_the_calls_and_rerun_rows(pg_engine, paths):
    _setup(pg_engine)
    paths["versions_run"].parent.mkdir(parents=True)
    paths["versions_run"].write_text(
        json.dumps(
            {
                "received": 4, "pages": 2, "calls": 2, "inserted": 0, "updated": 4,
                "rows_after": 4, "pk_digest": "abc",
                "previous": {"rows_after": 4, "pk_digest": "abc", "inserted": 4, "run_at": "x"},
            }
        ),
        encoding="utf-8",
    )  # fmt: skip

    run(pg_engine, paths)

    md = paths["md"].read_text(encoding="utf-8")
    assert "3회" in md  # 수집 2 + 본문 대조 1
    assert "새로 들어간 행은 0건" in md


def test_list_completeness_uses_the_rows_received_not_the_table_count(pg_engine, paths):
    _setup(pg_engine)  # 테이블에는 4행 — 수집이 지우지 않아 옛 행이 남은 상황을 흉내 낸다
    paths["versions_run"].parent.mkdir(parents=True)
    paths["versions_run"].write_text(
        json.dumps({"received": 128, "pages": 2, "calls": 2, "duplicates": 0}), encoding="utf-8"
    )

    run(pg_engine, paths)

    row = next(
        ln
        for ln in paths["md"].read_text(encoding="utf-8").splitlines()
        if ln.startswith("| 2. 목록 완결성")
    )
    assert "법령명 일치 128행(테이블에는 4행)" in row
    assert "128행 이하 → 미완" in row


def test_the_key_never_shows_up_anywhere(pg_engine, paths, capsys):
    _setup(pg_engine)
    run(pg_engine, paths)
    shown = capsys.readouterr()

    for blob in (shown.out, shown.err, paths["run"].read_text(), paths["md"].read_text()):
        assert FAKE_OC not in blob


def test_api_error_exits_1_without_the_key(pg_engine, paths, capsys):
    _setup(pg_engine)

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"upstream {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(boom))

    assert run(pg_engine, paths, client) == 1
    shown = capsys.readouterr()
    assert "본문 대조 실패" in shown.err and FAKE_OC not in shown.out + shown.err


def test_a_connection_error_message_with_the_url_never_leaks_the_key(pg_engine, paths, capsys):
    _setup(pg_engine)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(refuse))

    assert run(pg_engine, paths, client) == 1

    shown = capsys.readouterr()
    (c,) = json.loads(paths["run"].read_text(encoding="utf-8"))["compare"]
    assert "ConnectError" in c["error"]
    for blob in (shown.out, shown.err, paths["run"].read_text(), paths["md"].read_text()):
        assert FAKE_OC not in blob


def test_empty_oc_exits_1(pg_engine, paths, monkeypatch, capsys):
    monkeypatch.setattr(asof.settings, "law_oc", "")
    _setup(pg_engine)

    assert run(pg_engine, paths) == 1
    assert "LAW_OC" in capsys.readouterr().err


def test_a_report_that_would_contain_the_key_is_not_written(pg_engine, paths, capsys):
    _setup(pg_engine)

    # 어긋난 공포번호가 리포트의 기대/받은 값 칸으로 간다. 거기에 키가 있으면 쓰지 않는다
    assert run(pg_engine, paths, FakeService(leak=True).client()) == 1

    assert not paths["run"].exists() and not paths["md"].exists()
    shown = capsys.readouterr()
    assert "인증값" in shown.err and FAKE_OC not in shown.out + shown.err


def test_a_cached_body_that_disagrees_points_at_the_file(pg_engine, paths, capsys):
    _setup(pg_engine)
    paths["raw"].mkdir(parents=True)
    body = {
        "법령": {"기본정보": {"법령명_한글": LAW_NAME, "시행일자": "20260615", "공포번호": "old"}}
    }
    (paths["raw"] / "law-008243-20260615.json").write_text(json.dumps(body), encoding="utf-8")

    assert run(pg_engine, paths) == 1

    err = capsys.readouterr().err
    assert "law-008243-20260615.json" in err and "지우고" in err


def test_a_cached_file_of_another_law_is_an_error_not_a_match(pg_engine, paths):
    _setup(pg_engine)
    paths["raw"].mkdir(parents=True)
    body = {
        "법령": {
            "기본정보": {"법령명_한글": "다른 법", "시행일자": "20260615", "공포번호": "no-286965"}
        }
    }
    (paths["raw"] / "law-008243-20260615.json").write_text(json.dumps(body), encoding="utf-8")

    assert run(pg_engine, paths) == 1

    (c,) = json.loads(paths["run"].read_text(encoding="utf-8"))["compare"]
    assert not c["ok"] and "법령명" in c["error"]


def test_a_non_object_api_body_is_recorded_not_a_crash(pg_engine, paths):
    _setup(pg_engine)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))

    assert run(pg_engine, paths, client) == 1

    (c,) = json.loads(paths["run"].read_text(encoding="utf-8"))["compare"]
    assert not c["ok"] and "법령 객체가 아니다" in c["error"]


def test_a_failed_version_is_recorded_and_the_report_is_still_written(pg_engine, paths):
    _setup(pg_engine)

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    client = httpx.Client(transport=httpx.MockTransport(boom))

    assert run(pg_engine, paths, client) == 1

    (c,) = json.loads(paths["run"].read_text(encoding="utf-8"))["compare"]
    assert not c["ok"] and "HTTP 500" in c["error"]
    assert "0/1건 일치" in paths["md"].read_text(encoding="utf-8").splitlines()[0]


def test_one_mismatched_version_among_two_is_recorded_and_the_other_is_kept(pg_engine, paths):
    _load_versions(pg_engine, CURRENT, OLD)
    _load_notices(pg_engine, date(2026, 8, 1), date(2024, 10, 1))

    assert run(pg_engine, paths, FakeService(wrong={"265605"}).client()) == 1

    s = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert {c["mst"]: c["ok"] for c in s["compare"]} == {"286965": True, "265605": False}
    assert s["calls"] == 2
    assert (paths["raw"] / "law-008243-20260615.json").exists()
    assert not (paths["raw"] / "law-008243-20241001.json").exists()
    assert "1/2건 일치" in paths["md"].read_text(encoding="utf-8").splitlines()[0]


def test_band_rows_follows_the_plan_ranges():
    assert asof._band_rows(129, 0) == "129행 → 통과"
    assert "개정이 나온" in asof._band_rows(130, 0)
    assert "128행 이하 → 미완" in asof._band_rows(128, 0)
    assert "중복" in asof._band_rows(129, 1) and "미완" in asof._band_rows(129, 1)


def test_band_versions_follows_the_plan_ranges():
    expected = {asof.EXPECTED_VERSION}
    assert asof._band_versions(0, 0, expected) == "두 값 모두 0 → 통과"
    assert "1~3건" in asof._band_versions(3, 0, expected)
    assert "4건 이상" in asof._band_versions(4, 0, expected)
    assert "불일치 1건 이상" in asof._band_versions(0, 1, expected)
    assert "착수 실측" in asof._band_versions(0, 0, {("1", "2026-12-01")})


def test_band_calls_follows_the_plan_ranges():
    assert asof._band_calls(5) == "5 이하 정상"
    assert asof._band_calls(6).startswith("6~10") and asof._band_calls(10).startswith("6~10")
    assert asof._band_calls(11).startswith("11 이상")


def test_rerun_says_when_the_table_changed_or_there_is_no_previous_run():
    prev = {"rows_after": 129, "pk_digest": "a", "inserted": 129}
    same = {"rows_after": 129, "pk_digest": "a", "inserted": 0, "previous": prev}

    assert asof._rerun(None)[1] is None
    assert asof._rerun({"inserted": 0})[1] is None
    assert asof._rerun(same) == ("행 수와 PK 집합이 그대로, 새로 들어간 행은 0건", True)
    text_, ok = asof._rerun({**same, "pk_digest": "b"})
    assert ok is False and "달라졌다" in text_
    assert asof._rerun({**same, "inserted": 1})[1] is False
