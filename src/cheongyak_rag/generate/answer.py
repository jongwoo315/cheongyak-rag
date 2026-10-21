"""검색 결과로 인용 단 답 생성 (#139).

python -m cheongyak_rag.generate.answer "무주택세대구성원이란 무엇인가요?"

문맥(조 상위 k + FAQ 상위 n)을 라벨(`[제34조]` `[Q47]`)과 함께 모델에 주고, JSON schema로
`{abstain, answer, citations}`를 받는다. 문맥에 없는 라벨 인용은 `invalid_citations`로 옮기고,
유효 인용이 하나도 없는 답은 코드가 abstain으로 바꾼다(`forced_abstain`). 응답은 디스크 캐시에 둔다.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import Chunk, strip_head
from cheongyak_rag.retrieval.chunk_eval import RUNS73
from cheongyak_rag.retrieval.embed import CACHE_DIR, Embedder
from cheongyak_rag.retrieval.query import Index, selected_candidate

# 가격 $ / 1M 토큰 (입력, 출력).
# 출처: developers.openai.com/api/docs/models/gpt-5.4-mini, 2026-10-22 확인
PRICE_PER_1M = {"gpt-5.4-mini": (0.75, 4.50)}
MAX_COMPLETION_TOKENS = 1500
SHOW_CHARS = 300
REQUEST_TIMEOUT_S = 60
SHOW_SEARCH_CHARS = 80

SYSTEM = """\
너는 「주택공급에 관한 규칙」 안내 도우미다. 사용자 메시지의 문맥(규칙 조문과 국토교통부 FAQ)에 \
있는 내용으로만 한국어로 답한다. 문맥에 없는 지식은 쓰지 않는다.
- 답 문장 안에 근거를 문맥의 라벨 그대로 `[제34조]` `[Q47]` 꼴로 단다.
- `citations`에 답에서 쓴 라벨을 전부 넣는다. 문맥에 없는 라벨은 쓰지 않는다.
- 문맥이 질문의 답을 직접 주지 않으면(주택 청약과 무관한 질문, 이 규칙에 없는 내용) \
`abstain`을 true로 하고 `answer`에 왜 답할 수 없는지 한 문장만 쓴다. 이때 `citations`는 빈 배열이다.
- 추측하지 않는다. 문맥에 있는 요건·기한·숫자는 그대로 옮긴다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "abstain": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["abstain", "answer", "citations"],
    "additionalProperties": False,
}


class HardApiError(RuntimeError):
    """재시도로 풀리지 않는 API 오류(인증·권한·쿼터). 일괄 실행을 멈춘다."""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """표에 없는 모델이면 KeyError — 0으로 대신하면 비용 상한이 조용히 무력해진다."""
    in_p, out_p = PRICE_PER_1M[model]
    return (input_tokens * in_p + output_tokens * out_p) / 1_000_000


@dataclass
class Answer:
    question: str
    abstain: bool
    forced_abstain: bool = False
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    context_labels: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None


def build_messages(question: str, result: dict[str, list[Chunk]]) -> list[dict]:
    """[system, user]. 문맥은 조 → FAQ 순서이고 각 항목은 `[라벨] 본문`."""
    blocks = [f"[{c.label}] {c.text}" for c in result["law"] + result["faq"]]
    user = f"질문: {question}\n\n문맥:\n\n" + "\n\n".join(blocks)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def cache_key(model: str, messages: list[dict]) -> str:
    raw = f"{model}\n{messages[0]['content']}\n{messages[1]['content']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class GenCache:
    """`data/cache/gen-<model>.jsonl` — 키 → {content, input_tokens, output_tokens, latency_s}."""

    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[str, dict] = {}
        if path.exists():
            good, bad = [], 0
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self.rows[row["key"]] = row["value"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    bad += 1  # 추가 도중 끊긴 줄. 그 질문은 다시 부른다
                    continue
                good.append(line)
            if bad:
                # 끊긴 줄을 둔 채 이어 쓰면 다음 행이 그 줄에 붙어 같이 못 읽게 된다
                print(f"생성 캐시 {path}: 깨진 줄 {bad}개를 지운다", file=sys.stderr)
                path.write_text("".join(g + "\n" for g in good), encoding="utf-8")

    def get(self, key: str) -> dict | None:
        return self.rows.get(key)

    def put(self, key: str, value: dict) -> None:
        self.rows[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")


def cache_path_for(model: str) -> Path:
    return CACHE_DIR / f"gen-{model}.jsonl"


def _label(raw: str) -> str:
    return re.sub(r"[\[\]\s]", "", raw)


def _parse(content: str | None) -> dict:
    """응답 content를 `{abstain, answer, citations}`로. 형식이 어긋나면 ValueError."""
    if not content:
        raise ValueError("빈 응답")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}") from e
    ok = (
        isinstance(data, dict)
        and isinstance(data.get("abstain"), bool)
        and isinstance(data.get("answer"), str)
        and isinstance(data.get("citations"), list)
        and all(isinstance(c, str) for c in data["citations"])
    )
    if not ok:
        raise ValueError(f"스키마 위반: {content[:120]}")
    return data


def generate(
    question: str, result: dict[str, list[Chunk]], client, model: str, cache=None
) -> Answer:
    """검색 결과로 답 하나. API 예외는 `error`에 남기고, `HardApiError`만 위로 올린다."""
    messages = build_messages(question, result)
    labels = [c.label for c in result["law"] + result["faq"]]
    out = Answer(question=question, abstain=True, context_labels=labels)
    key = cache_key(model, messages)
    hit = cache.get(key) if cache is not None else None
    if hit is not None:
        value, out.cached = hit, True
    else:
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "strict": True, "schema": SCHEMA},
                },
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
            value = {
                "content": resp.choices[0].message.content,
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
                # 재시도 대기를 뺀 마지막 시도의 시간. 감싼 클라이언트가 없으면 전체 시간
                "latency_s": round(
                    getattr(client, "last_attempt_s", None) or time.perf_counter() - t0, 3
                ),
            }
        except HardApiError:
            raise
        except Exception as e:  # noqa: BLE001 — 질문 하나의 실패로 일괄 실행을 멈추지 않는다
            out.error = f"{type(e).__name__}: {e}"
            return out
    out.input_tokens, out.output_tokens = value["input_tokens"], value["output_tokens"]
    out.usd = cost_usd(model, out.input_tokens, out.output_tokens)
    out.latency_s = value["latency_s"]
    try:
        data = _parse(value["content"])
    except ValueError as e:
        out.error = str(e)
        return out
    if cache is not None and not out.cached:
        cache.put(key, value)  # 읽히는 응답만 둔다 — 잘린 응답이 굳어 다시 안 불리는 것을 막는다
    cites = list(dict.fromkeys(_label(c) for c in data["citations"]))
    out.citations = [c for c in cites if c in labels]
    out.invalid_citations = [c for c in cites if c not in labels]
    out.answer, out.abstain = data["answer"], data["abstain"]
    if not out.abstain and not out.citations:
        out.abstain, out.forced_abstain = True, True
    return out


def _title(c: Chunk) -> str:
    return f"{c.label}({c.meta['title']})" if "title" in c.meta else c.label


def format_answer(a: Answer, result: dict[str, list[Chunk]]) -> str:
    by_label = {c.label: c for c in result["law"] + result["faq"]}
    flag = "예" if a.abstain else "아니오"
    if a.forced_abstain:
        flag += " (인용이 없어 코드가 바꿈)"
    out = [f"질문: {a.question}", f"abstain: {flag}", f"답: {a.answer}"]
    law = [by_label[c] for c in a.citations if by_label[c].source == "law"]
    faq = [by_label[c] for c in a.citations if by_label[c].source == "faq"]
    out.append(f"인용한 조 {len(law)}개 (본문 앞 {SHOW_CHARS}자)")
    for c in law:
        body = " ".join(strip_head(c).split())[:SHOW_CHARS]
        out.append(f"[{c.label}] {_title(c)}\n    {body}")
    out.append(f"인용한 FAQ {len(faq)}개")
    out += [f"{c.label} · {c.text.partition(chr(10))[0]}" for c in faq]
    if a.invalid_citations:
        out.append("문맥 밖 인용(버림): " + ", ".join(a.invalid_citations))
    out += ["", f"검색 상위 조 {len(result['law'])}개"]
    for i, c in enumerate(result["law"], start=1):
        out.append(f"{i}. {c.label} · {' '.join(strip_head(c).split())[:SHOW_SEARCH_CHARS]}")
    out.append(f"검색 상위 FAQ {len(result['faq'])}개")
    out += [
        f"{i}. {c.label} · {c.text.partition(chr(10))[0]}" for i, c in enumerate(result["faq"], 1)
    ]
    out.append("")
    out.append(
        f"토큰: 입력 {a.input_tokens:,} · 출력 {a.output_tokens:,} · ${a.usd:.4f}"
        f" · 지연 {a.latency_s:.1f}초" + (" · 캐시" if a.cached else "")
    )
    return "\n".join(out)


def make_client(api_key: str | None = None):
    api_key = settings.openai_api_key if api_key is None else api_key
    if not api_key.strip():
        # 비면 다른 값으로 대신하지 않는다 — 재시도로 풀리지 않는 오류다
        raise HardApiError("OPENAI_API_KEY가 비어 있다. 셸 환경변수에 넣을 것")
    from openai import OpenAI

    # SDK 자체 재시도는 끈다 — 재시도와 호출 수는 evaluate의 RetryingClient가 센다
    return OpenAI(api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT_S)


def main(
    argv: list[str] | None = None,
    runs_dir: Path = RUNS73,
    embedder=None,
    client=None,
    cache_path: Path | None = None,
    law_rows=None,
    faq_rows=None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.answer")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5, help="조문 개수")
    ap.add_argument("--faq-k", type=int, default=3, help="FAQ 개수")
    args = ap.parse_args(argv)
    try:
        candidate = selected_candidate(runs_dir)
        client = client or make_client()
    except (FileNotFoundError, HardApiError) as e:
        print(e, file=sys.stderr)
        return 1
    embedder = embedder or Embedder(settings.openai_embed_model)
    index = Index(candidate, embedder, law_rows=law_rows, faq_rows=faq_rows)
    # 실사용 질문이라 같은 질문 FAQ를 빼지 않는다. 평가(evaluate)만 뺀다
    result = index.search(args.question, args.k, faq_k=args.faq_k)
    model = settings.openai_gen_model
    cache = GenCache(cache_path or cache_path_for(model))
    a = generate(args.question, result, client, model, cache)
    print(format_answer(a, result))
    if a.error:
        print(f"생성 실패: {a.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
