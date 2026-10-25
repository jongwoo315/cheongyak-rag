import copy
import json
from datetime import date

import pytest
from sqlalchemy import text

from cheongyak_rag.ingest import notice, notice_report
from tests.notice_fakes import KEY_DECODED, KEY_ENCODED, FakeApi, make_model, make_notice

TODAY = date(2026, 10, 22)


@pytest.fixture
def swagger():
    notice_keys = set(make_notice(1)) - {"BSNS_MBY_NM"} | {"ONLY_IN_SPEC"}
    model_keys = set(make_model(make_notice(1), "01"))
    prop = lambda keys: {"type": "object", "properties": {k: {"type": "string"} for k in keys}}  # noqa: E731
    return {
        "definitions": {
            "getAPTLttotPblancDetail_model": prop(notice_keys),
            "getAPTLttotPblancMdl_model": prop(model_keys),
        }
    }


@pytest.fixture
def run_file(pg_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(notice.settings, "data_go_kr_key", KEY_ENCODED)
    new1, new2, bare = make_notice(1), make_notice(2), make_notice(3, RCEPT_BGNDE="미정")
    api = FakeApi(
        [new1, new2, bare],
        [make_model(new1, "01"), make_model(new1, "02"), make_model(new2, "01")],
    )
    out = tmp_path / "last_run.json"
    for _ in range(2):  # 두 번 돌려야 재실행 비교가 생긴다
        notice.main(
            ["--out", str(out)],
            client=api.client(),
            engine=pg_engine,
            sleep=lambda _s: None,
            today=TODAY,
        )
    return out


def build(pg_engine, run_file, swagger, mutate=None):
    run = json.loads(run_file.read_text(encoding="utf-8"))
    if mutate:
        mutate(run)
    data = notice_report.gather(pg_engine, run, swagger)
    return notice_report.render(data)


def test_first_line_is_the_conclusion_and_sections_exist(pg_engine, run_file, swagger):
    text = build(pg_engine, run_file, swagger)

    first = text.splitlines()[0]
    assert "공고 3/3건" in first and "주택형 3/3건" in first
    assert "새로 들어간 행은 0건" in first
    assert "주택형 없는 공고는 1건" in first
    for heading in ("## 1. 지표", "## 2. 테이블 요약", "## 3. 표본 5건", "## 4. 목록"):
        assert heading in text


def test_clean_run_lands_in_the_pass_bands_with_plan_wording(pg_engine, run_file, swagger):
    text = build(pg_engine, run_file, swagger)

    assert "두 테이블 모두 0 → 통과" in text
    assert "100% 통과" in text
    assert "1~3건 공고번호 목록과 그 공고를 API로 다시 조회한 결과를 리포트에" in text
    assert "≤ 공고 수 + 10 정상" in text
    assert "판정 구간 없음 — 기록만" in text


def test_load_gap_bands(pg_engine, run_file, swagger):
    def small(run):
        run["notices"]["in_table"] -= 2
        run["notices"]["missing"] = ["a/a", "b/b"]

    def large(run):
        run["models"]["in_table"] -= 21
        run["models"]["missing"] = ["x/x/01"]

    def extra_only(run):
        run["notices"]["extra"] = ["z/z"]

    t_extra = build(pg_engine, run_file, swagger, extra_only)
    assert "1~3건(`notices`) 또는 1~20건(`notice_models`) 차이" in t_extra

    t_small = build(pg_engine, run_file, swagger, small)
    assert "1~3건(`notices`) 또는 1~20건(`notice_models`) 차이" in t_small
    assert "a/a" in t_small and "b/b" in t_small

    t_large = build(pg_engine, run_file, swagger, large)
    assert "그보다 크면 미완. 페이지 넘김이나 upsert를 고치고 다시 잰다" in t_large


def test_rerun_difference_makes_load_gap_incomplete(pg_engine, run_file, swagger):
    def changed(run):
        run["previous"]["notices_pk_digest"] = "다른 값"

    text = build(pg_engine, run_file, swagger, changed)

    assert "통과 기준 4가 깨졌다 → 미완" in text
    assert "달라졌다" in text.splitlines()[0]


def test_conversion_failures_are_listed_with_band(pg_engine, run_file, swagger):
    text = build(pg_engine, run_file, swagger)

    assert "1~10 값 목록을 리포트에" in text
    assert "RCEPT_BGNDE" in text and "미정" in text  # 목록에 값이 나온다


def test_no_models_bands(pg_engine, run_file, swagger):
    def none(run):
        run["no_models"] = []

    def many(run):
        run["no_models"] = [{"pk": f"{i}/{i}", "recheck_match_count": None} for i in range(4)]

    assert "0 정상" in build(pg_engine, run_file, swagger, none)
    assert "> 3건 원인을 찾는다(조건 파라미터가 틀렸는지)" in build(
        pg_engine, run_file, swagger, many
    )


def test_many_conversion_failures_hit_the_defect_band(pg_engine, run_file, swagger):
    def many(run):
        run["convert"]["failed"] = [
            {"table": "notices", "pk": f"{i}/{i}", "column": "c", "value": "v"} for i in range(11)
        ]

    assert "> 10 변환 규칙 결함" in build(pg_engine, run_file, swagger, many)


def test_call_bands(pg_engine, run_file, swagger):
    def retried(run):
        run["notices"]["received"] = 50
        run["calls"]["total"] = 61

    def broken(run):
        run["notices"]["received"] = 50
        run["calls"]["total"] = 101

    assert "그보다 크고 공고 수 × 2 이하 재시도 원인을 리포트에" in build(
        pg_engine, run_file, swagger, retried
    )
    assert "공고 수 × 2 초과 페이지 넘김·재시도 결함" in build(pg_engine, run_file, swagger, broken)


def test_spec_diff_lists_names_both_ways(pg_engine, run_file, swagger):
    text = build(pg_engine, run_file, swagger)

    assert "BSNS_MBY_NM" in text  # 응답에 있고 swagger에 없다
    assert "ONLY_IN_SPEC" in text  # swagger에 있고 응답에 없다


def test_table_summary_and_samples(pg_engine, run_file, swagger):
    text = build(pg_engine, run_file, swagger)

    summary = text.split("## 2.")[1].split("## 3.")[0]
    assert "2026-10-01" in summary and "경기" in summary
    samples = text.split("## 3.")[1].split("## 4.")[0]
    assert "단지 1" in samples and "084.3522A" in samples
    assert samples.count("단지 ") >= 3


def test_cli_writes_report_and_refuses_when_key_is_in_it(
    pg_engine, run_file, swagger, tmp_path, monkeypatch, capsys
):
    sw = tmp_path / "swagger.json"
    sw.write_text(json.dumps(swagger), encoding="utf-8")
    out = tmp_path / "report.md"
    argv = ["--run", str(run_file), "--swagger", str(sw), "--out", str(out)]

    assert notice_report.main(argv, engine=pg_engine) == 0
    text = out.read_text(encoding="utf-8")
    assert KEY_DECODED not in text and KEY_ENCODED not in text

    # 요약 JSON에 키가 섞여 들어갔다면 쓰지 않고 멈춘다
    run = json.loads(run_file.read_text(encoding="utf-8"))
    leaked = copy.deepcopy(run)
    leaked["no_models"][0]["note"] = KEY_DECODED
    run_file.write_text(json.dumps(leaked), encoding="utf-8")
    out.unlink()
    assert notice_report.main(argv, engine=pg_engine) == 1
    assert not out.exists()
    assert KEY_DECODED not in capsys.readouterr().err


def test_cli_refuses_a_run_summary_that_no_longer_matches_the_tables(
    pg_engine, run_file, swagger, tmp_path, capsys
):
    # 수집이 중간에 실패하면 last_run.json은 이전 실행의 것이다. 그 값으로 적재율을 쓰면 안 된다
    sw = tmp_path / "swagger.json"
    sw.write_text(json.dumps(swagger), encoding="utf-8")
    out = tmp_path / "report.md"
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM notices WHERE house_manage_no = '2026000003'"))

    code = notice_report.main(
        ["--run", str(run_file), "--swagger", str(sw), "--out", str(out)], engine=pg_engine
    )

    assert code == 1 and not out.exists()
    err = capsys.readouterr().err
    assert "notices 실행 요약 3행 ≠ DB 2행" in err


def test_cli_refuses_when_key_is_blank_because_the_leak_check_cannot_run(
    pg_engine, run_file, swagger, tmp_path, monkeypatch, capsys
):
    sw = tmp_path / "swagger.json"
    sw.write_text(json.dumps(swagger), encoding="utf-8")
    out = tmp_path / "report.md"
    monkeypatch.setattr(notice.settings, "data_go_kr_key", " \n")

    code = notice_report.main(
        ["--run", str(run_file), "--swagger", str(sw), "--out", str(out)], engine=pg_engine
    )

    assert code == 1 and not out.exists()
    assert "DATA_GO_KR_KEY가 비어 있다" in capsys.readouterr().err


def test_cli_leak_check_uses_the_stripped_key(pg_engine, run_file, swagger, tmp_path, monkeypatch):
    # .env 값에 공백이 붙어 있어도 실제로 요청에 쓰인 키(strip한 값)를 찾아야 한다
    sw = tmp_path / "swagger.json"
    sw.write_text(json.dumps(swagger), encoding="utf-8")
    out = tmp_path / "report.md"
    monkeypatch.setattr(notice.settings, "data_go_kr_key", f" {KEY_ENCODED}\n")
    leaked = json.loads(run_file.read_text(encoding="utf-8"))
    leaked["no_models"][0]["note"] = KEY_DECODED
    run_file.write_text(json.dumps(leaked), encoding="utf-8")

    code = notice_report.main(
        ["--run", str(run_file), "--swagger", str(sw), "--out", str(out)], engine=pg_engine
    )

    assert code == 1 and not out.exists()
