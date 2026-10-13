"""OpenAI 임베딩 + 디스크 캐시 (#131).

`data/cache/embed-<model>.jsonl` — 텍스트 sha256 → 벡터. 캐시에 없는 것만 한 요청에 묶어 보낸다.
두 번째 실행은 API를 안 부르므로 같은 입력의 결과가 같다(재현성).
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from cheongyak_rag.config import settings

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"
BATCH = 256  # 한 요청의 입력 수. OpenAI 한도(2048개)보다 훨씬 작게 둔다


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_path_for(model: str) -> Path:
    return CACHE_DIR / f"embed-{model}.jsonl"


class Embedder:
    def __init__(
        self,
        model: str | None = None,
        cache_path: Path | None = None,
        client=None,
        api_key: str | None = None,
    ):
        self.model = model or settings.openai_embed_model
        self.cache_path = cache_path or cache_path_for(self.model)
        self.api_key = settings.openai_api_key if api_key is None else api_key
        self._client = client
        self.api_calls = 0
        self.cache: dict[str, list[float]] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                if line:
                    row = json.loads(line)
                    self.cache[row["sha256"]] = row["vec"]

    def _get_client(self):
        if self._client is None:
            if not self.api_key.strip():
                # 비면 다른 값으로 대신하지 않는다 — 재시도로 풀리지 않는 오류다
                raise RuntimeError("OPENAI_API_KEY가 비어 있다. 셸 환경변수에 넣을 것")
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def embed(self, texts: list[str]) -> np.ndarray:
        missing = list(dict.fromkeys(t for t in texts if text_key(t) not in self.cache))
        if missing:
            client = self._get_client()
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as f:
                for i in range(0, len(missing), BATCH):
                    chunk = missing[i : i + BATCH]
                    resp = client.embeddings.create(model=self.model, input=chunk)
                    self.api_calls += 1
                    for text, item in zip(chunk, resp.data, strict=True):
                        vec = [float(x) for x in item.embedding]
                        self.cache[text_key(text)] = vec
                        f.write(json.dumps({"sha256": text_key(text), "vec": vec}) + "\n")
        return np.array([self.cache[text_key(t)] for t in texts], dtype=np.float64)
