"""#76 지표 7개 — 정의마다 손으로 만든 run 줄로 기대값을 정한다 (설계 §3.3)."""

from cheongyak_rag.eval import metrics


def row(gold="NEED_INFO", sys=None, *, axis="a", gold_cites=("제1조",), top5=(), cites=(), **kw):
    return {
        "axis": axis,
        "gold_verdict": gold,
        "gold_citations": list(gold_cites),
        "matched": sys is not None or bool(kw.get("error")),
        "sys_verdict": sys,
        "sys_citations": list(cites),
        "law_top5": list(top5),
        "faq_top3": [],
        "error": kw.get("error"),
        "cause": None,
    }


def nd(m):
    return (m["num"], m["den"])


def test_ratio_zero_denominator_has_no_value():
    assert metrics.ratio(0, 0)["value"] is None


def test_recall_counts_pairs_and_unmatched_stays_in_denominator():
    rows = [
        row(gold_cites=("제1조", "제2조"), sys="NEED_INFO", top5=("제1조", "제9조")),  # 1/2
        row(gold_cites=("제3조",)),  # 못 맞춘 라벨: 분자 0, 분모 1
    ]
    assert nd(metrics.recall_at_5(rows)) == (1, 3)


def test_hit_counts_labels_with_any_gold_article():
    rows = [
        row(gold_cites=("제1조", "제2조"), sys="NEED_INFO", top5=("제2조",)),
        row(gold_cites=("제3조",), sys="NEED_INFO", top5=("제4조",)),
        row(gold_cites=("제5조",)),
    ]
    assert nd(metrics.hit_at_5(rows)) == (1, 3)


def test_citation_precision_drops_faq_and_counts_it_apart():
    rows = [
        row(sys="NEED_INFO", cites=("제1조", "제9조", "Q47")),  # 조문 2개 중 1개
        row(sys="NEED_INFO", cites=("Q1",)),  # FAQ만 — 분모에 안 든다
        row(),  # 못 맞춘 라벨은 인용이 없다
    ]
    assert nd(metrics.citation_precision(rows)) == (1, 2)
    assert metrics.counts(rows)["faq_citations"] == 2


def test_accuracy_failed_verdict_is_wrong():
    rows = [row("ELIGIBLE", "ELIGIBLE"), row("ELIGIBLE", None, error="timeout")]
    assert nd(metrics.judgment_accuracy(rows)["total"]) == (1, 2)
    assert metrics.counts(rows)["verdict_errors"] == 1


def test_fatal_error_rate_only_ineligible_gold():
    rows = [
        row("INELIGIBLE", "ELIGIBLE"),  # 치명오답
        row("INELIGIBLE", "INELIGIBLE"),
        row("INELIGIBLE", "NEED_INFO"),
        row("INELIGIBLE"),  # 못 맞춘 라벨은 ELIGIBLE을 낸 게 아니다
        row("ELIGIBLE", "ELIGIBLE"),  # 분모 밖
    ]
    assert nd(metrics.fatal_error_rate(rows)) == (1, 4)


def test_abstain_includes_need_info_and_unverifiable_but_not_errors():
    rows = [
        row("NEED_INFO", "NEED_INFO"),
        row("NEED_INFO", "UNVERIFIABLE"),
        row("NEED_INFO", "ELIGIBLE"),
        row("NEED_INFO", None, error="x"),  # 판정 실패는 abstain이 아니다
        row("ELIGIBLE", "NEED_INFO"),  # 부당
        row("INELIGIBLE", "INELIGIBLE"),
        row("INELIGIBLE", "UNVERIFIABLE"),  # 부당
    ]
    assert nd(metrics.justified_abstain(rows)) == (2, 4)
    assert nd(metrics.unjustified_abstain(rows)) == (2, 3)


def test_compute_has_seven_metrics_and_counts():
    rows = [row("NEED_INFO", "NEED_INFO", top5=("제1조",)), row(), row("NEED_INFO", "NEED_INFO")]
    m = metrics.compute(rows)
    assert set(m) == {
        "recall_at_5",
        "hit_at_5",
        "citation_precision",
        "judgment_accuracy",
        "fatal_error_rate",
        "justified_abstain",
        "unjustified_abstain",
    }
    c = metrics.counts(rows)
    assert (c["unmatched_labels"], c["no_law_results"], c["search_incomplete"]) == (1, 1, 2)
