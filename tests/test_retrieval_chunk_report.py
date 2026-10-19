import json

import numpy as np

from cheongyak_rag.retrieval import chunk_report as cr
from cheongyak_rag.retrieval.chunk import CANDIDATES
from cheongyak_rag.retrieval.golden import load_faq

N = 30
STATS = {c: {"count": 100 + 10 * i, "median": 100.0, "max": 500} for i, c in enumerate(CANDIDATES)}
TITLES = {f"제{i}조": f"제목{i}" for i in range(1, N + 1)}


def _metrics(gold_rank):
    best = min(gold_rank.values())
    return {
        "recall@5": sum(r <= 5 for r in gold_rank.values()) / len(gold_rank),
        "hit@1": int(best == 1),
        "hit@5": int(best <= 5),
        "mrr": 1 / best,
        "gold_rank": gold_rank,
    }


def _line(i, rank, path="제1조"):
    """질문 i, 정답 하나(제i조)가 세 순위에서 모두 rank위."""
    label = f"제{i}조"
    gr = {label: rank}
    m = _metrics(gr)
    return {
        "qid": f"faq-{i}",
        "q_no": i,
        "question": f"질문 {i}",
        "gold": [label],
        "has_article_in_question": False,
        "top5": [label],
        "bm25": m,
        "dense": m,
        "hybrid": m,
        "gold_detail": {label: {"bm25": rank, "dense": rank, "hybrid": rank, "path": path}},
    }


def _results(ranks_by_cand):
    """후보 → 질문별 순위 목록. 안 준 후보는 article과 같다."""
    base = ranks_by_cand["article"]
    return {
        c: [_line(i + 1, r) for i, r in enumerate(ranks_by_cand.get(c, base))] for c in CANDIDATES
    }


def _inp(results, **kw):
    n = len(results["article"])
    inp = cr.Inputs(
        results=results,
        stats=STATS,
        titles=TITLES,
        long_qids={f"faq-{i}" for i in range(1, 6)},
        ref131={"bm25": 0.5, "dense": 0.5, "hybrid": 0.5},
        faq_lines=[],
        self_check={
            "n": n,
            "self_top1": {"bm25": 1.0, "dense": 0.9, "hybrid": 0.8},
            "misses": [{"qid": "faq-3", "ranker": "dense", "top1_q_no": 9}],
            "leak_count": 0,
        },
        spacing={
            "pairs": [{"q_no": 1, "toc": "가 나", "body": "가나", "jaccard": 0.9, "cosine": 0.99}],
            "mean_jaccard": 0.9,
            "mean_cosine": 0.99,
            "band": "쌍별 값을 리포트에 목록",
        },
        samples=[],
        checks={
            "preservation": {c: [] for c in CANDIDATES},
            "short": {c: {"ratio": 0.0, "items": []} for c in CANDIDATES},
        },
        observation={"kiwi": [("무", "XPN"), ("주택", "NNG")], "bm25": ["주택"]},
    )
    for k, v in kw.items():
        setattr(inp, k, v)
    return inp


SAME = [10] * N  # 전부 5위 밖
ALL_ZERO = {"article": SAME}
# 10개 문항을 5위 밖 → 1위로: 차이 +0.333, CI 하한 > 0
BETTER = [1] * 10 + [10] * (N - 10)
WORSE = [10] * 10 + [1] * (N - 10)  # article이 1위인 문항 10개를 5위 밖으로 떨어뜨림
ART_HALF = [1] * 10 + [10] * (N - 10)


def test_zone_of_four_intervals():
    mk = lambda lo, hi: cr.Verdict("x", (lo + hi) / 2, lo, hi, 0.5, 0.0, None)  # noqa: E731
    assert cr.zone_of(mk(0.01, 0.1)) == "차이 있음"
    assert cr.zone_of(mk(-0.03, 0.03)) == "차이 없음"
    assert cr.zone_of(mk(-0.2, 0.2)) == "판정 불가"
    assert cr.zone_of(mk(-0.3, -0.1)) == "낮다"


def test_all_zero_diffs_say_no_difference_and_keep_article():
    sel = cr.select(_results(ALL_ZERO), STATS)
    assert sel.chosen == "article"
    assert sel.zone == "차이 없음"
    text, selected = cr.build_report(_inp(_results(ALL_ZERO)))
    first = text.splitlines()[0]
    assert "`article`" in first and "차이 없음" in first
    assert selected["candidate"] == "article"


def test_candidate_with_ci_lower_bound_above_zero_is_chosen():
    res = _results({"article": SAME, "item": BETTER})
    sel = cr.select(res, STATS)
    assert sel.chosen == "item"
    assert sel.zone == "차이 있음"
    first = cr.build_report(_inp(res))[0].splitlines()[0]
    assert "`item`" in first and "+0.333" in first


def test_no_candidate_with_lower_bound_above_zero_keeps_article():
    one = [10] * N
    one[0] = 1  # 한 문항만 올라 신뢰구간이 0을 포함한다
    sel = cr.select(_results({"article": SAME, "item": one}), STATS)
    assert sel.chosen == "article"
    assert sel.best == "item"
    assert sel.zone in ("차이 없음", "판정 불가")


def test_tie_goes_to_fewer_chunks():
    res = _results({"article": SAME, "paragraph": BETTER, "item": BETTER})
    assert STATS["paragraph"]["count"] < STATS["item"]["count"]
    assert cr.select(res, STATS).chosen == "paragraph"


def test_tie_break_uses_chunk_count_not_candidate_order():
    stats = {**STATS, "paragraph": {**STATS["paragraph"], "count": 500}}
    res = _results({"article": SAME, "paragraph": BETTER, "item": BETTER})
    assert cr.select(res, stats).chosen == "item"


def test_chosen_is_best_among_lower_bound_winners_not_overall_best_mean():
    art = [1] * 15 + [10] * 15
    wide = [10] * 9 + [1] * 6 + [1] * 15  # 평균 +0.2, 신뢰구간이 0을 포함
    narrow = art[:15] + [1] * 5 + [10] * 10  # 평균 +0.167, 하한 > 0
    res = _results({"article": art, "paragraph": wide, "item": narrow})
    sel = cr.select(res, STATS)
    assert sel.best == "paragraph" and sel.verdicts["paragraph"].lo <= 0
    assert sel.chosen == "item" and sel.zone == "차이 있음"
    first = cr.build_report(_inp(res))[0].splitlines()[0]
    assert "`item`" in first
    assert cr._sgn(sel.verdicts["item"].mean) in first
    assert cr._sgn(sel.verdicts["paragraph"].mean) not in first


def test_one_low_candidate_is_not_all_low():
    res = _results({"article": ART_HALF, "paragraph": SAME})
    sel = cr.select(res, STATS)
    assert sel.zone != "모든 후보가 낮다"


def test_larger_mean_wins_among_positive_lower_bounds():
    better_more = [1] * 20 + [10] * (N - 20)
    res = _results({"article": SAME, "paragraph": BETTER, "item": better_more})
    assert cr.select(res, STATS).chosen == "item"


def test_all_candidates_lower_zone():
    res = _results({"article": ART_HALF, "paragraph": SAME, "paragraph+head": SAME})
    res["item"] = res["paragraph"]
    res["item+head"] = res["paragraph"]
    sel = cr.select(res, STATS)
    assert sel.chosen == "article"
    assert sel.zone == "모든 후보가 낮다"


def test_disagreement_section_lists_every_hit5_split():
    cand = [1] * 4 + [10] * 6 + [1] * 5 + [10] * (N - 15)  # 문항 1~4, 11~15에서 cand만 맞힘
    art = [10] * 4 + [10] * 6 + [10] * 5 + [1] * 2 + [10] * (N - 17)  # 16·17은 article만 맞힘
    res = _results({"article": art, "item": cand})
    text, _ = cr.build_report(_inp(res))
    sec = text.split("## 4.")[1].split("## 5.")[0]
    split_qids = [
        r["qid"]
        for a, c, r in zip(res["article"], res["item"], res["item"], strict=True)
        if a["hybrid"]["hit@5"] != c["hybrid"]["hit@5"]
    ]
    assert len(split_qids) == 11
    for qid in split_qids:
        assert f"{qid} " in sec or f"「질문 {qid.split('-')[1]}」" in sec
    assert "11개" in sec


def test_long_subset_section_uses_only_long_questions():
    outside_long = [10] * 5 + [1] * 10 + [10] * (N - 15)  # 긴 문항(faq-1..5)은 그대로
    res = _results({"article": SAME, "item": outside_long})
    text, _ = cr.build_report(_inp(res))
    full = text.split("## 1.")[1].split("## 2.")[0]
    sec = text.split("## 3.")[1].split("## 4.")[0]
    assert "차이 있음" in full
    row = next(x for x in sec.splitlines() if x.startswith("| `item` |") and "차이" in x)
    assert "차이 없음" in row and "차이 있음" not in row
    assert "| 0.000 | 0.000 | 0.000 |" in row


def test_long_subset_section_has_same_zones():
    res = _results({"article": SAME, "item": BETTER})
    text, _ = cr.build_report(_inp(res))
    sec = text.split("## 3.")[1].split("## 4.")[0]
    assert "질문 5개" in sec
    assert "item" in sec


def test_report_has_all_eight_sections_and_no_judgment_words():
    res = _results({"article": SAME, "item": BETTER})
    text, _ = cr.build_report(_inp(res))
    for n in range(1, 9):
        assert f"\n## {n}. " in text
    for bad in ("개선", "우수"):
        assert bad not in text


def test_sample_section_starts_with_not_human_label_notice():
    sample = {
        "question": "무주택 세대구성원 기준이 뭔가요?",
        "origin": "main 세션",
        "results": {
            "article": {"law": [("제2조", "제2조")], "faq": [(47, "무주택세대구성원이란?")]},
            "item": {"law": [("제2조", "제2조제4호")], "faq": [(47, "무주택세대구성원이란?")]},
        },
    }
    res = _results({"article": SAME})
    text, _ = cr.build_report(_inp(res, samples=[sample]))
    sec = text.split("## 6.")[1].split("## 7.")[0]
    notice = "이 표본의 정답은 사람이 단 라벨이 아니다"
    assert sec.index(notice) < sec.index("무주택 세대구성원 기준이 뭔가요?")
    assert "제2조제4호" in sec and "Q47" in sec


def test_self_check_band():
    assert cr.self_band(0.95) == "통과"
    assert cr.self_band(0.90) == "놓친 것 목록"
    assert cr.self_band(0.85) == "놓친 것 목록"
    assert cr.self_band(0.84) == "버그"


def test_short_band():
    assert cr.short_band(0.02) == "통과"
    assert cr.short_band(0.03) == "목록"
    assert cr.short_band(0.05) == "목록"
    assert cr.short_band(0.0501) == "청킹 규칙 결함"


def test_report_lists_self_check_misses_and_spacing_pairs():
    m = {"faq_hit@1": 1, "faq_hit@5": 1, "top5": [1]}
    faq = [{"qid": "faq-1", "q_no": 1, "bm25": m, "dense": m, "hybrid": m}]
    text, _ = cr.build_report(_inp(_results(ALL_ZERO), faq_lines=faq))
    assert "faq-3" in text  # 놓친 목록
    assert "가나" in text  # 붙은 단어 쌍
    assert "쌍별 값을 리포트에 목록" in text


def test_reproduction_check_compares_three_decimals():
    res = _results({"article": SAME})
    inp = _inp(res, ref131={"bm25": 0.0, "dense": 0.0, "hybrid": 0.0})
    text, _ = cr.build_report(inp)
    sec = text.split("## 8.")[1]
    assert "0.000" in sec and "같음" in sec
    inp = _inp(res, ref131={"bm25": 0.001, "dense": 0.0, "hybrid": 0.0})
    assert "다름" in cr.build_report(inp)[0].split("## 8.")[1]


def test_report_deterministic():
    res = _results({"article": SAME, "item": BETTER})
    assert cr.build_report(_inp(res))[0] == cr.build_report(_inp(res))[0]


def test_selected_json_content():
    res = _results({"article": SAME, "item": BETTER})
    _, selected = cr.build_report(_inp(res))
    assert selected["candidate"] == "item"
    assert selected["compare_candidate"] == "item"
    assert selected["zone"] == "차이 있음"
    json.dumps(selected)


def test_long_qids_uses_max_gold_length_above_median():
    lengths = {"제1조": 10, "제2조": 20, "제3조": 30}  # 중앙값 20
    golden = [
        {"qid": "a", "gold": ["제1조"]},
        {"qid": "b", "gold": ["제1조", "제3조"]},
        {"qid": "c", "gold": ["제2조"]},
    ]
    assert cr.long_qids(golden, lengths) == {"b"}


def test_sample_faq_q_nos_match_design_filter_on_real_data():
    """설계 §3: `무주택`과 `세대구성원`이 같이 든 FAQ 질문 8개."""
    got = [
        r["q_no"] for r in load_faq() if "무주택" in r["question"] and "세대구성원" in r["question"]
    ]
    assert tuple(got) == cr.SAMPLE_FAQ_Q_NOS


def test_diffs_helper_aligns_by_qid():
    a = [_line(1, 10), _line(2, 1)]
    b = [_line(2, 10), _line(1, 1)]  # 순서가 다르다
    assert np.allclose(cr.hybrid_diffs(a, b), [1.0, -1.0])


def test_main_end_to_end_with_fake_embedder(tmp_path):
    from cheongyak_rag.retrieval import chunk_eval as ce
    from tests.fakes import FakeEmbedder

    emb = FakeEmbedder()
    runs = tmp_path / "73"
    for c in CANDIDATES:
        assert ce.main(["--candidate", c], runs_dir=runs, embedder=emb) == 0
    assert ce.main(["--faq"], runs_dir=runs, embedder=emb) == 0
    (runs / "spacing.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {"q_no": 36, "toc": "가 나", "body": "가나", "jaccard": 1.0, "cosine": 1.0}
                ],
                "mean_jaccard": 1.0,
                "mean_cosine": 1.0,
                "band": "영향 없음",
            }
        )
    )
    out = tmp_path / "73-chunking.md"
    assert cr.main(runs_dir=runs, out=out, embedder=emb) == 0
    text = out.read_text()
    assert text.splitlines()[0].startswith("고른 후보는 `")
    for n in range(1, 9):
        assert f"\n## {n}. " in text
    selected = json.loads((runs / "selected.json").read_text())
    assert selected["candidate"] in CANDIDATES
    assert text.count("### 「") == 9  # 정의형 질문 표본 9개
