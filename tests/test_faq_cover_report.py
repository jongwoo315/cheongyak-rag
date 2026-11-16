import json

import pytest

from cheongyak_rag.ingest import faq_cover_report as fcr
from cheongyak_rag.ingest.citations import extract_citations, sentence_of

ANSWER = "「주택법」 제2조에 따른다. 청약통장은 제9조를 본다. 부칙 제6조는 아니다."
MARKED = "「주택법」 제2조에 따른다. 청약통장은 【제9조】를 본다. 부칙 제6조는 아니다."


def _faq(q_no, answer):
    return {
        "q_no": q_no,
        "as_of": "2024-05-29",
        "cited_articles": [],
        "question": "",
        "answer": answer,
    }


def test_sentence_of_returns_the_sentence_around_a_position():
    text = "첫 문장이다. 둘째 문장에 제9조가 있다. 셋째 문장이다."
    start, end = sentence_of(text, text.index("제9조"))

    assert text[start:end].strip() == "둘째 문장에 제9조가 있다."


def test_places_follow_extract_citations_in_order_with_pair_sequence_numbers():
    faq = [_faq(7, ANSWER), _faq(8, "인용이 없다."), _faq(9, "제1조와 제1조")]

    got = fcr.places(faq)

    assert [(p.q_no, p.no, p.label) for p in got] == [
        (7, 1, "제2조"),
        (7, 2, "제9조"),
        (7, 3, "제6조"),
        (9, 1, "제1조"),
        (9, 2, "제1조"),
    ]
    assert [p.kind for p in got] == [c.kind for c in extract_citations(ANSWER)] + ["none", "none"]


def test_labeler_input_hides_the_classification_and_marks_the_place():
    batch = fcr.labeler_input(fcr.places([_faq(7, ANSWER)]))

    assert batch == [
        {
            "q_no": 7,
            "answer": ANSWER,
            "places": [
                {
                    "no": 1,
                    "label": "제2조",
                    "context": "「주택법」 【제2조】에 따른다. 청약통장은 제9조를 본다.",
                },
                {
                    "no": 2,
                    "label": "제9조",
                    "context": MARKED,
                },
                {
                    "no": 3,
                    "label": "제6조",
                    "context": "청약통장은 제9조를 본다. 부칙 【제6조】는 아니다.",
                },
            ],
        }
    ]
    dumped = json.dumps(batch, ensure_ascii=False)
    assert '"kind"' not in dumped and '"before"' not in dumped and '"name"' not in dumped


def test_batches_keep_a_pair_together_and_stay_near_the_size():
    faq = [_faq(i, "제1조 제2조 제3조") for i in range(1, 8)]  # 쌍마다 3자리

    batches = fcr.batches(fcr.labeler_input(fcr.places(faq)), size=7)

    assert [[p["q_no"] for p in b] for b in batches] == [[1, 2, 3], [4, 5, 6], [7]]


def test_a_tiny_last_batch_joins_the_previous_one():
    faq = [_faq(i, "제1조 제2조 제3조") for i in range(1, 6)]
    batches = fcr.batches(fcr.labeler_input(fcr.places(faq)), size=10)  # 마지막은 3자리 < 5

    assert [[p["q_no"] for p in b] for b in batches] == [[1, 2, 3, 4, 5]]


def _row(q_no, no, label, law_label, name=None, evidence="근거"):
    return {
        "q_no": q_no,
        "no": no,
        "label": label,
        "law_label": law_label,
        "law_name": name,
        "evidence": evidence,
    }


def test_validate_labels_requires_one_row_per_place_in_order():
    ps = fcr.places([_faq(7, ANSWER)])
    ok = [
        _row(7, 1, "제2조", "다른 법령", "주택법"),
        _row(7, 2, "제9조", "이름 없음"),
        _row(7, 3, "제6조", "다른 법령", "부칙"),
    ]

    assert fcr.validate_labels(ps, ok) == []
    assert fcr.validate_labels(ps, ok[:2])  # 자리 수가 모자란다
    assert fcr.validate_labels(ps, [ok[1], ok[0], ok[2]])  # 순서·자리가 안 맞는다
    assert fcr.validate_labels(ps, [{**ok[0], "law_label": "타법"}, *ok[1:]])  # 허용 값이 아니다
    assert fcr.validate_labels(
        ps, [{**ok[0], "law_name": None}, *ok[1:]]
    )  # 다른 법령인데 이름이 없다
    assert fcr.validate_labels(ps, [ok[0], {**ok[1], "evidence": ""}, ok[2]])  # 근거가 비었다


def test_side_groups_rule_and_none_together():
    assert [fcr.class_side(k) for k in ("rule", "none", "other")] == ["rule", "rule", "other"]
    assert [fcr.label_side(v) for v in ("규칙", "이름 없음", "다른 법령", "모름")] == [
        "rule",
        "rule",
        "other",
        "unknown",
    ]


def test_disagreements_exclude_unknown_and_count_it_apart():
    ps = fcr.places([_faq(7, ANSWER)])  # 분류: other · none · other
    labels = [
        _row(7, 1, "제2조", "규칙"),  # 분류 other ↔ 규칙: 다르다
        _row(7, 2, "제9조", "모름"),  # 따로 센다
        _row(7, 3, "제6조", "다른 법령", "부칙"),  # 같다
    ]

    diffs, unknown = fcr.disagreements(ps, labels)

    assert [(d.place.q_no, d.place.no) for d in diffs] == [(7, 1)]
    assert [(u.place.q_no, u.place.no) for u in unknown] == [(7, 2)]


def test_label_based_uncovered_pairs_use_the_label_side_and_skip_unknown():
    faq = [_faq(1, "제999조"), _faq(2, "제999조"), _faq(3, "제1조"), _faq(4, "제999조")]
    ps = fcr.places(faq)
    labels = [
        _row(1, 1, "제999조", "규칙"),  # 규칙 인용인데 현행에 없다
        _row(2, 1, "제999조", "다른 법령", "주택법"),  # 다른 법령이라 분모 밖
        _row(3, 1, "제1조", "이름 없음"),
        _row(4, 1, "제999조", "모름"),  # 모름은 규칙으로 안 센다
    ]

    got = fcr.label_based_cover(ps, labels, current={"제1조"})

    assert (got.rule_pairs, got.uncovered_pairs) == (2, 1)
    assert [u.q_no for u in got.uncovered] == [1]


def test_gold_change_counts_only_places_that_change_the_pair_gold_set():
    # 같은 조가 두 번 나오면 한 자리의 분류가 바뀌어도 정답 조 집합은 그대로다
    faq = [_faq(1, "「주택법」 제2조. 제2조도 본다. 제9조"), _faq(2, "「주택법」 제5조")]
    ps = fcr.places(faq)
    labels = [
        _row(
            1, 1, "제2조", "규칙"
        ),  # 분류 other ↔ 규칙: 그런데 둘째 자리(none)가 제2조를 이미 정답에 넣었다
        _row(1, 2, "제2조", "이름 없음"),
        _row(1, 3, "제9조", "이름 없음"),
        _row(2, 1, "제5조", "규칙"),  # 분류 other ↔ 규칙: 정답 조 집합이 {} → {제5조}
    ]
    diffs, _ = fcr.disagreements(ps, labels)

    changing = fcr.gold_changing(ps, labels, diffs)

    assert [(d.place.q_no, d.place.no) for d in changing] == [(2, 1)]


def test_even_sample_takes_every_nth_item():
    assert fcr.even_sample(list(range(100)), 10) == list(range(0, 100, 10))
    assert fcr.even_sample([1, 2, 3], 10) == [1, 2, 3]
    assert fcr.even_sample([], 5) == []


@pytest.mark.parametrize("n", [0, -1])
def test_even_sample_with_no_room_returns_empty(n):
    assert fcr.even_sample([1, 2, 3], n) == []


# ── 리포트 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fn, n, want",
    [
        (fcr.band_sign1, 0, "통과"),
        (fcr.band_sign1, 2, "다시 잰다"),
        (fcr.band_sign1, 3, "미완"),
        (fcr.band_sign2, 4, "정상"),
        (fcr.band_sign2, 5, "다시 잰다"),
        (fcr.band_sign2, 20, "다시 잰다"),
        (fcr.band_sign2, 21, "미완"),
    ],
)
def test_bands_follow_the_plan_cutoffs(fn, n, want):
    assert fn(n) == want


def test_sign3_and_sign4_bands():
    assert fcr.band_sign3(same=True) == "정상"
    assert fcr.band_sign3(same=False) == "미완"
    assert fcr.band_sign4((123, 123, 59), (123, 123, 59)) == "정상"
    assert fcr.band_sign4((123, 122, 59), (123, 123, 59)) == "다시 잰다"


def _law_rows(*labels):
    return [{"label": lb, "deleted": False, "amendments": []} for lb in labels]


def test_build_report_has_every_section_and_the_plan_numbers():
    faq = [
        {**_faq(1, "「주택법」 제2조와 제1조를 본다."), "cited_articles": ["제2조", "제1조"]},
        {**_faq(2, "제999조는 없다. 제1조는 있다."), "cited_articles": ["제999조", "제1조"]},
        {**_faq(3, "「민법」 제5조만 본다."), "cited_articles": ["제5조"]},
    ]
    ps = fcr.places(faq)
    labels = [
        _row(1, 1, "제2조", "다른 법령", "주택법", "「주택법」 제2조"),
        _row(1, 2, "제1조", "규칙", None, "주택법 제2조와 제1조"),  # 분류 other ↔ 규칙
        _row(2, 1, "제999조", "이름 없음", None, "제999조는 없다"),
        _row(2, 2, "제1조", "모름", None, "제1조는 있다"),
        _row(3, 1, "제5조", "다른 법령", "민법", "「민법」 제5조"),
    ]

    out = fcr.build_report(faq, _law_rows("제1조", "제2조"), labels, golden_same=True)

    assert "## 실패 징후" in out
    assert "번호로만 센 커버" in out
    assert "## 분류와 법령 이름 라벨이 다른 자리" in out
    assert "## jw 표본" in out
    assert "같은 모델이 읽은 것이라 완전히 독립된 확인이 아니다" in out
    # 새 커버: Q1은 두 자리 다 「주택법」 뒤라 다른 법령만이다. 규칙 인용 쌍은 Q2 하나뿐이다
    assert "규칙 인용 있는 쌍 1 · 커버 0 · 커버 안 됨 1 · 다른 법령 인용만 있는 쌍 2" in out
    assert "| Q1 | 2 | 제1조 |" in out  # 갈린 자리 한 줄
    assert "- 쌍마다 갈린 자리 수: Q1 1" in out
    assert "모름" in out
    assert len(fcr.sample_places(ps, {"제1조", "제2조"}, faq)) <= 20


def test_even_sample_reaches_the_tail():
    items = list(range(53))

    got = fcr.even_sample(items, 10)

    assert len(got) == 10 and got[0] == 0 and got[-1] >= 47  # 꼬리 쪽도 뽑힌다


def test_sample_groups_split_the_candidates_by_the_plan_filters():
    faq = [
        {
            **_faq(1, "「주택법」 제999조를 본다."),
            "cited_articles": ["제999조"],
        },  # 번호로 커버 안 됨
        {
            **_faq(2, "「주택법」 제1조를 본다."),
            "cited_articles": ["제1조"],
        },  # 조 번호가 규칙에 있다
        _faq(3, "제1조를 본다."),  # 이름 없음
    ]

    uncovered, in_rule, none = fcr.sample_groups(fcr.places(faq), {"제1조"}, faq)

    assert [(p.q_no, p.label) for p in uncovered] == [(1, "제999조")]
    assert [(p.q_no, p.label) for p in in_rule] == [(2, "제1조")]
    assert [(p.q_no, p.label) for p in none] == [(3, "제1조")]


def test_gold_pair_changes_lists_added_and_removed_labels_and_keeps_unknown():
    faq = [_faq(1, "「주택법」 제2조. 제9조"), _faq(2, "「주택법」 제5조"), _faq(3, "제7조")]
    ps = fcr.places(faq)
    labels = [
        _row(1, 1, "제2조", "규칙"),  # 정답에 제2조가 더해진다
        _row(1, 2, "제9조", "이름 없음"),
        _row(2, 1, "제5조", "다른 법령", "주택법"),  # 같다
        _row(3, 1, "제7조", "모름"),  # 분류 쪽 그대로
    ]

    assert fcr.gold_pair_changes(ps, labels) == [(1, {"제2조"}, set(), {"제2조", "제9조"})]


def test_main_rejects_an_unknown_argument_without_touching_the_report(capsys):
    assert fcr.main(["merg"]) == 2
    assert "모르는 인자" in capsys.readouterr().err


def test_sample_places_takes_ten_five_five_in_group_order():
    faq = (
        [
            {**_faq(i, "「주택법」 제999조를 본다."), "cited_articles": ["제999조"]}
            for i in range(1, 13)
        ]
        + [
            {**_faq(i, "「주택법」 제1조를 본다."), "cited_articles": ["제1조"]}
            for i in range(13, 20)
        ]
        + [_faq(i, "제1조를 본다.") for i in range(20, 27)]
    )

    got = fcr.sample_places(fcr.places(faq), {"제1조"}, faq)

    assert [p.q_no for p in got] == [1, 2, 3, 4, 5, 7, 8, 9, 10, 11] + [13, 14, 15, 17, 18] + [
        20,
        21,
        22,
        24,
        25,
    ]
