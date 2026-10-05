import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from cheongyak_rag.ingest import law_report
from cheongyak_rag.ingest.law import parse_articles

FIXTURE = Path(__file__).parent / "fixtures" / "law_sample.json"


@pytest.fixture(scope="module")
def law_json():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def rows(law_json):
    return [asdict(a) for a in parse_articles(law_json)]


def _row(rows, label):
    return next(r for r in rows if r["label"] == label)


def test_report_module_does_not_use_the_parser():
    # 같은 코드로 세면 같은 버그가 양쪽에 들어간다
    src = Path(law_report.__file__).read_text(encoding="utf-8")

    assert "parse_articles" not in src
    assert "from .law " not in src
    assert "import law\n" not in src


def test_clean_output_has_no_missing_and_no_duplicates(law_json, rows):
    check = law_report.check(law_json, rows)

    assert check.missing == []
    assert check.duplicated == []
    assert check.source_counts == check.output_counts
    assert check.ok


def test_counts_of_fixture(law_json, rows):
    check = law_report.check(law_json, rows)

    assert check.source_counts == {"조문": 5, "장절": 5, "항": 5, "호": 20, "목": 10}
    assert law_report.output_counts(rows) == check.source_counts


def test_dropped_paragraph_is_reported_as_missing_with_article_and_text(law_json, rows):
    dropped = _row(rows, "제3조")["paragraphs"].pop(0)

    check = law_report.check(law_json, rows)

    assert [(f.where, f.text[:12]) for f in check.missing] == [("제3조", "① 이 규칙은 사업주체")]
    assert check.duplicated == []
    assert check.source_counts["항"] == check.output_counts["항"] + 1
    assert not check.ok
    assert dropped["no"] == "①"


def test_paragraph_inserted_twice_is_reported_as_duplicate(law_json, rows):
    paragraphs = _row(rows, "제3조")["paragraphs"]
    paragraphs.append(copy.deepcopy(paragraphs[0]))

    check = law_report.check(law_json, rows)

    assert check.missing == []
    assert [(f.where, f.text[:12]) for f in check.duplicated] == [("제3조", "① 이 규칙은 사업주체")]
    assert not check.ok


def test_dropped_subitem_is_missing_and_counted(law_json, rows):
    item = _row(rows, "제3조")["paragraphs"][1]["items"][2]
    item["subitems"].pop(0)

    check = law_report.check(law_json, rows)

    assert len(check.missing) == 1
    assert check.missing[0].text.startswith("가. 공공사업의 시행에 따른 이주대책용")
    assert check.source_counts["목"] == check.output_counts["목"] + 1


def test_dropped_chapter_heading_is_missing(law_json, rows):
    for r in rows:
        if r["chapter"] == "제4장 주택공급 방법":
            r["chapter"] = None

    check = law_report.check(law_json, rows)

    assert [f.text for f in check.missing] == ["제4장 주택공급 방법"]
    assert check.source_counts["장절"] == check.output_counts["장절"] + 1


def test_whitespace_differences_are_not_reported(law_json, rows):
    sub = _row(rows, "제3조")["paragraphs"][1]["items"][2]["subitems"][0]
    sub["text"] = sub["text"].replace("\n", "   ")  # 줄바꿈이 공백으로 바뀌어도 같은 내용이다

    assert law_report.check(law_json, rows).ok


def test_changed_text_is_both_missing_and_unexpected(law_json, rows):
    _row(rows, "제1조")["text"] += " 덧붙임"

    check = law_report.check(law_json, rows)

    assert len(check.missing) == 1
    assert len(check.duplicated) == 0
    assert len(check.extra) == 1
    assert not check.ok


def test_source_fields_flatten_nested_list_text(law_json):
    fields = law_report.source_fields(law_json)
    sub = next(f for f in fields if f.text.startswith("가. 공공사업의 시행에 따른 이주대책용"))

    assert "1) 공공사업의 시행자가 직접 건설하는 주택" in sub.text
    assert "\n" not in sub.text
    assert sub.where == "제3조"
