import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from cheongyak_rag.ingest import notice, notice_doc
from tests.notice_fakes import make_notice
from tests.test_notice_doc_fetch import NO_LINK, WITH_LINK, attach, make_pdf

N1, N2, N3 = "2026000001", "2026000002", "2026000003"


class Site:
    """no=1 링크 있음, no=2 링크 없음, no=3 페이지 404."""

    def __init__(self, boom_on: str | None = None):
        self.requests: list[str] = []
        self.boom_on = boom_on

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.host == "www.applyhome.co.kr":
            no = request.url.params["no"]
            if no == self.boom_on:
                raise RuntimeError("예상 밖 오류")
            return {
                "1": httpx.Response(200, text=WITH_LINK),
                "2": httpx.Response(200, text=NO_LINK),
            }.get(no, httpx.Response(404, text="없음"))
        return attach(make_pdf())

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    @property
    def doc_requests(self) -> int:
        return sum("getAtchmnfl.do" in r for r in self.requests)


@pytest.fixture
def engine(pg_engine):
    rows = [notice.to_notice_row(make_notice(n)).row for n in (1, 2, 3)]
    notice.upsert(pg_engine, notice.NOTICES, rows)
    return pg_engine


def run(site, engine, tmp_path, *extra, name="last_run.json"):
    return notice_doc.main(
        ["--out", str(tmp_path / name), "--dir", str(tmp_path / "notices"), *extra],
        client=site.client(),
        engine=engine,
        sleep=lambda _s: None,
    )


def manifest(tmp_path) -> list[dict]:
    path = tmp_path / "notices" / "manifest.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_end_to_end_writes_manifest_summary_and_never_writes_db(engine, tmp_path):
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM notices")).scalar()

    assert run(Site(), engine, tmp_path) == 0

    rows = manifest(tmp_path)
    assert [(r["house_manage_no"], r["result"]) for r in rows] == [
        (N1, "pdf"),
        (N2, "no_link"),
        (N3, "error"),
    ]
    assert rows[1]["url"] is None and "apply.lh.or.kr" in rows[1]["note"]
    assert "404" in rows[2]["error"]
    assert Path(rows[0]["path"]).is_file()

    s = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert s["notices"] == 3
    assert s["results"] == {"pdf": 1, "hwp": 0, "other": 0, "no_link": 1, "error": 1}
    assert s["errors"] == 1 and s["with_link"] == 2
    assert s["new_downloads"] == 1 and s["downloaded_bytes"] == rows[0]["bytes"]
    assert s["error_notices"] == [f"{N3}/{N3}"] and s["no_link_notices"] == [f"{N2}/{N2}"]
    assert s["started_at"] and s["ended_at"] and s["elapsed_sec"] >= 0

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notices")).scalar() == before


def test_second_run_downloads_nothing_and_results_match(engine, tmp_path):
    first = Site()
    assert run(first, engine, tmp_path) == 0
    run1 = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert first.doc_requests == 1

    second = Site()
    assert run(second, engine, tmp_path) == 0
    run2 = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))

    assert second.doc_requests == 0
    assert run2["new_downloads"] == 0 and run2["downloaded_bytes"] == 0
    assert run2["results"] == run1["results"]
    assert len(manifest(tmp_path)) == 3


def test_one_notice_crashing_does_not_stop_the_rest(engine, tmp_path):
    assert run(Site(boom_on="1"), engine, tmp_path) == 0
    rows = {r["house_manage_no"]: r for r in manifest(tmp_path)}
    assert rows[N1]["result"] == "error" and "RuntimeError" in rows[N1]["error"]
    assert rows[N2]["result"] == "no_link" and rows[N3]["result"] == "error"


def test_limit_keeps_other_notices_rows_in_manifest(engine, tmp_path):
    assert run(Site(), engine, tmp_path) == 0
    assert run(Site(), engine, tmp_path, "--limit", "1") == 0

    assert len(manifest(tmp_path)) == 3  # 지난 줄을 지우지 않는다
    s = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert s["notices"] == 1 and s["limit"] == 1


def test_empty_notices_table_exits_1(pg_engine, tmp_path, capsys):
    assert run(Site(), pg_engine, tmp_path) == 1
    assert "공고" in capsys.readouterr().err
