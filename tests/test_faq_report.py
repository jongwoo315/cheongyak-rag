import json

from cheongyak_rag.ingest.faq import BodyStats, FaqPair, TocEntry, write_jsonl
from cheongyak_rag.ingest.faq_report import build_report, format_report

MAJOR = "Ⅰ. 청약자격(공통)"
MIDDLE = "1. 청약신청지역"


def toc_entry(n, minor="가. 첫째", question=None):
    return TocEntry(n, MAJOR, MIDDLE, minor, question or f"질문 {n}번 내용은?")


def pair(n, minor="가. 첫째", question=None, answer="충분히 긴 답변 본문입니다. " * 5):
    return FaqPair(
        n, MAJOR, MIDDLE, minor, question or f"질문 {n}번 내용은?", answer, 10, "2024-05-29", []
    )


def report(toc, pairs, stats=None):
    return build_report(toc, pairs, stats or BodyStats(), warnings=0)


def test_clean_input_has_no_mismatch():
    r = report([toc_entry(1), toc_entry(2)], [pair(1), pair(2)])
    assert (r.pair_count, r.q_no_ok, r.mismatches, r.leaks, r.outliers) == (2, True, [], [], [])


def test_wrong_section_is_caught():
    # 2번 쌍이 일부러 다른 소분류에 들어갔다
    r = report([toc_entry(1), toc_entry(2)], [pair(1), pair(2, minor="나. 둘째")])
    assert [(m.q_no, m.field, m.toc, m.body) for m in r.mismatches] == [
        (2, "minor", "가. 첫째", "나. 둘째")
    ]


def test_wrong_question_is_caught_but_spacing_only_is_not():
    toc = [toc_entry(1, question="입금해도 되나요?"), toc_entry(2, question="질문 2")]
    pairs = [pair(1, question="입금해도되나요?"), pair(2, question="다른 질문")]
    r = report(toc, pairs)
    assert [m.q_no for m in r.mismatches] == [2]  # 공백을 전부 빼면 같은 1번은 일치로 센다
    assert [m.q_no for m in r.spacing_diffs] == [1]  # 공백 연속만 합친 엄격 비교로는 다르다


def test_missing_and_duplicate_q_no():
    r = report([toc_entry(1), toc_entry(2), toc_entry(3)], [pair(1), pair(3), pair(3)])
    assert r.q_no_ok is False
    assert {m.q_no for m in r.mismatches} >= {2}  # 목차에 있는데 쌍이 없다


def test_answer_boundary_leaks():
    toc = [toc_entry(1), toc_entry(2), toc_entry(3)]
    pairs = [
        pair(1, answer=f"본문\n{MAJOR}\n끝" * 3),  # (a) 쪽 머리말
        pair(2, answer="본문 " * 10 + "\n1. 청약신청지역"),  # (b) 중분류 제목
        pair(3, answer="본문 " * 10 + "질문 4번 내용은?"),  # (c) 다음 질문
    ]
    toc.append(toc_entry(4))
    pairs.append(pair(4))
    r = report(toc, pairs)
    assert [(leak.q_no, leak.kind) for leak in r.leaks] == [
        (1, "머리말"),
        (2, "목차 제목"),
        (3, "다음 질문"),
    ]


def test_title_inside_a_sentence_is_not_a_leak():
    # `2023. 11. 2. 입주자모집…`은 중분류 `2. 입주자 모집`이 아니다 (Q199 실제 사례)
    entry = TocEntry(1, MAJOR, "2. 입주자 모집", "", "질문?")
    p = pair(1, answer="따라서 2023. 11. 2. 입주자모집공고한 단지부터는 신청할 수 없습니다. " * 2)
    assert report([entry], [p]).leaks == []


def test_length_outliers_listed():
    toc = [toc_entry(n) for n in (1, 2, 3)]
    pairs = [pair(1, answer="짧다"), pair(2), pair(3, answer="가" * 3001)]
    r = report(toc, pairs)
    assert r.outliers == [(1, 2), (3, 3001)]
    assert r.length_min == 2 and r.length_max == 3001


def test_format_report_mentions_every_section():
    text = format_report(
        report([toc_entry(1)], [pair(1)], BodyStats(skipped_pages={5}, skipped_chars=9))
    )
    for needle in ("쌍 수", "섹션 불일치", "답변 경계", "답변 길이", "표", "주요내용", "경고"):
        assert needle in text


def test_write_jsonl_one_pair_per_line(tmp_path):
    out = tmp_path / "out" / "faq.jsonl"
    write_jsonl([pair(1), pair(2)], out)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["q_no"] for r in rows] == [1, 2]
    assert set(rows[0]) == {
        "q_no", "major", "middle", "minor", "question", "answer",
        "page_start", "as_of", "cited_articles",
    }  # fmt: skip
    assert "질문 1번" in out.read_text(encoding="utf-8")  # ensure_ascii=False


def test_count_warnings_expands_repeat_lines():
    from cheongyak_rag.ingest.faq import count_warnings

    assert count_warnings("") == 0
    assert count_warnings("freetype could not find any cmaps\n... repeated 2 times...") == 3


def test_empty_pairs_are_not_reported_as_contiguous():
    # 파싱이 0쌍이면 `[] == list(range(1, 1))`이 참이라 연속으로 보고되던 것을 막는다
    r = report([toc_entry(1)], [])
    assert (r.pair_count, r.q_no_ok) == (0, False)
