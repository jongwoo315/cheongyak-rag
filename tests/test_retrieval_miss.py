import json
import math
import statistics

import numpy as np
import pytest

from cheongyak_rag.retrieval import miss
from cheongyak_rag.retrieval.chunk import CANDIDATES, law_chunks
from cheongyak_rag.retrieval.corpus import Article, _body
from cheongyak_rag.retrieval.evaluate import first_sentence, run_sanity
from cheongyak_rag.retrieval.search import BM25
from tests.fakes import FakeEmbedder


def _row(label, title, rest="", paragraphs=()):
    return {
        "label": label,
        "title": title,
        "deleted": False,
        "text": f"{label}({title}) {rest}".strip(),
        "paragraphs": list(paragraphs),
    }


def _para(no, text, items=()):
    return {"no": no, "text": text, "items": list(items)}


def _item(no, text):
    return {"no": no, "text": text, "subitems": []}


ROWS = [
    _row("제1조", "목적", "이 규칙은 주택 공급 조건을 정한다."),
    _row("제2조", "정의", "용어의 뜻은 다음과 같다.", [_para("", "", [_item("1", "1. 공급이란")])]),
    _row("제3조", "자격", "청약 자격은 나이와 소득으로 정한다. 추가 요건도 있다."),
    _row(
        "제4조",
        "순위",
        "순위는 가입 기간으로 정한다.",
        [_para("①", "① 첫째", [_item("1", "1. 호")])],
    ),
    _row("제5조", "당첨", "당첨자는 추첨으로 정한다."),
    _row("제6조", "취소", "취소 사유는 다음과 같다.", [_para("①", "① 거짓 신청")]),
]
ARTICLES = [Article(r["label"], r["title"], _body(r)) for r in ROWS]
N = 4  # 6개 중 4개(제1·3·4·6조)


@pytest.fixture(scope="module")
def lines():
    return miss.sanity_by_candidate(ROWS, ARTICLES, FakeEmbedder(), n=N)


# ── Task 1 — 후보별 점검 run ────────────────────────────────────────────


def test_one_line_per_candidate_and_question(lines):
    assert len(lines) == len(CANDIDATES) * N
    assert [x["candidate"] for x in lines[:N]] == ["article"] * N
    assert {x["candidate"] for x in lines} == set(CANDIDATES)


def test_article_candidate_ranks_equal_run_sanity(lines, tmp_path):
    run_sanity(tmp_path, ARTICLES, FakeEmbedder(), n=N)
    want = [json.loads(x) for x in (tmp_path / "sanity/results.jsonl").read_text().splitlines()]
    got = [x for x in lines if x["candidate"] == "article"]
    for g, w in zip(got, want, strict=True):
        for key in ("label", "query", "bm25_rank", "bm25_top1", "dense_rank", "dense_top1"):
            assert g[key] == w[key], key


def test_own_has_query_is_true_when_question_sits_in_chunk(lines):
    for x in lines:
        if x["candidate"] == "article":
            assert x["bm25_own_has_query"] and x["dense_own_has_query"]  # 질문 = 조문 첫 문장
            assert x["query"] == first_sentence(next(a for a in ARTICLES if a.label == x["label"]))
    for x in lines:  # 후보마다 own 청크 글자 수·포함 여부가 그 청크 텍스트와 맞는다
        by_path = {c.path: c for c in law_chunks(ROWS, x["candidate"])}
        for name in ("bm25", "dense"):
            c = by_path[x[f"{name}_own_path"]]
            assert x[f"{name}_own_chars"] == len(c.text)
            assert x[f"{name}_own_has_query"] == (x["query"] in c.text)
            assert x["query_chars"] == len(x["query"])


# ── Task 2 — golden 놓친 문항 ───────────────────────────────────────────


def _base(qid, hit, rank):
    return {
        "qid": qid, "question": f"질문 {qid}", "gold": ["제1조"],
        "hit@5": hit, "gold_rank": {"제1조": rank},
    }  # fmt: skip


def _cand(qid, hit, rank):
    return {"qid": qid, "hybrid": {"hit@5": hit, "gold_rank": {"제1조": rank}}}


def _pair(spec):
    """spec: [(#131 hit, #131 순위, 후보 hit, 후보 순위)]"""
    base = [_base(f"faq-{i}", b, br) for i, (b, br, _, _) in enumerate(spec)]
    cand = [_cand(f"faq-{i}", c, cr) for i, (_, _, c, cr) in enumerate(spec)]
    return base, cand


def test_compare_golden_counts_found_and_lost_with_ranks():
    base, cand = _pair([(0, 9, 1, 2), (0, 8, 0, 7), (1, 1, 0, 6), (1, 2, 1, 1)])
    got = miss.compare_golden(base, cand)
    assert (got["found_count"], got["lost_count"]) == (1, 1)
    assert got["found"] == [
        {
            "qid": "faq-0",
            "question": "질문 faq-0",
            "gold": ["제1조"],
            "base_rank": 9,
            "cand_rank": 2,
        }
    ]
    assert [(x["qid"], x["base_rank"], x["cand_rank"]) for x in got["lost"]] == [("faq-2", 1, 6)]


@pytest.mark.parametrize(
    ("found", "lost", "band"),
    [
        (3, 0, "찾은 것이 더 많다"),
        (5, 2, "찾은 것이 더 많다"),
        (2, 0, "차이 없음"),
        (0, 2, "차이 없음"),
        (0, 3, "놓친 것이 더 많다"),
        (4, 7, "놓친 것이 더 많다"),
    ],
)
def test_golden_band_boundaries(found, lost, band):
    assert miss.golden_band(found, lost) == band


def test_compare_golden_band_comes_from_f_minus_l():
    spec = [(0, 9, 1, 1)] * 3 + [(1, 1, 1, 1)]
    assert miss.compare_golden(*_pair(spec))["band"] == "찾은 것이 더 많다"  # F−L = 3
    spec = [(1, 1, 0, 9)] * 3 + [(0, 9, 0, 9)]
    assert miss.compare_golden(*_pair(spec))["band"] == "놓친 것이 더 많다"  # F−L = −3
    spec = [(0, 9, 1, 1)] * 2 + [(1, 1, 0, 9)] * 0
    assert miss.compare_golden(*_pair(spec))["band"] == "차이 없음"  # F−L = 2


def test_compare_golden_rejects_different_questions():
    base, cand = _pair([(0, 9, 1, 1), (1, 1, 1, 1)])
    with pytest.raises(ValueError, match="qid"):
        miss.compare_golden(base, cand[::-1])


def test_golden_misses_reads_run_files(tmp_path):
    base, cand = _pair([(0, 9, 1, 1), (1, 1, 0, 5), (0, 4, 0, 4)])
    (tmp_path / "hybrid").mkdir()
    (tmp_path / "hybrid/results.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in base), encoding="utf-8"
    )
    (tmp_path / "73/article").mkdir(parents=True)
    (tmp_path / "73/article/results.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cand), encoding="utf-8"
    )
    got = miss.golden_misses(tmp_path, candidates=("article",))
    assert got["missed"] == ["faq-0", "faq-2"]
    art = got["candidates"]["article"]
    assert (art["found_count"], art["lost_count"]) == (1, 1)


# ── Task 3 — 원인 ───────────────────────────────────────────────────────


def test_bm25_terms_matches_hand_calculation():
    docs = [Article("가", "", "a b b"), Article("나", "", "c d")]
    bm = BM25(docs, tokenizer=str.split)
    got = miss.bm25_terms(bm, "a b x", "가")
    idf = math.log((2 - 1 + 0.5) / (1 + 0.5) + 1)
    norm = 1.2 * (1 - 0.75 + 0.75 * 3 / 2.5)
    assert set(got) == {"a", "b"}  # x는 어느 문서에도 없다
    assert got["a"] == pytest.approx(idf * 1 * 2.2 / (1 + norm))
    assert got["b"] == pytest.approx(idf * 2 * 2.2 / (2 + norm))
    assert list(got) == ["b", "a"]  # 기여가 큰 순서
    assert miss.bm25_terms(bm, "a", "나") == {}  # 그 문서에 없는 낱말은 기여 0


def test_bm25_term_contributions_sum_to_scores():
    bm = BM25(ARTICLES)
    for q in ("청약 자격은 나이와 소득으로 정한다.", "순위는 가입 기간 추첨", "없는낱말"):
        scores = bm.scores(q)
        for a in ARTICLES:
            total = sum(miss.bm25_terms(bm, q, a.label).values())
            assert abs(total - scores[bm.labels.index(a.label)]) < miss.SUM_TOLERANCE


def _fake_miss(name, label, top1, rank):
    """`article` 점검 줄 하나. 자기 순위·1위만 채운 합성 줄 — build_causes가 읽는 값이다."""
    q = first_sentence(next(a for a in ARTICLES if a.label == label))
    line = {"candidate": "article", "label": label, "query": q}
    for r in ("bm25", "dense", "hybrid"):
        line[f"{r}_rank"] = 1
        line[f"{r}_top1"] = label
    line[f"{name}_rank"], line[f"{name}_top1"] = rank, top1
    return line


def test_causes_cover_only_missed_retrievers_of_article_candidate():
    lines = [_fake_miss("bm25", "제3조", "제4조", 2), _fake_miss("dense", "제6조", "제1조", 4)]
    lines += [{**lines[0], "candidate": "item"}]  # article 외 후보는 원인 대상이 아니다
    got = miss.build_causes(lines, ARTICLES, ROWS, FakeEmbedder())
    assert [(c["retriever"], c["label"], c["top1"]) for c in got] == [
        ("bm25", "제3조", "제4조"),
        ("dense", "제6조", "제1조"),
    ]
    assert (
        miss.build_causes([_fake_miss("bm25", "제3조", "제3조", 1)], ARTICLES, ROWS, FakeEmbedder())
        == []
    )


def test_bm25_cause_numbers_match_scores_and_sentence_cites_them():
    bm = BM25(ARTICLES)
    (c,) = miss.build_causes(
        [_fake_miss("bm25", "제3조", "제4조", 2)], ARTICLES, ROWS, FakeEmbedder()
    )
    scores = bm.scores(c["query"])
    assert c["own_score"] == pytest.approx(scores[2]) and c["top1_score"] == pytest.approx(
        scores[3]
    )
    assert c["own_terms_gap"] < miss.SUM_TOLERANCE and c["top1_terms_gap"] < miss.SUM_TOLERANCE
    assert c["own_chars"] == len(ARTICLES[2].text) and c["top1_tokens"] == bm.lengths[3]
    assert c["median_chars"] == statistics.median(len(a.text) for a in ARTICLES)
    assert miss.cites_number(c) and f"{c['own_score']:.3f}" in c["sentence"]


def test_dense_cause_cosines_and_best_item_chunk():
    emb = FakeEmbedder()
    (c,) = miss.build_causes([_fake_miss("dense", "제4조", "제1조", 3)], ARTICLES, ROWS, emb)
    qv = emb.embed([c["query"]])[0]
    cos = lambda t: float(  # noqa: E731
        (v := emb.embed([t])[0]) @ qv / (np.linalg.norm(v) * np.linalg.norm(qv))
    )
    assert c["own_cos"] == pytest.approx(cos(ARTICLES[3].text))
    assert c["top1_cos"] == pytest.approx(cos(ARTICLES[0].text))
    own_items = [ch for ch in law_chunks(ROWS, "item") if ch.label == "제4조"]
    assert c["item_best_cos"] == pytest.approx(max(cos(ch.text) for ch in own_items))
    assert c["item_best_path"] in {ch.path for ch in own_items}
    assert miss.cites_number(c)


def test_cites_number_fails_when_any_number_is_missing_or_only_a_substring():
    bm25 = {"retriever": "bm25", "own_score": 32.079, "top1_score": 34.426}
    assert miss.cites_number({**bm25, "sentence": "점수 32.079, 1위 34.426."})
    assert not miss.cites_number({**bm25, "sentence": "점수 32.079."})  # 1위 점수가 없다
    other = {**bm25, "sentence": "점수 132.0791, 1위 34.426."}  # 다른 수의 일부
    assert not miss.cites_number(other)
    dense = {"retriever": "dense", "own_cos": 0.5, "top1_cos": 0.6, "item_best_cos": 1.0}
    assert miss.cites_number({**dense, "sentence": "0.500 / 0.600 / 1.000"})
    assert not miss.cites_number({**dense, "sentence": "0.500 / 0.600 / 10.000"})


# ── Task 4 — 리포트와 실행 진입점 ────────────────────────────────────────


def _sl(cand, label, ranks, chars=100, has=True):
    """합성 점검 줄. ranks = (bm25, dense, hybrid) 자기 순위."""
    line = {"candidate": cand, "label": label, "query": "q", "query_chars": 30}
    for r, k in zip(("bm25", "dense", "hybrid"), ranks, strict=True):
        line |= {f"{r}_rank": k, f"{r}_top1": label if k == 1 else "제9조"}
    for r in ("bm25", "dense"):
        line |= {f"{r}_own_path": label, f"{r}_own_chars": chars, f"{r}_own_has_query": has}
    return line


# article은 제2조 bm25와 제3조 dense를 놓친다(2건). 후보마다 찾은 수가 0·1·2
SYN = [
    *[_sl("article", "제1조", (1, 1, 1)), _sl("article", "제2조", (3, 1, 2))],
    _sl("article", "제3조", (1, 4, 2)),
    *[_sl("paragraph", "제1조", (1, 1, 1)), _sl("paragraph", "제2조", (3, 1, 2))],
    _sl("paragraph", "제3조", (1, 5, 2)),
    *[_sl("paragraph+head", "제1조", (1, 1, 1)), _sl("paragraph+head", "제2조", (1, 1, 1), 40)],
    _sl("paragraph+head", "제3조", (1, 5, 2)),
    *[_sl("item", "제1조", (1, 1, 1)), _sl("item", "제2조", (1, 1, 1), 40, False)],
    _sl("item", "제3조", (1, 1, 1), 55),
    *[_sl("item+head", "제1조", (1, 1, 1)), _sl("item+head", "제2조", (1, 1, 1), 60)],
    _sl("item+head", "제3조", (1, 1, 1), 70),
]


@pytest.mark.parametrize(
    ("found", "total", "band"),
    [
        (4, 4, "찾음"),
        (3, 4, "일부 찾음"),
        (1, 4, "일부 찾음"),
        (0, 4, "못 찾음"),
        (0, 0, "해당 없음"),
    ],
)
def test_band_a(found, total, band):
    assert miss.band_a(found, total) == band


def test_summarize_a_counts_found_among_article_misses():
    a = miss.summarize_a(SYN)
    assert a["n"] == 3 and a["misses"] == [("bm25", "제2조"), ("dense", "제3조")]
    c = a["candidates"]
    assert c["article"]["ranks"] == [3, 4] and c["article"]["band"] == "못 찾음"
    assert c["paragraph"]["found"] == 0
    assert (c["paragraph+head"]["found"], c["paragraph+head"]["band"]) == (1, "일부 찾음")
    assert c["paragraph+head"]["top1_chars"] == [40]
    assert (c["item"]["found"], c["item"]["band"]) == (2, "찾음")
    assert c["item"]["top1_has_query"] == 1 and c["item"]["top1_chars"] == [40, 55]
    assert c["item+head"]["query_chars"] == [30, 30]
    assert a["candidates"]["article"]["top1"] == {"bm25": 2, "dense": 2, "hybrid": 1}


def test_reproduce_reports_every_differing_field():
    art = [x for x in SYN if x["candidate"] == "article"]
    same = [{k: x[k] for k in miss.REPRO_KEYS} for x in art]
    assert miss.reproduce(art, same)["diffs"] == []
    changed = [{**s} for s in same]
    changed[1]["dense_rank"] = 2
    got = miss.reproduce(art, changed)
    assert [(d["label"], d["key"], d["now"], d["before"]) for d in got["diffs"]] == [
        ("제2조", "dense_rank", 1, 2)
    ]
    assert miss.reproduce(art, same[:2])["diffs"][0]["key"] == "질문 수"


def _golden_syn():
    """F = 2, L = 3 → 찾은 것도 놓친 것도 3 미만. `article`은 #131과 같은 줄을 낸 것으로 둔다."""
    spec = [(0, 9, 1, 1)] * 2 + [(0, 9, 0, 9)] + [(1, 1, 0, 9)] * 3 + [(1, 1, 1, 1)]
    base, cand = _pair(spec)
    same = [_cand(x["qid"], x["hit@5"], x["gold_rank"]["제1조"]) for x in base]
    per = {c: miss.compare_golden(base, same if c == "article" else cand) for c in CANDIDATES}
    return {"total": len(base), "missed": ["faq-0", "faq-1", "faq-2"], "candidates": per}


@pytest.fixture(scope="module")
def report():
    causes = miss.build_causes(
        [_fake_miss("bm25", "제3조", "제4조", 2), _fake_miss("dense", "제6조", "제1조", 4)],
        ARTICLES,
        ROWS,
        FakeEmbedder(),
    )
    repro = miss.reproduce([x for x in SYN if x["candidate"] == "article"], [])
    return miss.build_report(SYN, _golden_syn(), causes, repro)


def test_report_sections_in_order(report):
    heads = [x for x in report.splitlines() if x.startswith("## ")]
    assert [h.split(".")[0] for h in heads] == ["## 1", "## 2", "## 3", "## 4"]
    assert (
        "묶음 A" in heads[0] and "묶음 B" in heads[1] and "원인" in heads[2] and "재현" in heads[3]
    )


def test_first_line_is_one_sentence_naming_all_four_candidates(report):
    first = report.splitlines()[0]
    for cand in CANDIDATES[1:]:
        assert f"`{cand}`" in first
    assert first.endswith(".") and not first.startswith("# ")
    assert "일부 찾음" in first and "차이 없음" in first  # 구간 이름이 들어 있다


def test_conclusion_reads_each_candidates_own_values():
    counts = {"article": (0, 0), "paragraph": (6, 18), "paragraph+head": (4, 12)}
    counts |= {"item": (8, 10), "item+head": (6, 7)}
    bands = ["차이 없음", "놓친 것이 더 많다", "놓친 것이 더 많다", "차이 없음", "차이 없음"]
    golden = {
        "missed": list(range(20)),
        "candidates": {
            c: {"found_count": f, "lost_count": lo, "band": b}
            for (c, (f, lo)), b in zip(counts.items(), bands, strict=True)
        },
    }
    first = miss._conclusion(miss.summarize_a(SYN), golden)
    assert "`paragraph` F 6 · L 18(놓친 것이 더 많다)" in first
    assert "`paragraph+head` F 4 · L 12(놓친 것이 더 많다)" in first
    assert "`item` F 8 · L 10(차이 없음)" in first
    assert "`item+head` F 6 · L 7(차이 없음)" in first
    assert "(비교: `article` F 0 · L 0)" in first
    assert "`paragraph` 0건(못 찾음)" in first and "`item` 2건(찾음)" in first  # SYN의 A 값


def test_section_notes_are_at_the_top_of_each_section(report):
    a = report.split("## 1.")[1].split("## 2.")[0]
    b = report.split("## 2.")[1].split("## 3.")[0]
    top = a.split("###")[0]
    assert (
        "`article` 후보에서는 3개 모두 자기 조 청크 안에 글자 그대로 있다" in top
    )  # SYN은 질문 3개
    assert "다른 후보에서는" in top
    assert "이미 커밋된 run을 다시 읽은 값이다" in b.split("###")[0]
    assert "plan을 쓰기 전에 이 값을 이미 알았고" in b.split("###")[0]


def test_report_has_no_judgment_words_and_article_baseline_values(report):
    assert "개선" not in report and "우수" not in report
    assert "`article` 0건" in report.splitlines()[0]  # 숫자 옆에 비교 기준이 붙는다


def test_causes_section_states_checks(report):
    section = report.split("## 3.")[1].split("## 4.")[0]
    assert "숫자를 인용하지 않은 원인 문장: 0건" in section and "최대" in section


def test_causes_section_says_unchecked_when_no_bm25_cause():
    dense_only = miss.build_causes(
        [_fake_miss("dense", "제6조", "제1조", 4)], ARTICLES, ROWS, FakeEmbedder()
    )
    repro = miss.reproduce([x for x in SYN if x["candidate"] == "article"], [])
    report = miss.build_report(SYN, _golden_syn(), dense_only, repro)
    section = report.split("## 3.")[1].split("## 4.")[0]
    assert "검산하지 않았다" in section and "최대" not in section


def test_main_exits_nonzero_when_a_cause_sentence_lacks_its_numbers(env, monkeypatch):
    law, runs, out = env
    monkeypatch.setattr(miss, "cites_number", lambda cause: False)
    # env 점검 줄에는 article 놓친 건이 없어 원인 문장이 안 만들어진다 — 합성 원인을 넣는다
    cause = miss.build_causes(
        [_fake_miss("bm25", "제3조", "제4조", 2)], ARTICLES, ROWS, FakeEmbedder()
    )
    monkeypatch.setattr(miss, "build_causes", lambda *args, **kwargs: cause)
    assert miss.main(runs, out, FakeEmbedder(), law, n=N) == 1


def test_main_exits_nonzero_when_term_gap_is_nan(env, monkeypatch):
    law, runs, out = env
    (cause,) = miss.build_causes(
        [_fake_miss("bm25", "제3조", "제4조", 2)], ARTICLES, ROWS, FakeEmbedder()
    )
    nan_cause = {**cause, "own_terms_gap": float("nan")}
    monkeypatch.setattr(miss, "build_causes", lambda *args, **kwargs: [nan_cause])
    assert miss.main(runs, out, FakeEmbedder(), law, n=N) == 1


# main — 가짜 임베더와 tmp 법령 파일로 처음부터 끝까지


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


@pytest.fixture
def env(tmp_path):
    law = tmp_path / "law.jsonl"
    _write_jsonl(law, ROWS)
    runs = tmp_path / "runs"
    base, cand = _pair([(0, 9, 1, 1), (1, 1, 0, 8), (0, 7, 0, 7), (1, 1, 1, 1)])
    _write_jsonl(runs / "hybrid/results.jsonl", base)
    for c in CANDIDATES:
        _write_jsonl(runs / f"73/{c}/results.jsonl", cand)
    run_sanity(runs, ARTICLES, FakeEmbedder(), n=N)  # #131 점검 run
    return law, runs, tmp_path / "report.md"


def test_main_writes_runs_and_report_and_second_run_is_identical(env):
    law, runs, out = env
    emb = FakeEmbedder()
    assert miss.main(runs, out, emb, law, n=N) == 0
    names = ("sanity.jsonl", "golden_misses.json", "causes.json")
    assert all((runs / "138" / f).exists() for f in names)
    assert len((runs / "138/sanity.jsonl").read_text().splitlines()) == len(CANDIDATES) * N
    first = {f: (runs / "138" / f).read_bytes() for f in names} | {"report": out.read_bytes()}
    assert miss.main(runs, out, FakeEmbedder(), law, n=N) == 0
    second = {f: (runs / "138" / f).read_bytes() for f in names} | {"report": out.read_bytes()}
    assert first == second


def test_main_exits_nonzero_when_article_run_differs_from_sanity(env):
    law, runs, out = env
    rows = (runs / "sanity/results.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    first["bm25_rank"] += 7
    rows[0] = json.dumps(first, ensure_ascii=False)
    (runs / "sanity/results.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert miss.main(runs, out, FakeEmbedder(), law, n=N) == 1
    assert "bm25_rank" in out.read_text()  # 다른 값이 리포트에 남는다
