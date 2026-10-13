import re
from pathlib import Path

import pytest

from cheongyak_rag.retrieval.corpus import LAW_PATH, Article, load_articles


@pytest.fixture(scope="module")
def articles() -> dict[str, Article]:
    # 조용한 skip 금지 — 데이터가 없으면 실패시킨다
    if not LAW_PATH.exists():
        pytest.fail(f"법령 JSONL 없음: {LAW_PATH}")
    return {a.label: a for a in load_articles(LAW_PATH)}


def test_88_current_articles_deleted_excluded(articles):
    assert len(articles) == 88
    assert "제29조" not in articles and "제47조의2" not in articles


def test_branch_article_label(articles):
    assert articles["제7조의2"].title
    assert articles["제24조의3"].text.startswith("제24조의3(")


def test_head_line_then_body(articles):
    head, _, rest = articles["제1조"].text.partition("\n")
    assert head == "제1조(목적)"
    assert rest.startswith("이 규칙은")


def test_article_without_paragraphs_keeps_body(articles):
    # 제7조는 항이 없고 본문이 조 문장에 바로 있다
    assert len(articles["제7조"].text.split("\n", 1)[1]) > 20


def test_items_and_subitems_included(articles):
    t = articles["제2조"].text
    assert '"공급"이란' in t  # 호
    assert "자녀를 양육하는 경우" in t  # 목


def test_paragraphs_included_in_order(articles):
    t = articles["제23조"].text
    assert t.index("① 사업주체") < t.index("② 주택의 공급신청")


def test_amendment_marks_stripped(articles):
    # `<개정 2016.8.12>` 날짜 목록이 BM25에 숫자 토큰으로 들어가는 것을 막는다
    assert all("<개정" not in a.text and "<신설" not in a.text for a in articles.values())
    # `삭제<2024.12.18>` 같은 날짜만 든 표시와 `<img>` 태그도 남지 않는다
    assert not any(re.search(r"<\d{4}\.|<img", a.text) for a in articles.values())


def test_load_from_given_path(tmp_path: Path):
    p = tmp_path / "law.jsonl"
    p.write_text(
        '{"label":"제1조","title":"가","deleted":false,"text":"제1조(가) 본문 <개정 2020.1.1>",'
        '"paragraphs":[]}\n'
        '{"label":"제2조","title":"나","deleted":true,"text":"제2조 삭제","paragraphs":[]}\n',
        encoding="utf-8",
    )
    assert load_articles(p) == [Article("제1조", "가", "제1조(가)\n본문")]
