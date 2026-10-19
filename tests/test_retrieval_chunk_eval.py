import json

from cheongyak_rag.retrieval import chunk_eval as ce
from cheongyak_rag.retrieval.chunk import Chunk, law_chunks, load_law_rows
from cheongyak_rag.retrieval.corpus import Article, load_articles
from cheongyak_rag.retrieval.evaluate import evaluate_run
from cheongyak_rag.retrieval.search import tokenize
from tests.fakes import FakeEmbedder


def _c(label, path, text="본문"):
    return Chunk(f"law:{path}", label, path, text, "law", {})


# ── 청크 순위 → 조 순위 ─────────────────────────────────────────────────


def test_article_ranking_keeps_only_first_chunk_of_each_article():
    ranking = [_c("제2조", "제2조제4호"), _c("제5조", "제5조"), _c("제2조", "제2조제1호")]
    assert ce.article_ranking(ranking) == ["제2조", "제5조"]


def test_article_view_returns_path_of_highest_chunk():
    ranking = [
        _c("제5조", "제5조제2항"),
        _c("제2조", "제2조제4호"),
        _c("제5조", "제5조제1항"),
        _c("제2조", "제2조제1호"),
    ]
    labels, paths = ce.article_view(ranking)
    assert labels == ["제5조", "제2조"]
    assert paths == {"제5조": "제5조제2항", "제2조": "제2조제4호"}


# ── 후보 하나 평가 ──────────────────────────────────────────────────────

ARTS = [
    Article("제1조", "목적", "제1조(목적)\n주택 공급 목적을 정한다."),
    Article(
        "제2조", "정의", "제2조(정의)\n무주택세대구성원 정의를 정한다.\n세대란 사람의 집단이다."
    ),
    Article("제3조", "자격", "제3조(자격)\n청약 자격은 나이와 소득으로 정한다."),
]
GOLDEN = [
    {
        "qid": "faq-1",
        "q_no": 1,
        "question": "무주택세대구성원 정의",
        "gold": ["제2조"],
        "has_article_in_question": False,
    },
    {
        "qid": "faq-2",
        "q_no": 2,
        "question": "청약 자격 나이",
        "gold": ["제3조", "제1조"],
        "has_article_in_question": False,
    },
]


def _article_chunks():
    return [_c(a.label, a.label, a.text) for a in ARTS]


def test_article_candidate_matches_evaluate_run_ranks():
    emb = FakeEmbedder()
    got = ce.evaluate_candidate(_article_chunks(), GOLDEN, emb)
    for run in ("bm25", "dense", "hybrid"):
        want = evaluate_run(run, GOLDEN, ARTS, FakeEmbedder())
        for g, w in zip(got, want, strict=True):
            assert g[run]["gold_rank"] == w["gold_rank"], run
            assert g[run]["recall@5"] == w["recall@5"], run
            assert g[run]["mrr"] == w["mrr"], run
    assert [g["top5"] for g in got] == [
        w["top5"] for w in evaluate_run("hybrid", GOLDEN, ARTS, FakeEmbedder())
    ]


def test_embedding_runs_once_with_chunks_and_questions_and_no_api():
    emb = FakeEmbedder()
    ce.evaluate_candidate(_article_chunks(), GOLDEN, emb)
    assert emb.calls == [len(ARTS) + len(GOLDEN)]
    assert emb.api_calls == 0


def test_two_chunks_of_same_article_count_once_in_ranking():
    chunks = [
        _c("제1조", "제1조", "주택 공급 목적"),
        _c("제2조", "제2조제1호", "무주택세대구성원 정의"),
        _c("제2조", "제2조제2호", "세대 정의 집단"),
        _c("제3조", "제3조", "청약 자격 나이"),
    ]
    lines = ce.evaluate_candidate(chunks, GOLDEN[:1], FakeEmbedder())
    assert len(lines[0]["top5"]) == len(set(lines[0]["top5"])) == 3
    d = lines[0]["gold_detail"]["제2조"]
    assert d["bm25"] == 1  # 정의 질문에 두 청크 중 높은 쪽이 조 순위
    assert d["path"] in ("제2조제1호", "제2조제2호")


def test_gold_detail_has_three_ranks_and_hand_computed_hybrid():
    lines = ce.evaluate_candidate(_article_chunks(), GOLDEN, FakeEmbedder())
    d = lines[0]["gold_detail"]["제2조"]
    assert set(d) == {"bm25", "dense", "hybrid", "path"}
    assert d["bm25"] == 1
    # 순위 1·dense r 의 RRF는 순서만 본다. hybrid 순위는 hybrid.gold_rank와 같다
    assert d["hybrid"] == lines[0]["hybrid"]["gold_rank"]["제2조"]
    assert lines[0]["hybrid"]["hit@1"] == int(lines[0]["top5"][0] == "제2조")


def test_path_is_from_better_ranking_ties_to_bm25():
    chunks = [
        _c("제2조", "제2조제1호", "무주택세대구성원 정의"),
        _c("제2조", "제2조제2호", "다른 내용"),
        _c("제3조", "제3조", "청약 자격 나이"),
    ]
    line = ce.evaluate_candidate(chunks, GOLDEN[:1], FakeEmbedder())[0]
    assert line["gold_detail"]["제2조"]["path"] == "제2조제1호"


def test_results_are_deterministic_bytes():
    a = ce.dump_lines(ce.evaluate_candidate(_article_chunks(), GOLDEN, FakeEmbedder()))
    b = ce.dump_lines(ce.evaluate_candidate(_article_chunks(), GOLDEN, FakeEmbedder()))
    assert a == b
    assert all(json.loads(x)["qid"] for x in a.splitlines())


# ── 파일과 CLI ──────────────────────────────────────────────────────────


def test_write_candidate_run_writes_results_and_config(tmp_path):
    emb = FakeEmbedder()
    chunks = _article_chunks()
    lines = ce.evaluate_candidate(chunks, GOLDEN, emb)
    ce.write_candidate_run(tmp_path, "article", lines, chunks, emb, new_texts=5)
    out = tmp_path / "article"
    assert len((out / "results.jsonl").read_text().splitlines()) == 2
    cfg = json.loads((out / "config.json").read_text())
    assert cfg["candidate"] == "article"
    assert cfg["chunk_count"] == 3
    assert cfg["question_count"] == 2
    assert cfg["model"] == "fake"
    assert (cfg["k1"], cfg["b"], cfg["rrf_k"]) == (1.2, 0.75, 60)
    assert cfg["embedding_api_calls"] == 0
    assert cfg["new_embedded_texts"] == 5
    assert {"run_at", "commit"} <= set(cfg)


def test_cli_article_on_real_data_writes_123_lines(tmp_path):
    emb = FakeEmbedder()
    rc = ce.main(["--candidate", "article"], runs_dir=tmp_path, embedder=emb)
    assert rc == 0
    lines = (tmp_path / "article" / "results.jsonl").read_text().splitlines()
    assert len(lines) == 123
    arts = load_articles()
    assert json.loads(lines[0])["top5"][0] in {a.label for a in arts}


def test_real_item_chunks_every_article_has_a_chunk():
    labels = {a.label for a in load_articles()}
    for cand in ("paragraph", "item+head"):
        got = {c.label for c in law_chunks(load_law_rows(), cand)}
        assert got == labels
    assert tokenize("무주택세대구성원")  # kiwi가 돈다


# ── FAQ (leave-self-out) ────────────────────────────────────────────────


def _faq_chunk(q_no, question, answer, cited=()):
    return Chunk(
        f"faq:{q_no}",
        f"Q{q_no}",
        f"Q{q_no}",
        f"{question}\n{answer}",
        "faq",
        {"q_no": q_no, "cited": list(cited)},
    )


FAQ = [
    _faq_chunk(1, "무주택세대구성원 정의가 뭔가요", "세대원 전원이 무주택인 세대", ["제2조"]),
    _faq_chunk(2, "청약 자격 나이가 어떻게 되나요", "만 19세 이상 소득 기준", ["제3조"]),
    _faq_chunk(3, "무주택세대구성원 정의가 뭔가요", "같은 질문 다른 답", ["제2조"]),
    _faq_chunk(4, "무주택 세대 기준 알려주세요", "세대 전원 무주택 요건", ["제2조", "제9조"]),
    _faq_chunk(5, "공급 목적이 뭔가요", "주택 공급 목적 규정", ["제1조"]),
]
FAQ_GOLDEN = [
    {
        "qid": "faq-1",
        "q_no": 1,
        "question": "무주택세대구성원 정의가 뭔가요",
        "gold": ["제2조"],
        "has_article_in_question": False,
    },
    {
        "qid": "faq-2",
        "q_no": 2,
        "question": "청약 자격 나이가 어떻게 되나요",
        "gold": ["제3조"],
        "has_article_in_question": False,
    },
]


def test_faq_leave_self_out_removes_self_and_same_question_pairs():
    lines = ce.evaluate_faq(FAQ, FAQ_GOLDEN, FakeEmbedder())
    first = lines[0]
    assert first["excluded"] == [1, 3]
    for r in ce.RANKERS:
        assert not {1, 3} & set(first[r]["top5"]), r


def test_faq_hit_hand_computed():
    lines = ce.evaluate_faq(FAQ, FAQ_GOLDEN, FakeEmbedder())
    first = lines[0]
    # 남은 쌍은 2·4·5. 4번이 제2조를 인용해 정답과 겹친다. 2번은 제3조, 5번은 제1조
    assert first["bm25"]["top5"][0] == 4
    assert first["bm25"]["faq_hit@1"] == 1
    assert first["bm25"]["faq_hit@5"] == 1
    # 둘째 질문: 정답 제3조는 2번만 인용하고 2번이 자기 쌍이라 빠진다 → 맞힐 쌍이 없다
    second = lines[1]
    assert second["excluded"] == [2]
    for r in ce.RANKERS:
        assert second[r]["faq_hit@5"] == 0 and second[r]["faq_hit@1"] == 0


def test_faq_hit_at_5_counts_only_top5_not_hit_at_1():
    chunks = [
        _faq_chunk(i, f"질문{i} 번호", f"답{i}", ["제7조"] if i == 6 else []) for i in range(1, 8)
    ]
    g = [
        {
            "qid": "faq-1",
            "q_no": 1,
            "question": "질문1 번호",
            "gold": ["제7조"],
            "has_article_in_question": False,
        }
    ]
    line = ce.evaluate_faq(chunks, g, FakeEmbedder())[0]
    for r in ce.RANKERS:
        top5 = line[r]["top5"]
        assert line[r]["faq_hit@5"] == int(6 in top5)
        assert line[r]["faq_hit@1"] == int(top5[0] == 6)


def test_faq_without_leave_self_out_self_pair_is_top1():
    check = ce.self_check(FAQ, FAQ_GOLDEN, FakeEmbedder())
    assert check["n"] == 2
    assert check["self_top1"]["bm25"] == 1.0  # 가짜 임베더의 dense는 무작위라 bm25만 본다
    assert all(m["ranker"] != "bm25" for m in check["misses"])


def test_leak_count_zero_for_leave_self_out_and_detects_leak():
    lines = ce.evaluate_faq(FAQ, FAQ_GOLDEN, FakeEmbedder())
    assert ce.leak_count(lines) == 0
    lines[0]["dense"]["top5"][0] = 3  # 같은 질문 쌍이 새어 들어온 경우
    assert ce.leak_count(lines) == 1


def test_faq_results_deterministic():
    a = ce.dump_lines(ce.evaluate_faq(FAQ, FAQ_GOLDEN, FakeEmbedder()))
    b = ce.dump_lines(ce.evaluate_faq(FAQ, FAQ_GOLDEN, FakeEmbedder()))
    assert a == b


def test_cli_faq_writes_results_config_and_self_check(tmp_path):
    rc = ce.main(["--faq"], runs_dir=tmp_path, embedder=FakeEmbedder())
    assert rc == 0
    out = tmp_path / "faq"
    assert len((out / "results.jsonl").read_text().splitlines()) == 123
    sc = json.loads((out / "self_check.json").read_text())
    assert sc["n"] == 123 and sc["leak_count"] == 0
    assert set(sc["self_top1"]) == set(ce.RANKERS)
    cfg = json.loads((out / "config.json").read_text())
    assert cfg["chunk_count"] == 480


def test_leave_self_out_drops_self_pair_even_if_question_text_differs():
    g = [
        {**FAQ_GOLDEN[0], "question": "무주택세대구성원  정의가 뭔가요"}
    ]  # 공백이 달라 텍스트가 다르다
    line = ce.evaluate_faq(FAQ, g, FakeEmbedder())[0]
    assert 1 in line["excluded"]
    for r in ce.RANKERS:
        assert 1 not in line[r]["top5"]


def test_leak_count_counts_own_q_no_even_if_excluded_list_misses_it():
    line = {"q_no": 1, "excluded": [], **{r: {"top5": [1, 2]} for r in ce.RANKERS}}
    assert ce.leak_count([line]) == len(ce.RANKERS)
