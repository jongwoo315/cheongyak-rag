import hashlib

import numpy as np


class FakeEmbedder:
    """텍스트 해시로 만든 벡터. API를 안 부른다."""

    model = "fake"

    def __init__(self):
        self.api_calls = 0
        self.cache = {}
        self.calls = []

    def embed(self, texts):
        self.calls.append(len(texts))
        out = []
        for t in texts:
            if t not in self.cache:
                h = hashlib.sha256(t.encode()).digest()
                self.cache[t] = [(b + 1) / 256 for b in h[:16]]
            out.append(self.cache[t])
        return np.array(out, dtype=np.float64)
