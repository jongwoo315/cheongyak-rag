"""#131 리뷰 1차 #9에서 미룬 테스트 둘 (#138).

- `evaluate_run` 출력을 `compare.build_report`에 그대로 넣으면 리포트가 만들어진다
- `Embedder` + `write_run`을 두 번 돌리면 두 번째는 OpenAI를 안 부르고 `results.jsonl`이
  바이트까지 같다
"""

import hashlib
import json
from types import SimpleNamespace

from cheongyak_rag.retrieval.compare import build_report
from cheongyak_rag.retrieval.corpus import Article
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.evaluate import evaluate_run, run_sanity, write_run
from cheongyak_rag.retrieval.golden import GoldenResult
from tests.fakes import FakeEmbedder

TOPICS = "나이 소득 자산 순위 추첨 가입 기간 세대 지역 면적 가점 부양".split()
ARTICLES = [
    Article(
        f"제{i}조", f"제목{i}", f"제{i}조(제목{i})\n{t} 기준은 {t}에 따라 정한다. {t} 관련 요건"
    )
    for i, t in enumerate(TOPICS, 1)
]
GOLDEN = [
    {
        "qid": f"faq-{i}",
        "q_no": i,
        "question": f"{TOPICS[i - 1]} 기준이 뭔가요?",
        "gold": [f"제{i}조"],
        "has_article_in_question": False,
    }
    for i in range(1, len(TOPICS) + 1)
]


class FakeOpenAI:
    """OpenAI 클라이언트 흉내 — 텍스트 해시로 벡터를 만들고 호출 횟수를 센다."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, *, model, input):
        self.calls.append(list(input))
        vec = lambda t: [b / 255 + 0.01 for b in hashlib.sha256(t.encode()).digest()[:16]]  # noqa: E731
        return SimpleNamespace(data=[SimpleNamespace(embedding=vec(t)) for t in input])


def test_evaluate_run_output_feeds_build_report(tmp_path):
    results = {
        run: evaluate_run(run, GOLDEN, ARTICLES, FakeEmbedder())
        for run in ("bm25", "dense", "hybrid")
    }
    run_sanity(tmp_path, ARTICLES, FakeEmbedder(), n=4)
    sanity = [json.loads(x) for x in (tmp_path / "sanity/results.jsonl").read_text().splitlines()]
    report = build_report(results, GoldenResult(), ARTICLES, sanity)
    assert report.splitlines()[0].startswith("hybrid가 dense보다 recall@5가 ")
    heads = [x for x in report.splitlines() if x.startswith("## ")]
    assert [h.split(".")[0] for h in heads[:7]] == [f"## {i}" for i in range(1, 8)]
    assert "## 9. 점검 run" in report and "BM25 4/4" in report  # 점검 절까지 만들어진다


def test_second_write_run_makes_no_api_call_and_results_are_byte_identical(tmp_path):
    cache = tmp_path / "embed.jsonl"
    out = {}
    for attempt in ("first", "second"):
        client = FakeOpenAI()
        emb = Embedder("m", cache, client=client)
        for run in ("dense", "hybrid"):
            lines = evaluate_run(run, GOLDEN, ARTICLES, emb)
            write_run(tmp_path / attempt, run, lines, ARTICLES, emb)
        out[attempt] = (client.calls, emb.api_calls)
    assert out["first"][1] > 0  # 첫 실행은 캐시가 비어 있어 API를 부른다
    assert out["second"] == ([], 0)
    for run in ("dense", "hybrid"):
        a = (tmp_path / "first" / run / "results.jsonl").read_bytes()
        b = (tmp_path / "second" / run / "results.jsonl").read_bytes()
        assert a == b
        config = json.loads((tmp_path / "second" / run / "config.json").read_text())
        assert config["embedding_api_calls"] == 0
