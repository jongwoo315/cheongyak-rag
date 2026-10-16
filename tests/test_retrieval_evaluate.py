import json

import numpy as np
import pytest

from cheongyak_rag.retrieval.corpus import Article
from cheongyak_rag.retrieval.evaluate import (
    evaluate_run,
    first_sentence,
    metrics,
    pick_sanity,
    run_sanity,
    write_run,
)
from cheongyak_rag.retrieval.search import rrf

LABELS = [f"제{i}조" for i in range(1, 9)]


def test_metrics_hand_calculation():
    m = metrics(LABELS, ["제1조"])
    assert (m["recall@5"], m["hit@1"], m["hit@5"], m["mrr"]) == (1.0, 1, 1, 1.0)
    assert m["gold_rank"] == {"제1조": 1}


def test_recall_at_5_is_half_when_one_of_two_gold_in_top5():
    m = metrics(LABELS, ["제2조", "제7조"])  # 순위 2, 7
    assert m["recall@5"] == 0.5
    assert (m["hit@1"], m["hit@5"]) == (0, 1)
    assert m["mrr"] == 0.5
    assert m["gold_rank"] == {"제2조": 2, "제7조": 7}


def test_metrics_all_miss():
    m = metrics(LABELS, ["제6조", "제8조"])
    assert (m["recall@5"], m["hit@1"], m["hit@5"]) == (0.0, 0, 0)
    assert m["mrr"] == pytest.approx(1 / 6)


ARTICLES = [
    Article("제1조", "청약", "제1조(청약)\n청약 통장 가입 기간을 정한다."),
    Article("제2조", "소득", "제2조(소득)\n월평균 소득 기준을 정한다."),
    Article("제3조", "전매", "제3조(전매)\n분양권 전매 제한 기간을 정한다."),
]
GOLDEN = [
    {"qid": "faq-1", "q_no": 1, "question": "청약 통장 가입 기간", "gold": ["제1조"],
     "has_article_in_question": False},
    {"qid": "faq-2", "q_no": 2, "question": "월평균 소득 기준", "gold": ["제2조", "제3조"],
     "has_article_in_question": False},
]  # fmt: skip


class FakeEmbedder:
    """글자 빈도 벡터. API를 안 부른다."""

    api_calls = 0

    def embed(self, texts):
        chars = sorted(
            {c for t in ARTICLE_TEXT + ["청약 통장 가입 기간", "월평균 소득 기준"] for c in t}
        )
        return np.array([[t.count(c) for c in chars] for t in texts], dtype=float) + 0.01


ARTICLE_TEXT = [a.text for a in ARTICLES]


@pytest.mark.parametrize("run", ["bm25", "dense", "hybrid"])
def test_evaluate_run_lines_match_golden(run):
    lines = evaluate_run(run, GOLDEN, ARTICLES, FakeEmbedder())
    assert [x["qid"] for x in lines] == ["faq-1", "faq-2"]
    for x in lines:
        assert set(x) >= {"qid", "gold", "top5", "recall@5", "hit@1", "hit@5", "mrr", "gold_rank"}
        assert len(x["top5"]) == 3  # 문서가 3개뿐


def test_bm25_finds_obvious_match():
    line = evaluate_run("bm25", GOLDEN, ARTICLES, FakeEmbedder())[0]
    assert line["gold_rank"] == {"제1조": 1}


def test_hybrid_line_has_per_gold_bm25_dense_rrf_detail():
    line = evaluate_run("hybrid", GOLDEN, ARTICLES, FakeEmbedder())[1]
    assert set(line["gold_detail"]) == {"제2조", "제3조"}
    d = line["gold_detail"]["제2조"]
    assert set(d) == {"bm25", "dense", "rrf"} and d["rrf"] > 0
    assert d["rrf"] == pytest.approx(1 / (60 + d["bm25"]) + 1 / (60 + d["dense"]))


def test_hybrid_top5_detail_lists_competitors_too():
    line = evaluate_run("hybrid", GOLDEN, ARTICLES, FakeEmbedder())[0]
    assert list(line["top5_detail"]) == line["top5"]  # 순위 순서 그대로
    assert all(set(d) == {"bm25", "dense", "rrf"} for d in line["top5_detail"].values())


def test_hybrid_is_rrf_of_the_bm25_and_dense_runs():
    # 문서 3개라 top5가 전체 순위다. hybrid가 다른 순위표를 섞었거나 순서를 바꾸면 깨진다
    emb = FakeEmbedder()
    bm = evaluate_run("bm25", GOLDEN, ARTICLES, emb)
    dn = evaluate_run("dense", GOLDEN, ARTICLES, emb)
    hy = evaluate_run("hybrid", GOLDEN, ARTICLES, emb)
    for b, d, h in zip(bm, dn, hy, strict=True):
        assert h["top5"] == [lab for lab, _ in rrf([b["top5"], d["top5"]])]
        for lab, detail in h["gold_detail"].items():
            assert detail["bm25"] == b["top5"].index(lab) + 1
            assert detail["dense"] == d["top5"].index(lab) + 1


def test_rerun_is_byte_identical():
    a = evaluate_run("hybrid", GOLDEN, ARTICLES, FakeEmbedder())
    b = evaluate_run("hybrid", GOLDEN, ARTICLES, FakeEmbedder())
    dump = lambda xs: "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in xs)  # noqa: E731
    assert dump(a) == dump(b)


def test_write_run_writes_results_and_config(tmp_path):
    lines = evaluate_run("dense", GOLDEN, ARTICLES, FakeEmbedder())
    write_run(tmp_path, "dense", lines, ARTICLES, FakeEmbedder())
    out = tmp_path / "dense"
    assert len((out / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert cfg["doc_count"] == 3 and cfg["question_count"] == 2 and cfg["run"] == "dense"
    assert {"model", "k1", "b", "rrf_k", "run_at", "commit", "embedding_api_calls"} <= set(cfg)


def test_first_sentence_stops_at_sentence_end():
    art = Article("제1조", "t", "제1조(t)\n이 규칙은 목적이다. 둘째 문장이다.")
    assert first_sentence(art) == "이 규칙은 목적이다."


def test_first_sentence_when_head_only_uses_first_paragraph():
    art = Article("제2조", "t", "제2조(t)\n① 사업주체는 공고한다. 다음은 생략\n② 둘째")
    assert first_sentence(art) == "① 사업주체는 공고한다."


def test_pick_sanity_spreads_evenly_and_includes_both_ends():
    arts = [Article(f"제{i}조", "t", "x") for i in range(88)]
    picked = pick_sanity(arts, 20)
    assert len(picked) == 20 and picked[0].label == "제0조" and picked[-1].label == "제87조"
    assert [a.label for a in picked] == sorted(
        {a.label for a in picked}, key=lambda s: int(s[1:-1])
    )


def test_run_sanity_reports_rank_of_own_article(tmp_path):
    res = run_sanity(tmp_path, ARTICLES, FakeEmbedder(), n=3)
    assert res["bm25_top1"] == 3 and res["dense_top1"] == 3
    rows = (tmp_path / "sanity" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3 and json.loads(rows[0])["label"] == "제1조"


def test_commit_marks_dirty_tree(monkeypatch):
    from cheongyak_rag.retrieval import evaluate

    answers = {"rev-parse": "abc123", "status": " M x.py"}
    monkeypatch.setattr(evaluate, "_git", lambda *a: answers[a[0]])
    assert evaluate._commit() == "abc123-dirty"
    answers["status"] = ""
    assert evaluate._commit() == "abc123"
