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
                    {
                        "별표구분": "별표",
                        "별표번호": "0001",
                        "별표가지번호": "00",
                        "별표제목": "가점제",
                    },
                    {
                        "별표구분": "서식",
                        "별표번호": "0001",
                        "별표가지번호": "00",
                        "별표제목": "신청서",
                    },
                    {
                        "별표구분": "서식",
                        "별표번호": "0003",
                        "별표가지번호": "02",
                        "별표제목": "접수증",
                    },
                    {
                        "별표구분": "별표",
                        "별표번호": "0003",
                        "별표제목": "삭제 &lt;2017. 11. 24.&gt;",
                    },
                ]
            },
            "부칙": {"부칙단위": [{"부칙키": "a"}, {"부칙키": "b"}, {"부칙키": "c"}]},
        }
    }

    s = law_report.appendix_summary(law)

    # 같은 번호가 별표와 서식에 따로 있다. 구분을 붙여야 안 겹친다
    assert s.table_titles == [
        "별표 1 가점제",
        "서식 1 신청서",
        "서식 3의2 접수증",
        "별표 3 삭제 <2017. 11. 24.>",
    ]
    assert (s.table_count, s.form_count) == (2, 2)
    assert s.supplement_count == 3


def test_appendix_summary_accepts_single_dict_and_missing_keys():
    law = {
        "법령": {
            "별표": {"별표단위": {"별표구분": "별표", "별표번호": "0003", "별표제목": "하나뿐"}}
        }
    }

    s = law_report.appendix_summary(law)

    assert s.table_titles == ["별표 3 하나뿐"]
    assert s.supplement_count == 0


# ── 실패 징후 4: FAQ 인용 커버 ────────────────────────────────────────────


def _faq(q_no, *cited, answer=""):
    return {
        "q_no": q_no,
        "as_of": "2024-05-29",
        "cited_articles": list(cited),
        "question": "",
        "answer": answer,
    }


def test_faq_cross_covers_a_pair_only_when_every_cited_article_exists(rows):
    faq = [
        _faq(1, "제1조"),  # 있다 → 커버
        _faq(2, "제1조", "제999조"),  # 하나라도 없으면 커버 안 됨
        _faq(3, "제999조"),  # 없다
        _faq(4),  # 인용 없음 → 분모에 안 넣는다
    ]

    cross = law_report.faq_cross(rows, faq)

    assert cross.pair_count == 4
    assert cross.cited_pairs == 3
    assert cross.covered_pairs == 1
    assert cross.uncovered_pairs == 2
    assert [(u.q_no, u.label) for u in cross.uncovered] == [(2, "제999조"), (3, "제999조")]


def test_faq_cross_amendment_date_does_not_decide_coverage(rows):
    # 제3조는 FAQ 기준일(2024-05-29) 뒤인 2026-06-15에 개정됐지만 현행에 있다 → 커버
    cross = law_report.faq_cross(rows, [_faq(1, "제3조")])

    assert cross.covered_pairs == 1
    assert cross.uncovered == []
    # 개정은 참고 줄로만 남는다
    assert cross.covered_pairs_amended == 1
    assert cross.latest_amendment["제3조"] == "2026-06-15"


def test_faq_cross_amended_means_strictly_after_the_faq_date(rows):
    for r in rows:
        r["amendments"] = ["2024-05-29"]  # 같은 날은 FAQ에 이미 반영된 것이다

    cross = law_report.faq_cross(rows, [_faq(1, "제1조")])

    assert cross.covered_pairs == 1
    assert cross.covered_pairs_amended == 0


def test_faq_cross_folds_clause_and_item_citations_into_the_article(rows):
    faq = [
        _faq(1, "제3조제1항제2호나목"),  # 조 단위로 접어 제3조로 판정
        _faq(2, "제7조의2제1항", "제3조제2항"),  # 가지 조문은 따로 센다
        _faq(3, "제7조제1항"),  # 제7조는 없다 (제7조의2는 다른 조)
    ]

    cross = law_report.faq_cross(rows, faq)

    assert cross.covered_pairs == 2
    assert [(u.q_no, u.label) for u in cross.uncovered] == [(3, "제7조")]
    assert cross.cited_labels == 3  # 제3조 · 제7조의2 · 제7조


def test_faq_cross_keeps_the_text_before_the_missing_article_to_show_the_law_name(rows):
    answer = "참고로 조세특례제한법 제87조에 따르면 …"
    faq = [_faq(1, "제87조", answer=answer)]

    cross = law_report.faq_cross(rows, faq)

    assert cross.uncovered[0].before == "참고로 조세특례제한법"  # 20자 이내, 조 바로 앞까지


def test_faq_cross_context_does_not_match_inside_a_longer_article_number(rows):
    # 제7조를 찾을 때 제7조의2나 제17조에 걸리면 엉뚱한 법령 이름이 붙는다
    answer = "「A법」 제7조의2와 「B법」 제17조 그리고 「C법」 제7조"
    cross = law_report.faq_cross(rows, [_faq(1, "제7조", answer=answer)])

    assert cross.uncovered[0].before.endswith("「C법」")


def test_faq_cross_context_is_empty_when_the_text_does_not_contain_the_article(rows):
    cross = law_report.faq_cross(rows, [_faq(1, "제999조", answer="본문에 없다")])

    assert cross.uncovered[0].before == ""


def test_faq_cross_cutoff_is_the_latest_faq_date(rows):
    assert law_report.faq_cross(rows, [_faq(1, "제1조")]).cutoff == "2024-05-29"
    assert law_report.faq_cross(rows, []).cutoff == ""


# ── 위치 검증 (리뷰 지적: 텍스트만 맞고 자리가 틀린 경우) ────────────────────


def test_item_moved_to_another_article_is_reported(law_json, rows):
    item = _row(rows, "제3조")["paragraphs"][1]["items"].pop(1)  # 6의2 호
    _row(rows, "제7조의2")["paragraphs"][0]["items"].append(item)

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert [f.where for f in check.missing] == ["제3조"]
    assert [f.where for f in check.extra + check.duplicated] == ["제7조의2"]


def test_item_moved_to_another_paragraph_of_same_article_is_reported(law_json, rows):
    # 텍스트는 조문 단위로 세므로 같은 조문 안의 항 사이 이동은 텍스트 대조로는 안 보인다
    paragraphs = _row(rows, "제3조")["paragraphs"]
    paragraphs[0]["items"].append(paragraphs[1]["items"].pop(0))

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert {f.where for f in check.bad_meta} == {"제3조"}
    assert any("호번호" in f.text for f in check.bad_meta)


def test_wrong_chapter_or_section_attribution_is_reported(law_json, rows):
    _row(rows, "제7조의2")["chapter"] = "제1장 총칙"

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert [f.where for f in check.misplaced] == ["제7조의2"]


def test_expected_chapter_section_follows_source_order(law_json):
    assert law_report.source_headings(law_json)["제7조의2"] == (
        "제2장 입주자저축",
        "제1절 입주자저축의 가입 및 사용",
    )
    assert law_report.source_headings(law_json)["제1조"] == ("제1장 총칙", None)
    assert law_report.source_headings(law_json)["제29조"] == (
        "제4장 주택공급 방법",
        "제2절 일반공급",
    )


# ── amendments·삭제 검증 (리뷰 지적: FAQ (b)가 amendments에 전적으로 기대는데 검증이 없었다) ──


def test_lost_amendments_are_reported(law_json, rows):
    _row(rows, "제3조")["amendments"] = []

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert [f.where for f in check.bad_meta] == ["제3조"]
    assert "amendments" in check.bad_meta[0].text


def test_wrong_deleted_flag_is_reported(law_json, rows):
    _row(rows, "제29조")["deleted"] = False

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert "deleted" in check.bad_meta[0].text


def test_clean_rows_have_no_misplaced_or_bad_meta(law_json, rows):
    check = law_report.check(law_json, rows)

    assert check.misplaced == [] and check.bad_meta == []


def test_faq_cross_counts_deleted_article_as_not_current(rows):
    # 제29조는 삭제됐다. 행은 남아 있지만 현행 조문이 아니다
    cross = law_report.faq_cross(rows, [_faq(1, "제29조제1항"), _faq(2, "제1조")])

    assert cross.covered_pairs == 1
    assert [(u.q_no, u.label) for u in cross.uncovered] == [(1, "제29조")]
    assert cross.current_labels == 1  # 제1조만. 삭제된 제29조는 인용돼도 현행에 없다


def test_response_with_no_articles_is_not_ok(law_json):
    empty = copy.deepcopy(law_json)
    empty["법령"]["조문"]["조문단위"] = []

    check = law_report.check(empty, [])

    assert check.source_counts["조문"] == 0
    assert not check.ok  # 0 == 0이라 개수가 일치해도 빈 응답은 통과가 아니다


# ── 식별 필드·항 단위 개정 날짜 (리뷰 지적: 파서가 낸 값인데 원본과 안 맞댔다) ──


def _para_with_amendment(rows):
    return next(p for r in rows for p in r["paragraphs"] if p["amendments"])


@pytest.mark.parametrize(
    "tamper, key",
    [
        (lambda rows: _row(rows, "제3조").update(article_no=9), "article_no"),
        (lambda rows: _row(rows, "제7조의2").update(branch_no=0), "branch_no"),
        (lambda rows: _row(rows, "제3조").update(article_effective_date="1999-01-01"), "시행일"),
        (lambda rows: _row(rows, "제3조").update(law_id="ZZ"), "law_id"),
        (lambda rows: _row(rows, "제3조").update(effective_date="1999-01-01"), "effective_date"),
        (lambda rows: _para_with_amendment(rows).update(amendments=["1999-01-01"]), "항 개정"),
    ],
)
def test_identity_and_paragraph_amendment_mismatch_is_reported(law_json, rows, tamper, key):
    tamper(rows)

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert any(key in f.text for f in check.bad_meta)


@pytest.mark.parametrize(
    "tamper, key",
    [
        (lambda rows: _row(rows, "제3조").update(title="다른 제목"), "title"),
        (lambda rows: _row(rows, "제3조")["paragraphs"][1].update(no="③"), "항번호"),
        (lambda rows: _row(rows, "제3조")["paragraphs"][1]["items"][1].update(no="6"), "호번호"),
        (
            lambda rows: _row(rows, "제3조")["paragraphs"][1]["items"][2]["subitems"][0].update(
                no="하"
            ),
            "목번호",
        ),
    ],
)
def test_wrong_title_or_number_is_reported_even_when_text_is_the_same(law_json, rows, tamper, key):
    tamper(rows)

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert any(key in f.text for f in check.bad_meta)


def test_wrong_section_alone_is_reported(law_json, rows):
    _row(rows, "제29조")["section"] = "제1절 다른 절"  # 장은 맞고 절만 틀리다

    check = law_report.check(law_json, rows)

    assert not check.ok
    assert [f.where for f in check.misplaced] == ["제29조"]


# ── 리포트 본문 (PR 게이트가 읽는 줄) ─────────────────────────────────────


def _report(law_json, rows, cross=None):
    current = {"mst": "286965", "law_id": "008243", "effective_date": "2026-06-15"}
    return law_report.format_report(
        current, law_report.check(law_json, rows), law_report.appendix_summary(law_json), cross
    )


def test_report_shows_each_level_count_and_marks_mismatch(law_json, rows):
    _row(rows, "제3조")["paragraphs"].pop(0)  # 항 5 → 4

    out = _report(law_json, rows)

    assert "항 5 → 4 불일치" in out
    assert "조문 5 → 5 일치" in out
    assert "누락 1" in out


def test_report_says_when_counts_differ_from_the_reference_values(law_json, rows):
    out = _report(law_json, rows)  # 픽스처는 5개짜리라 현행 기준값(90·20·…)과 다르다

    assert "기준값(시행 2026-06-15)과 다르다" in out
    assert "과 같다" not in out


def test_report_says_when_counts_equal_the_reference_values(law_json, rows, monkeypatch):
    monkeypatch.setattr(law_report, "REFERENCE_COUNTS", law_report.source_counts(law_json))

    assert "기준값(시행 2026-06-15)과 같다" in _report(law_json, rows)


def test_report_shows_faq_cross_values(law_json, rows):
    cross = law_report.faq_cross(
        rows, [_faq(1, "제3조제1항"), _faq(2, "제999조", answer="「다른법」 제999조")]
    )

    out = _report(law_json, rows, cross)

    assert "인용 있는 쌍 2 · 커버 1 (50%) · 커버 안 됨 1" in out
    assert "인용된 조 2종 중 현행에 있는 것 1종" in out
    assert "Q2 제999조: '「다른법」'" in out
    assert "참고 (커버 판정에 안 씀)" in out
    assert "인용한 쌍 1 (조 1종: 제3조(2026-06-15))" in out
    assert "다른 법령 인용도 분모에서 빼지 않았다" in out


def test_appendix_counts_tables_and_forms_separately():
    unit = {"별표번호": "0001", "별표제목": "t"}
    law = {
        "법령": {
            "별표": {
                "별표단위": [
                    {**unit, "별표구분": "별표"},
                    {**unit, "별표구분": "별표"},
                    {**unit, "별표구분": "별표"},
                    {**unit, "별표구분": "서식"},
                ]
            }
        }
    }

    s = law_report.appendix_summary(law)

    assert (s.table_count, s.form_count) == (3, 1)  # 서로 다른 값이라 둘이 바뀌면 잡힌다


def test_whole_article_dropped_or_inserted_twice_is_reported(law_json, rows):
    # 파서가 가지 조문이나 삭제 조문을 통째로 건너뛰는 것이 가장 있을 법한 실패다
    dropped = [r for r in rows if r["label"] != "제7조의2"]
    twice = rows + [copy.deepcopy(_row(rows, "제29조"))]

    gone = law_report.check(law_json, dropped)
    dup = law_report.check(law_json, twice)

    # 제7조의2만 달고 있던 장·절 제목도 같이 사라져 `장절`이 함께 잡힌다
    assert not gone.ok and {f.where for f in gone.missing} == {"제7조의2", "장절"}
    assert gone.source_counts["조문"] == gone.output_counts["조문"] + 1
    assert not dup.ok and {f.where for f in dup.duplicated} == {"제29조"}
