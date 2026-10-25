import json
import logging
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from cheongyak_rag.ingest import notice
from tests.notice_fakes import KEY_DECODED, KEY_ENCODED, FakeApi, make_model, make_notice

TODAY = date(2026, 10, 22)


@pytest.fixture
def api():
    new1, new2, no_models = make_notice(1), make_notice(2), make_notice(3)
    old = make_notice(4, de="2026-01-05")  # 기간 밖
    models = [make_model(new1, "01"), make_model(new1, "02"), make_model(new2, "01")]
    models.append(make_model(old, "01"))
    return FakeApi([new1, new2, no_models, old], models)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(notice.settings, "data_go_kr_key", KEY_ENCODED)


def run(api, engine, out, extra=()):
    return notice.main(
        ["--out", str(out), *extra],
        client=api.client(),
        engine=engine,
        sleep=lambda _s: None,
        today=TODAY,
    )


def test_end_to_end_loads_window_only_and_reports(api, pg_engine, tmp_path, capsys):
    out = tmp_path / "last_run.json"

    assert run(api, pg_engine, out) == 0

    with pg_engine.connect() as conn:
        pks = [r[0] for r in conn.execute(text("SELECT house_manage_no FROM notices ORDER BY 1"))]
        n_models = conn.execute(text("SELECT count(*) FROM notice_models")).scalar()
    assert pks == ["2026000001", "2026000002", "2026000003"]  # 기간 밖 공고는 없다
    assert n_models == 3

    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["since"] == "2026-07-22"
    assert summary["notices"]["match_count"] == 3 and summary["notices"]["received"] == 3
    assert summary["notices"]["inserted"] == 3 and summary["notices"]["in_table"] == 3
    assert summary["models"]["match_count"] == 3 and summary["models"]["in_table"] == 3
    assert summary["models"]["raw_same"] == 3
    assert summary["no_models"] == [{"pk": "2026000003/2026000003", "recheck_match_count": 0}]
    # 상세 1 + 공고별 3 + 주택형 없는 공고 재조회 1
    assert summary["calls"]["total"] == 5 and summary["calls"]["retries"] == 0
    assert summary["previous"] is None
    assert "matchCount" in capsys.readouterr().out


def test_second_run_adds_nothing(api, pg_engine, tmp_path):
    out = tmp_path / "last_run.json"
    run(api, pg_engine, out)
    first = json.loads(out.read_text(encoding="utf-8"))

    assert run(api, pg_engine, out) == 0
    second = json.loads(out.read_text(encoding="utf-8"))

    assert second["notices"]["inserted"] == 0 and second["models"]["inserted"] == 0
    assert second["notices"]["updated"] == 3 and second["models"]["updated"] == 3
    assert second["notices"]["rows_after"] == first["notices"]["rows_after"] == 3
    assert second["notices"]["pk_digest"] == first["notices"]["pk_digest"]
    assert second["models"]["pk_digest"] == first["models"]["pk_digest"]
    assert second["previous"]["notices_pk_digest"] == first["notices"]["pk_digest"]
    assert second["previous"]["notices_inserted"] == 3


def test_months_option_widens_the_window(api, pg_engine, tmp_path):
    out = tmp_path / "last_run.json"

    run(api, pg_engine, out, ["--months", "12"])

    assert json.loads(out.read_text(encoding="utf-8"))["notices"]["received"] == 4


def test_key_never_reaches_output_log_or_summary(api, pg_engine, tmp_path, capsys, caplog):
    out = tmp_path / "last_run.json"
    with caplog.at_level(logging.DEBUG):
        run(api, pg_engine, out)
    captured = capsys.readouterr()

    for blob in (captured.out, captured.err, caplog.text, out.read_text(encoding="utf-8")):
        assert KEY_DECODED not in blob and KEY_ENCODED not in blob


def test_empty_key_stops_before_any_request(api, pg_engine, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(notice.settings, "data_go_kr_key", "  ")

    assert run(api, pg_engine, tmp_path / "x.json") == 1

    assert "DATA_GO_KR_KEY가 비어 있다" in capsys.readouterr().err
    assert api.requests == []
    assert not (tmp_path / "x.json").exists()


def test_api_error_exits_1_without_writing_summary(api, pg_engine, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(notice.settings, "data_go_kr_key", "wrong%2Bkey")

    assert run(api, pg_engine, tmp_path / "x.json") == 1

    assert "HTTP 401" in capsys.readouterr().err
    assert not (tmp_path / "x.json").exists()
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notices")).scalar() == 0


def test_zero_notices_in_window_is_an_error_not_a_success(pg_engine, tmp_path, capsys):
    # 2026-10-23 새벽 실측: API가 HTTP 200에 totalCount 0·data []로 모든 operation을 비워 돌려줬다.
    # 0건 적재를 성공(exit 0)으로 치면 빈 테이블이 「성공」으로 남는다
    empty = FakeApi([make_notice(4, de="2026-01-05")])  # 기간 안에 공고가 없다
    out = tmp_path / "last_run.json"

    assert run(empty, pg_engine, out) == 1

    err = capsys.readouterr().err
    assert "matchCount 0" in err and "API 상태" in err
    assert not out.exists()


def test_all_models_empty_is_an_error_not_a_success(pg_engine, tmp_path, capsys):
    # 공고는 받았는데 주택형 호출이 전부 비어 있으면 상류가 비워 돌려준 것이다
    only_notices = FakeApi([make_notice(1), make_notice(2)])
    out = tmp_path / "last_run.json"

    assert run(only_notices, pg_engine, out) == 1

    assert "주택형이 없다" in capsys.readouterr().err
    assert not out.exists()
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notices")).scalar() == 0


def test_duplicate_pk_across_pages_is_a_mismatch_not_a_success(pg_engine, tmp_path, capsys):
    # matchCount는 맞는데 같은 PK가 두 번 오면 upsert가 한 행으로 합쳐 한 행이 모자란다
    n1 = make_notice(1)
    dup = FakeApi([n1, dict(n1)], [make_model(n1, "01")])
    out = tmp_path / "last_run.json"

    assert run(dup, pg_engine, out) == 1

    assert "적재 불일치: 공고 2행 받았는데 테이블에 1행" in capsys.readouterr().err
    assert json.loads(out.read_text(encoding="utf-8"))["notices"]["rows_after"] == 1


def test_recheck_that_finds_models_keeps_them(api, pg_engine, tmp_path):
    # 첫 주택형 호출이 일시적으로 비었다가 다시 물었을 때 받아지면 그 행을 적재한다
    notice3 = api.notices[2]
    seen = {"n": 0}
    base = api.handler

    def handler(request):
        p = request.url.params
        if (
            request.url.path.endswith("Mdl")
            and p.get("cond[HOUSE_MANAGE_NO::EQ]") == (notice3["HOUSE_MANAGE_NO"])
        ):
            seen["n"] += 1
            if seen["n"] == 1:
                return httpx.Response(200, json={"matchCount": 0, "data": [], "totalCount": 0})
            api.models.append(make_model(notice3, "01"))
        return base(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = tmp_path / "last_run.json"

    code = notice.main(
        ["--out", str(out)], client=client, engine=pg_engine, sleep=lambda _s: None, today=TODAY
    )

    assert code == 0
    summary = json.loads(out.read_text())
    assert summary["no_models"] == []
    assert summary["models"]["in_table"] == 4
