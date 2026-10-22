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


class FakeChat:
    """`client.chat.completions.create(**kw)`를 흉내 낸다. 호출을 `calls`에 기록한다.

    replies의 원소: JSON 문자열(응답 content) · 예외(던진다) · 함수(kw → 위 둘).
    다 쓰면 마지막을 되풀이한다.
    """

    def __init__(self, replies, prompt_tokens=1000, completion_tokens=100):
        from types import SimpleNamespace

        self.replies = list(replies)
        self.calls = []
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        from types import SimpleNamespace

        self.calls.append(kw)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if callable(reply):
            reply = reply(kw)
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        usage = SimpleNamespace(
            prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
