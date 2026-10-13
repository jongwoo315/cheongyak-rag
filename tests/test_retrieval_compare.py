import math

import numpy as np
import pytest

from cheongyak_rag.retrieval.compare import (
    bootstrap_ci,
    build_report,
    check_runs,
    paired_permutation_p,
    verdict,
)
from cheongyak_rag.retrieval.corpus import Article
from cheongyak_rag.retrieval.evaluate import metrics
from cheongyak_rag.retrieval.golden import GoldenResult

UNIVERSE = [f"제{i}조" for i in range(1, 13)]
ARTICLES = [Article(label, f"제목{i}", "가" * (100 * i)) for i, label in enumerate(UNIVERSE, 1)]


def _ranking(gold_ranks: dict[str, int]) -> list[str]:
    """gold를 지정한 순위에 놓고 나머지로 채운 전체 순위."""
    out: list[str | None] = [None] * len(UNIVERSE)
    for label, r in gold_ranks.items():
        out[r - 1] = label
    rest = iter(x for x in UNIVERSE if x not in gold_ranks)
    return [x if x is not None else next(rest) for x in out]


def _line(qid, gold, ranks, *, has_article=False, hybrid=None):
    ranking = _ranking(ranks)
    line = {
        "qid": qid,
        "q_no": int(qid.split("-")[1]),
        "question": f"질문 {qid}",
        "gold": gold,
        "has_article_in_question": has_article,
        "top5": ranking[:5],
        **metrics(ranking, gold),
    }
    if hybrid:
        line["gold_detail"] = {
            g: {"bm25": b, "dense": d, "rrf": 1 / (60 + b) + 1 / (60 + d)}
            for g, (b, d) in hybrid.items()
        }
        line["top5_detail"] = {
            x: {"bm25": i, "dense": i, "rrf": 2 / (60 + i)} for i, x in enumerate(ranking[:5], 1)
        }
        for g, d in line["gold_detail"].items():
            line["top5_detail"].setdefault(g, d)
    return line


def _results(specs):
    """specs: [(qid, gold, bm25_rank, dense_rank, hybrid_rank)] — 정답이 하나인 질문."""
    out = {"bm25": [], "dense": [], "hybrid": []}
    for qid, gold, b, d, h, *opt in specs:
        has_article = opt[0] if opt else False
        g = gold[0]
        out["bm25"].append(_line(qid, gold, {g: b}, has_article=has_article))
        out["dense"].append(_line(qid, gold, {g: d}, has_article=has_article))
        out["hybrid"].append(_line(qid, gold, {g: h}, has_article=has_article, hybrid={g: (b, d)}))
    return out


SPECS = [
    ("faq-1", ["제1조"], 1, 1, 1),  # 둘 다 맞힘
    ("faq-2", ["제2조"], 2, 9, 2),  # hybrid만 (BM25가 끌어올림)
    ("faq-3", ["제3조"], 8, 8, 4),  # hybrid만 (합산 효과)
    ("faq-4", ["제4조"], 12, 3, 7),  # dense만 (BM25가 끌어내림)
    ("faq-5", ["제5조"], 10, 10, 10),  # 둘 다 놓침
    ("faq-6", ["제6조"], 1, 7, 2, True),
]


@pytest.fixture
def report():
    return build_report(_results(SPECS), GoldenResult(), ARTICLES, sanity_rows=None)


def test_permutation_p_is_1_and_ci_zero_when_all_diffs_zero():
    d = np.zeros(30)
    assert paired_permutation_p(d) == 1.0
    assert bootstrap_ci(d) == (0.0, 0.0)


def test_same_seed_same_result():
    d = np.array([0.5, -0.25, 1.0, 0.0, 0.5, -0.5])
    assert paired_permutation_p(d) == paired_permutation_p(d)
    assert bootstrap_ci(d) == bootstrap_ci(d)


def test_consistent_positive_diffs_are_significant():
    d = np.full(40, 0.5)
    assert paired_permutation_p(d) < 0.001
    assert bootstrap_ci(d) == (0.5, 0.5)


def test_verdict_three_intervals():
    assert verdict(np.full(50, 0.2)).kind == "차이 있음"
    tiny = np.array([0.01, -0.01] * 100)
    assert verdict(tiny).kind == "차이 없음"
    wide = np.array([1.0, -1.0] * 10)
    v = verdict(wide)
    assert v.kind == "판정 불가"
    sd = float(np.std(wide, ddof=1))
    assert v.needed_n == math.ceil((1.96 * sd / 0.05) ** 2)


def test_check_runs_rejects_different_question_sets():
    res = _results(SPECS)
    golden = [{"qid": x["qid"]} for x in res["dense"]]
    check_runs(res, golden)  # 같으면 통과
    res["hybrid"] = res["hybrid"][:-1]
    with pytest.raises(ValueError, match="hybrid"):
        check_runs(res, golden)


def test_report_has_all_sections_in_order(report):
    heads = [line for line in report.splitlines() if line.startswith("## ")]
    nums = [h.split(".")[0].removeprefix("## ") for h in heads[:7]]
    assert nums == ["1", "2", "3", "4", "5", "6", "7"]


def test_first_line_is_conclusion_sentence_without_judgment_words(report):
    first = report.splitlines()[0]
    assert (
        first.startswith("hybrid가 dense보다 recall@5가 ") and "95% CI" in first and "p=" in first
    )
    assert "개선" not in report and "우수" not in report


def test_every_disagreement_is_listed_with_all_ranks(report):
    section = report.split("## 4.")[1].split("## 5.")[0]
    for qid in ("faq-2", "faq-3", "faq-4", "faq-6"):  # hit@5가 갈린 질문
        assert qid in section
    assert "faq-1" not in section and "faq-5" not in section
    row = next(x for x in section.splitlines() if "faq-2" in x)
    assert "BM25 2" in row and "dense 9" in row and "hybrid 2" in row


def test_2x2_counts(report):
    section = report.split("## 3.")[1].split("## 4.")[0]
    # 둘 다 맞힘 1(faq-1) · dense만 1(faq-4) · hybrid만 3(faq-2·3·6) · 둘 다 놓침 1(faq-5)
    assert "| dense 맞힘 | 1 | 1 |" in section
    assert "| dense 놓침 | 3 | 1 |" in section


def test_reasons_are_counted(report):
    section = report.split("## 5.")[1].split("## 6.")[0]
    assert "BM25가 끌어올림" in section and "BM25가 끌어내림" in section


def test_sign_flip_in_subset_marks_warning_in_first_section():
    # 제N조가 든 질문만 hybrid가 우세 → 그 질문을 빼면 부호가 반대(dense가 우세)
    specs = [("faq-1", ["제1조"], 1, 9, 1, True), ("faq-2", ["제2조"], 9, 1, 9, False)]
    specs += [("faq-3", ["제3조"], 1, 9, 1, True), ("faq-4", ["제4조"], 9, 1, 9, False)]
    specs += [("faq-5", ["제5조"], 1, 9, 1, True), ("faq-6", ["제6조"], 9, 3, 9, False)]
    specs += [("faq-7", ["제7조"], 1, 9, 1, True)]
    rep = build_report(_results(specs), GoldenResult(), ARTICLES, sanity_rows=None)
    first = rep.split("## 2.")[0]
    assert "⚠" in first and "제N조" in first


def test_same_sign_subset_has_no_warning(report):
    assert "⚠" not in report.split("## 2.")[0]


def test_sanity_section_reports_counts():
    rows = [
        {"label": f"제{i}조", "query": "q", "bm25_rank": 1, "bm25_top1": f"제{i}조",
         "dense_rank": 1 if i < 17 else 3, "dense_top1": f"제{i}조" if i < 17 else "제99조"}
        for i in range(1, 21)
    ]  # fmt: skip
    rep = build_report(_results(SPECS), GoldenResult(), ARTICLES, sanity_rows=rows)
    assert "BM25 20/20" in rep and "dense 16/20" in rep
