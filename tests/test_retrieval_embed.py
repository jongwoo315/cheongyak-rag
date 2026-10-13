import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from cheongyak_rag.retrieval.embed import Embedder, text_key


class FakeClient:
    """OpenAI 클라이언트 흉내. 호출 횟수와 보낸 입력을 센다."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, *, model, input):
        self.calls.append(list(input))
        data = [SimpleNamespace(embedding=[float(len(t)), 1.0, 0.5]) for t in input]
        return SimpleNamespace(data=data)


def test_returns_matrix_in_input_order(tmp_path):
    emb = Embedder("m", tmp_path / "c.jsonl", client=FakeClient())
    out = emb.embed(["가", "가나다", "가나"])
    assert out.shape == (3, 3)
    assert out[:, 0].tolist() == [1.0, 3.0, 2.0]


def test_batches_in_one_request(tmp_path):
    client = FakeClient()
    Embedder("m", tmp_path / "c.jsonl", client=client).embed(["a", "b", "c"])
    assert len(client.calls) == 1 and client.calls[0] == ["a", "b", "c"]


def test_cache_hit_makes_no_api_call(tmp_path):
    path = tmp_path / "c.jsonl"
    first = Embedder("m", path, client=FakeClient())
    a = first.embed(["가", "나"])
    client = FakeClient()
    second = Embedder("m", path, client=client)
    b = second.embed(["나", "가"])
    assert client.calls == [] and second.api_calls == 0
    assert np.array_equal(a, b[::-1])


def test_only_missing_texts_are_sent(tmp_path):
    path = tmp_path / "c.jsonl"
    Embedder("m", path, client=FakeClient()).embed(["가"])
    client = FakeClient()
    Embedder("m", path, client=client).embed(["가", "나", "나"])
    assert client.calls == [["나"]]  # 캐시에 있는 것·중복은 안 보낸다


def test_cache_key_is_sha256_of_text(tmp_path):
    path = tmp_path / "c.jsonl"
    Embedder("m", path, client=FakeClient()).embed(["가"])
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["sha256"] == hashlib.sha256("가".encode()).hexdigest() == text_key("가")


def test_cached_run_does_not_need_a_client_or_key(tmp_path):
    path = tmp_path / "c.jsonl"
    Embedder("m", path, client=FakeClient()).embed(["가"])
    emb = Embedder("m", path, client=None, api_key="")
    emb.embed(["가"])  # 캐시만 읽으니 키가 없어도 된다
    assert emb.api_calls == 0


def test_missing_key_stops_when_api_is_needed(tmp_path):
    emb = Embedder("m", tmp_path / "c.jsonl", client=None, api_key="")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        emb.embed(["가"])


def test_torn_last_cache_line_is_ignored_and_refetched(tmp_path):
    path = tmp_path / "c.jsonl"
    Embedder("m", path, client=FakeClient()).embed(["가"])
    with path.open("a", encoding="utf-8") as f:
        f.write('{"sha256": "abc", "vec": [1.0,')  # 쓰다 끊긴 줄
    client = FakeClient()
    Embedder("m", path, client=client).embed(["가", "나"])
    assert client.calls == [["나"]]
