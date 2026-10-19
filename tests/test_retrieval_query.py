import json

from cheongyak_rag.retrieval import query as q
from tests.fakes import FakeEmbedder


def _row(label, title, rest="", paragraphs=()):
    head = f"{label}({title})"
    return {
        "label": label,
        "title": title,
        "deleted": False,
        "text": f"{head} {rest}".strip(),
        "paragraphs": list(paragraphs),
    }


def _item(no, text):
    return {"no": no, "text": text, "subitems": []}


LAW = [
    _row("제1조", "목적", "주택 공급 목적을 정한다."),
    _row(
        "제2조",
        "정의",
        "용어의 뜻은 다음과 같다.",
        [
            {
                "no": "",
                "text": "",
                "items": [
                    _item("1", "1. 공급이란 분양 또는 임대하는 것이다."),
                    _item("2", "2. 무주택세대구성원이란 세대원 전원이 무주택인 사람이다."),
                ],
            }
        ],
    ),
    _row("제3조", "자격", "청약 자격은 나이와 소득으로 정한다."),
]
FAQ = [
    {
        "q_no": 1,
        "major": "Ⅰ",
        "middle": "",
        "minor": "",
        "question": "무주택세대구성원이란?",
        "answer": "세대원 전원이 무주택인 세대",
    },
    {
        "q_no": 2,
        "major": "Ⅰ",
        "middle": "",
        "minor": "",
        "question": "청약 자격은?",
        "answer": "나이와 소득 기준",
    },
    {
        "q_no": 3,
        "major": "Ⅰ",
        "middle": "",
        "minor": "",
        "question": "공급 목적은?",
        "answer": "주택 공급",
    },
    {
        "q_no": 4,
        "major": "Ⅰ",
        "middle": "",
        "minor": "",
        "question": "무주택 세대 요건은?",
        "answer": "전원 무주택",
    },
]


def _index(candidate="item"):
    return q.Index(candidate, FakeEmbedder(), law_rows=LAW, faq_rows=FAQ)


def test_search_returns_law_by_article_without_duplicates():
    res = _index().search("무주택세대구성원 정의", k=5)
    labels = [c.label for c in res["law"]]
    assert len(labels) == len(set(labels)) == 3
    assert res["law"][0].label == "제2조"


def test_search_returns_best_chunk_of_the_article_not_whole_article():
    res = _index("item").search("무주택세대구성원 정의", k=5)
    assert res["law"][0].path == "제2조제2호"


def test_search_respects_k_and_faq_k():
    res = _index().search("자격", k=2, faq_k=3)
    assert len(res["law"]) == 2
    assert len(res["faq"]) == 3
    assert all(c.source == "faq" for c in res["faq"])


def test_search_can_exclude_faq_pair_with_same_question():
    res = _index().search("무주택세대구성원이란?", faq_k=3, exclude_same_question=True)
    assert 1 not in [c.meta["q_no"] for c in res["faq"]]


def test_search_keeps_self_pair_by_default():
    res = _index().search("무주택세대구성원이란?", faq_k=3)
    assert res["faq"][0].meta["q_no"] == 1


def test_format_result_shape():
    res = _index().search("무주택세대구성원 정의", k=2, faq_k=1)
    text = q.format_result(res)
    lines = text.splitlines()
    assert lines[0].startswith("조문 상위 2개")
    assert lines[1].startswith("1. 제2조 · 제2조제2호 · ")
    assert "FAQ 상위 1개" in lines
    assert lines[-1].startswith("1. Q")
    assert all("\n" not in x for x in lines)


def test_format_result_cuts_text_to_80_chars():
    long = "가" * 200
    law = [_row("제1조", "목적", long)]
    res = q.Index("article", FakeEmbedder(), law_rows=law, faq_rows=FAQ).search("가", k=1, faq_k=1)
    first = q.format_result(res).splitlines()[1]
    assert first.endswith("가" * 10) and len(first.split(" · ")[2]) == 80


def test_main_reads_selected_json_and_prints_exit_0(tmp_path, capsys):
    (tmp_path / "selected.json").write_text(json.dumps({"candidate": "item+head"}))
    rc = q.main(
        ["무주택세대구성원 정의"],
        runs_dir=tmp_path,
        embedder=FakeEmbedder(),
        law_rows=LAW,
        faq_rows=FAQ,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "조문 상위 3개" in out and "FAQ 상위 3개" in out  # 가짜 조문이 3개뿐이다
    assert "제2조 · 제2조제2호 · 제2조(정의)" in out  # +head 후보라 본문이 머리로 시작한다


def test_main_without_selected_json_fails_with_message(tmp_path, capsys):
    rc = q.main(["질문"], runs_dir=tmp_path, embedder=FakeEmbedder(), law_rows=LAW, faq_rows=FAQ)
    assert rc == 1
    assert "selected.json" in capsys.readouterr().err
