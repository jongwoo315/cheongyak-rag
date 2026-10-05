import json
from pathlib import Path

import pytest

from cheongyak_rag.ingest.law import extract_amendments, parse_articles

FIXTURE = Path(__file__).parent / "fixtures" / "law_sample.json"


@pytest.fixture(scope="module")
def articles():
    law_json = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {a.label: a for a in parse_articles(law_json, mst="286965")}


def _law(*units) -> dict:
    """합성 응답. 조문단위 몇 개만 든 최소 형태."""
    info = {"법령명_한글": "주택공급에 관한 규칙", "법령ID": "008243", "시행일자": "20260615"}
    return {"법령": {"기본정보": info, "조문": {"조문단위": list(units)}}}


def _article(no="1", **extra) -> dict:
    return {
        "조문번호": no,
        "조문여부": "조문",
        "조문시행일자": "20260615",
        "조문내용": f"제{no}조(시험) 본문",
        "조문제목": "시험",
        **extra,
    }


def _heading(text: str) -> dict:
    return {"조문번호": "1", "조문여부": "전문", "조문시행일자": "20260615", "조문내용": text}


# ── 픽스처로 확인하는 고정값 ──────────────────────────────────────────────


def test_fixture_yields_only_articles_not_headings(articles):
    assert list(articles) == ["제1조", "제2조", "제3조", "제7조의2", "제29조"]


def test_article_without_paragraphs_keeps_body_in_text(articles):
    a = articles["제1조"]

    assert a.paragraphs == []
    assert a.text.startswith("제1조(목적) 이 규칙은 「주택법」")
    assert a.title == "목적"
    assert (a.law_id, a.mst, a.effective_date) == ("008243", "286965", "2026-06-15")
    assert a.article_effective_date == "2026-06-15"
    assert (a.article_no, a.branch_no, a.deleted) == (1, 0, False)


def test_amendment_dates_are_extracted_but_text_keeps_the_tag(articles):
    a = articles["제1조"]

    assert a.amendments == ["2016-08-12", "2019-08-16", "2019-11-01", "2019-12-06", "2021-02-02"]
    assert "<개정 2016.8.12, 2019.8.16, 2019.11.1, 2019.12.6, 2021.2.2>" in a.text


def test_paragraph_as_dict_without_number_becomes_one_paragraph(articles):
    a = articles["제2조"]

    assert a.text.startswith("제2조(정의) 이 규칙에서 사용하는 용어의 뜻은 다음과 같다.")
    assert len(a.paragraphs) == 1
    p = a.paragraphs[0]
    assert (p.no, p.text, p.amendments) == ("", "", [])
    assert [i.no for i in p.items] == ["1", "2의2", "3"]
    assert [s.no for s in p.items[1].subitems] == ["가", "나"]
    assert p.items[1].text.startswith('2의2. "성년자"란')


def test_paragraph_list_with_items_and_subitems(articles):
    a = articles["제3조"]

    assert a.text == "제3조(적용대상)"
    assert [p.no for p in a.paragraphs] == ["①", "②"]
    first, second = a.paragraphs
    assert first.text.startswith("① 이 규칙은 사업주체")
    assert first.amendments == ["2016-08-12"]
    assert first.items == []
    assert len(second.amendments) == 7
    assert [i.no for i in second.items] == ["1", "6의2", "8"]
    assert [s.no for s in second.items[0].subitems] == ["가", "나"]


def test_subitem_text_given_as_list_of_lines_is_joined_with_newlines(articles):
    sub = articles["제3조"].paragraphs[1].items[2].subitems[0]

    assert sub.no == "가"
    lines = sub.text.split("\n")
    assert lines[0] == "가. 공공사업의 시행에 따른 이주대책용으로 공급하는 다음의 주택"
    assert lines[1] == "1) 공공사업의 시행자가 직접 건설하는 주택"
    assert len(lines) == 5


def test_article_amendments_are_union_of_all_levels_sorted(articles):
    a = articles["제3조"]

    assert a.amendments == sorted(set(a.amendments))
    assert "2016-08-12" in a.amendments  # ① 항
    assert "2026-06-15" in a.amendments  # ② 항


def test_branch_article_label_and_chapter_section(articles):
    a = articles["제7조의2"]

    assert (a.article_no, a.branch_no, a.label) == (7, 2, "제7조의2")
    assert a.chapter == "제2장 입주자저축"
    assert a.section == "제1절 입주자저축의 가입 및 사용"
    assert articles["제1조"].chapter == "제1장 총칙"
    assert articles["제1조"].section is None


def test_deleted_article(articles):
    a = articles["제29조"]

    assert a.deleted is True
    assert a.title is None
    assert a.paragraphs == []
    assert a.text == "제29조 삭제 <2016.12.30>"
    assert a.amendments == ["2016-12-30"]
    assert (a.chapter, a.section) == ("제4장 주택공급 방법", "제2절 일반공급")


# ── 모양이 달라도 같은 결과 ───────────────────────────────────────────────


def _items(a):
    return [
        (p.no, p.text, [(i.no, i.text, [(s.no, s.text) for s in i.subitems]) for i in p.items])
        for p in a.paragraphs
    ]


def test_paragraph_item_subitem_shapes_list_dict_and_missing_give_same_result():
    mok = {"목번호": "가.", "목내용": "가. 목"}
    ho = {"호번호": "1.", "호내용": "1. 호", "목": [mok]}
    hang = {"항번호": "①", "항내용": "① 항", "호": [ho]}
    as_lists = _article(항=[{**hang, "호": [{**ho, "목": [mok]}]}])
    as_dicts = _article(항={**hang, "호": {**ho, "목": mok}})

    a, b = (parse_articles(_law(x))[0] for x in (as_lists, as_dicts))

    assert _items(a) == _items(b) == [("①", "① 항", [("1", "1. 호", [("가", "가. 목")])])]


def test_missing_children_are_empty_lists():
    hang_only = _article(항=[{"항번호": "①", "항내용": "① 항"}])

    p = parse_articles(_law(hang_only))[0].paragraphs[0]

    assert p.items == []


def test_text_given_as_string_list_or_nested_list_gives_same_text():
    def sub_text(value):
        hang = {
            "항번호": "①",
            "항내용": "① 항",
            "호": [{"호번호": "1.", "호내용": "1. 호", "목": [{"목번호": "가.", "목내용": value}]}],
        }
        return parse_articles(_law(_article(항=[hang])))[0].paragraphs[0].items[0].subitems[0].text

    assert sub_text("가. a\n1) b") == sub_text(["가. a", "1) b"]) == sub_text([["가. a", "1) b"]])


# ── 장·절 ─────────────────────────────────────────────────────────────────


def test_new_chapter_resets_section():
    law = _law(
        _heading("            제1장 총칙"),
        _heading("                  제1절 가"),
        _article("1"),
        _heading("            제2장 나"),
        _article("2"),
        _heading("              제2절의2 다 <신설 2021.11.16>"),
        _article("3"),
    )

    rows = {a.label: (a.chapter, a.section) for a in parse_articles(law)}

    assert rows == {
        "제1조": ("제1장 총칙", "제1절 가"),
        "제2조": ("제2장 나", None),
        "제3조": ("제2장 나", "제2절의2 다 <신설 2021.11.16>"),
    }


def test_article_before_any_chapter_has_none():
    a = parse_articles(_law(_article("1")))[0]

    assert (a.chapter, a.section) == (None, None)


def test_unknown_heading_kind_raises_instead_of_guessing():
    with pytest.raises(ValueError, match="제1편"):
        parse_articles(_law(_heading("제1편 총칙"), _article("1")))


# ── 개정 표시 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "dates"),
    [
        ("본문 <개정 2016.5.19, 2019.8.16>", ["2016-05-19", "2019-08-16"]),
        ("본문 <신설 2021.11.16>", ["2021-11-16"]),
        ("&lt;개정 2024. 12. 18.&gt; 와 <개정 2024. 12. 18.>", ["2024-12-18"]),
        ("본문 <2018. 12. 11.>", ["2018-12-11"]),
        ("제29조 삭제 <2016.12.30>", ["2016-12-30"]),
        ("본문 <개정 2016.8.12> 중간 <개정 2017.1.2>", ["2016-08-12", "2017-01-02"]),
        ("개정 표시 없음", []),
        ('<img src="http://x/y?flSeq=1" alt="a" >표</img>', []),
    ],
)
def test_extract_amendments(text, dates):
    assert extract_amendments(text) == dates
