import json

import pytest

from cheongyak_rag.ingest import notice, notice_doc
from cheongyak_rag.ingest import notice_doc_report as rep
from tests.notice_fakes import make_notice

LH = "2026000409"  # 링크 없음 LH 10건 중 하나


def row(hm, result, **kw):
    base = notice_doc._row(hm, hm, f"https://x/getAtchmnfl.do?n={hm}", result=result)
    return base | kw


def make_rows():
    return [
        row("A1", "pdf", pages=3, text_chars=100, bytes=10, header_ext="pdf", magic_ext="pdf"),
        row("A2", "pdf", pages=2, text_chars=0, bytes=20, header_ext="pdf", magic_ext="pdf"),
        row(
            "A3",
            "pdf",
            pages=1,
            text_chars=5,
            bytes=30,
            header_ext="hwp",
            magic_ext="pdf",
            ext_mismatch=True,
            header_filename="공고.hwp",
        ),
        row("B1", "hwp", bytes=40, header_ext="hwp", magic_ext="hwp"),
        row("B2", "other", bytes=50, header_ext="xlsx", magic_ext="unknown", ext_mismatch=True),
        row("E1", "error", error="HTTP 503: 재시도 4회 뒤에도 실패"),
        notice_doc._row(
            LH, LH, None, result="no_link", note="다른 외부 링크: https://apply.lh.or.kr/"
        ),
        notice_doc._row("N9", "N9", None, result="no_link", note="다른 외부 링크 없음"),
    ]


def summary(**over):
    s = {
        "started_at": "2026-11-09T23:30:00+09:00",
        "ended_at": "2026-11-09T23:33:00+09:00",
        "elapsed_sec": 180.0,
        "limit": None,
        "notices": 8,
        "results": {"pdf": 3, "hwp": 1, "other": 1, "no_link": 2, "error": 1},
        "errors": 1,
        "with_link": 6,
        "link_rows": 8,
        "new_downloads": 0,
        "downloaded_bytes": 0,
        "error_notices": ["E1/E1"],
        "no_link_notices": [f"{LH}/{LH}", "N9/N9"],
    }
    return s | over


NAMES = {f"{hm}/{hm}": f"단지{hm}" for hm in ("A1", "A2", "A3", "B1", "B2", "E1", LH, "N9")}


def data(**over):
    d = {
        "run": summary(),
        "run1": summary(new_downloads=5, downloaded_bytes=150, elapsed_sec=240.0),
        "rows": make_rows(),
        "names": NAMES,
        "notes": None,
    }
    return d | over


def test_first_line_is_one_sentence_conclusion():
    first = rep.render(data()).splitlines()[0]
    assert first == (
        "공고문 링크가 있는 공고 6건 중 오류는 1건이다"
        "(PDF 3건 · 격리 2건[HWP 1·그 밖 1] · 링크 없음 2건)."
    )


def test_lists_name_the_notices():
    text = rep.render(data())
    assert "`E1/E1` 단지E1" in text and "HTTP 503" in text  # 오류
    assert "`B1/B1` 단지B1" in text and "`B2/B2` 단지B2" in text  # 격리
    assert f"`{LH}/{LH}` 단지{LH}" in text and "apply.lh.or.kr" in text  # 링크 없음
    assert "`A2/A2` 단지A2" in text  # 텍스트 없는 PDF
    assert "`A3/A3` 단지A3" in text and "공고.hwp" in text  # 확장자 어긋남


def test_result_table_and_rerun_table():
    text = rep.render(data())
    for value in notice_doc.RESULTS:
        assert f"| `{value}` |" in text
    assert "| 새 다운로드 | 5 | 0 |" in text
    assert "| 받은 바이트 | 150 | 0 |" in text


@pytest.mark.parametrize(
    ("errors", "band"),
    [(0, "통과"), (1, "1~3"), (3, "1~3"), (4, "미완")],
)
def test_error_band(errors, band):
    assert band in rep.error_band(errors)


@pytest.mark.parametrize(("outside", "band"), [(0, "통과"), (2, "1~3"), (5, "고치고")])
def test_no_link_outside_lh_band(outside, band):
    assert band in rep.no_link_band(outside)


def test_no_link_outside_lh_is_listed_with_note():
    text = rep.render(data())
    # LH 목록 밖 no_link(N9)는 따로 눈에 띄게 적는다
    assert "LH 10건 밖 링크 없음: 1건" in text and "`N9/N9`" in text


def test_rerun_failures_are_flagged():
    bad = data(
        run=summary(
            new_downloads=2, results={"pdf": 2, "hwp": 1, "other": 1, "no_link": 2, "error": 2}
        )
    )
    text = rep.render(bad)
    assert "새 다운로드가 0이 아니다" in text and "결과별 공고 수가 첫 실행과 다르다" in text


def test_notice_results_from_manifest_take_worst_row():
    rows = [
        row("Z", "pdf"),
        row("Z", "hwp"),
        row("Y", "pdf"),
        notice_doc._row("X", "X", None, result="no_link"),
    ]
    assert rep.notice_results(rows) == {"Z/Z": "hwp", "Y/Y": "pdf", "X/X": "no_link"}


def test_main_refuses_when_summary_and_manifest_disagree(pg_engine, tmp_path, capsys):
    notice.upsert(pg_engine, notice.NOTICES, [notice.to_notice_row(make_notice(1)).row])
    (tmp_path / "manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in make_rows()), encoding="utf-8"
    )
    run = summary(results={"pdf": 8, "hwp": 0, "other": 0, "no_link": 0, "error": 0})
    for name in ("last_run.json", "run1.json"):
        (tmp_path / name).write_text(json.dumps(run), encoding="utf-8")
    out = tmp_path / "report.md"

    code = rep.main(
        [
            "--run", str(tmp_path / "last_run.json"),
            "--run1", str(tmp_path / "run1.json"),
            "--manifest", str(tmp_path / "manifest.jsonl"),
            "--out", str(out),
        ],
        engine=pg_engine,
    )  # fmt: skip
    assert code == 1 and not out.exists()
    assert "맞지 않는다" in capsys.readouterr().err


def test_main_writes_report(pg_engine, tmp_path):
    names = [notice.to_notice_row(make_notice(n)).row for n in (1,)]
    notice.upsert(pg_engine, notice.NOTICES, names)
    rows = [
        row("2026000001", "pdf", pages=2, text_chars=9, bytes=7, header_ext="pdf", magic_ext="pdf")
    ]
    rows[0]["pblanc_no"] = "2026000001"
    (tmp_path / "manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    run = summary(
        notices=1,
        results={"pdf": 1, "hwp": 0, "other": 0, "no_link": 0, "error": 0},
        errors=0,
        with_link=1,
        error_notices=[],
        no_link_notices=[],
    )
    for name in ("last_run.json", "run1.json"):
        (tmp_path / name).write_text(json.dumps(run), encoding="utf-8")
    out = tmp_path / "report.md"

    code = rep.main(
        [
            "--run", str(tmp_path / "last_run.json"),
            "--run1", str(tmp_path / "run1.json"),
            "--manifest", str(tmp_path / "manifest.jsonl"),
            "--out", str(out),
        ],
        engine=pg_engine,
    )  # fmt: skip
    assert code == 0
    assert out.read_text(encoding="utf-8").startswith(
        "공고문 링크가 있는 공고 1건 중 오류는 0건이다"
    )
