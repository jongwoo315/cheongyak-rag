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


# ── 별표·부칙 요약 ────────────────────────────────────────────────────────


def test_appendix_summary_counts_and_titles():
    law = {
        "법령": {
            "별표": {
                "별표단위": [
                    {"별표번호": "0001", "별표가지번호": "00", "별표제목": "가점제 적용기준"},
                    {"별표번호": "0001", "별표가지번호": "02", "별표제목": "추가 기준"},
                ]
            },
            "부칙": {"부칙단위": [{"부칙키": "a"}, {"부칙키": "b"}, {"부칙키": "c"}]},
        }
    }

    s = law_report.appendix_summary(law)

    assert s.table_titles == ["별표 1 가점제 적용기준", "별표 1의2 추가 기준"]
    assert s.supplement_count == 3


def test_appendix_summary_accepts_single_dict_and_missing_keys():
    law = {"법령": {"별표": {"별표단위": {"별표번호": "0003", "별표제목": "하나뿐"}}}}

    s = law_report.appendix_summary(law)

    assert s.table_titles == ["별표 3 하나뿐"]
    assert s.supplement_count == 0


# ── 실패 징후 3: FAQ 인용과 현행 법령 대조 ────────────────────────────────


def _faq(q_no, *cited):
    return {"q_no": q_no, "as_of": "2024-05-29", "cited_articles": list(cited)}


def test_faq_cross_counts_pairs_citing_missing_and_amended_articles(rows):
    faq = [
        _faq(1, "제1조제1항"),  # 현행에 있고 2021년까지만 개정
        _faq(2, "제3조제1항", "제3조제2항"),  # 같은 조를 두 번 인용해도 쌍은 한 번, 개정 2026
        _faq(3, "제999조"),  # 현행에 없다
        _faq(4, "제7조의2제1항", "제999조의2"),  # 가지 조문 + 현행에 없는 가지 조문
        _faq(5),  # 인용 없음
    ]

    cross = law_report.faq_cross(rows, faq)

    assert cross.pair_count == 5
    assert cross.cutoff == "2024-05-29"
    assert cross.pairs_citing_missing == 2
    assert cross.missing_labels == ["제999조", "제999조의2"]
    assert cross.pairs_citing_amended == 2  # Q2(제3조 2026-06-15), Q4(제7조의2 2024-09-30)
    assert "제3조" in cross.amended_labels


def test_faq_cross_amended_means_strictly_after_the_faq_date(rows):
    for r in rows:
        r["amendments"] = ["2024-05-29"]  # 같은 날은 FAQ에 이미 반영된 것이다

    cross = law_report.faq_cross(rows, [_faq(1, "제1조")])

    assert cross.pairs_citing_amended == 0
    assert cross.amended_labels == []
