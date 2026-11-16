from cheongyak_rag.ingest import citations
from cheongyak_rag.retrieval import golden


def test_golden_uses_the_classifier_from_the_ingest_module():
    # 복사가 아니라 같은 함수여야 한다. 두 곳이 다르게 세면 정답 라벨과 리포트가 갈린다
    assert golden.extract_citations is citations.extract_citations
    assert golden.Citation is citations.Citation


def test_classifier_splits_rule_other_and_none():
    got = citations.extract_citations(
        "「주택법」 제2조에 따른다. 「주택공급에 관한 규칙」 제23조도 본다. 제4조를 본다."
    )

    assert [(c.label, c.kind) for c in got] == [
        ("제2조", "other"),
        ("제23조", "rule"),
        ("제4조", "none"),
    ]


def test_citation_carries_the_nearest_preceding_law_name():
    got = citations.extract_citations(
        "「주택법」 제2조와 「민법」 제3조를 본다. 시행령 제4조. 제5조. 부칙 제6조."
    )

    assert [(c.label, c.kind, c.name) for c in got] == [
        ("제2조", "other", "주택법"),
        ("제3조", "other", "민법"),
        ("제4조", "other", "시행령"),
        ("제5조", "none", None),
        ("제6조", "other", "부칙"),
    ]
