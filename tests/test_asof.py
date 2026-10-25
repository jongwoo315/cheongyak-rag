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

    def __init__(self, wrong=()):
        self.wrong = set(wrong)
        self.requests: list[httpx.Request] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        p = request.url.params
        assert p["OC"] == FAKE_OC and p["target"] == "eflaw" and p["type"] == "JSON"
        info = {
            "법령명_한글": LAW_NAME,
            "시행일자": p["efYd"],
            "공포번호": "no-other" if p["MST"] in self.wrong else f"no-{p['MST']}",
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
    assert "API 오류" in shown.err and FAKE_OC not in shown.out + shown.err


def test_empty_oc_exits_1(pg_engine, paths, monkeypatch, capsys):
    monkeypatch.setattr(asof.settings, "law_oc", "")
    _setup(pg_engine)

    assert run(pg_engine, paths) == 1
    assert "LAW_OC" in capsys.readouterr().err
