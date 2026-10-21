"""golden 123문항 + 범위 밖 10문항 일괄 답 생성 (#139).

    python -m cheongyak_rag.generate.evaluate [--budget-usd 6]

`runs/139/answers.jsonl` — 질문 한 줄. 같은 입력이면 바이트까지 같아야 하므로(캐시로 재현)
`latency_s`·`cached`처럼 실행마다 달라지는 값은 넣지 않고 `config.json`의 요약으로 뺀다.
`config.json`의 `first_run`은 API를 부른 마지막 실행의 요약이다.
캐시만 쓴 재실행은 `last_run`만 바꾼다.
"""

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from cheongyak_rag.config import settings
from cheongyak_rag.generate.answer import (
    Answer,
    GenCache,
    HardApiError,
    cache_path_for,
    generate,
    make_client,
)
from cheongyak_rag.retrieval.chunk_eval import RUNS73
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.golden import GOLDEN_PATH, RUNS_DIR
from cheongyak_rag.retrieval.query import Index, selected_candidate

OUT_DIR = RUNS_DIR / "139"
OOD_PATH = OUT_DIR / "ood.jsonl"
K, FAQ_K = 5, 3
BUDGET_USD = 6.0
MAX_RETRIES = 5
BACKOFF_S = 2.0
HARD_STATUS = (401, 403)


def _is_hard(e: Exception) -> bool:
    return getattr(e, "status_code", None) in HARD_STATUS or (
        getattr(e, "code", None) == "insufficient_quota"
    )


class RetryingClient:
    """`chat.completions.create`에 429 재시도를 씌운다. 시도마다 `calls`를 센다.

    429는 2·4·8·16·32초를 기다려 최대 5번 다시 보낸다. 인증·권한·쿼터 오류는 `HardApiError`.
    """

    def __init__(self, client, *, sleep=time.sleep):
        self._client, self._sleep = client, sleep
        self.calls = self.retries = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        for attempt in range(MAX_RETRIES + 1):
            self.calls += 1
            try:
                return self._client.chat.completions.create(**kw)
            except Exception as e:
                if _is_hard(e):
                    raise HardApiError(f"{type(e).__name__}: {e}") from e
                if getattr(e, "status_code", None) != 429 or attempt == MAX_RETRIES:
                    raise
                self.retries += 1
                self._sleep(BACKOFF_S * 2**attempt)


def percentile(values: list[float], p: float) -> float:
    """가장 가까운 순위(nearest-rank) 백분위. 값이 없으면 0."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _row(a: Answer, q: dict, kind: str, result: dict) -> dict:
    row = asdict(a)
    del row["latency_s"], row["cached"]
    gold = q.get("gold", [])
    law = {c.label for c in result["law"]}
    faq = {c.label for c in result["faq"]}
    return {
        "qid": q["qid"],
        "set": kind,
        **row,
        "gold": gold,
        "retrieval_hit": any(g in law for g in gold) if kind == "golden" else None,
        "self_faq_in_context": f"Q{q['q_no']}" in faq if kind == "golden" else False,
    }


def run_all(index, client, cache, model, questions, budget_usd):
    """질문마다 검색 → 답. (rows, answers, stop_reason). 예산을 넘으면 그 질문까지 하고 멈춘다."""
    rows, answers, spent = [], [], 0.0
    for kind, q in questions:
        result = index.search(q["question"], K, faq_k=FAQ_K, exclude_same_question=True)
        try:
            a = generate(q["question"], result, client, model, cache)
        except HardApiError as e:
            return rows, answers, f"{q['qid']}: {e}"
        rows.append(_row(a, q, kind, result))
        answers.append(a)
        spent += 0.0 if a.cached else a.usd
        if spent > budget_usd:
            return rows, answers, f"{q['qid']}: 예산 ${budget_usd} 초과 (${spent:.4f})"
    return rows, answers, None


def summarize(answers: list[Answer], client, stop_reason: str | None) -> dict:
    ok_lat = [a.latency_s for a in answers if not a.error]
    return {
        "calls": client.calls,
        "retries": client.retries,
        "cache_hits": sum(a.cached for a in answers),
        "failures": sum(bool(a.error) for a in answers),
        "forced_abstain": sum(a.forced_abstain for a in answers),
        "input_tokens": sum(a.input_tokens for a in answers),
        "output_tokens": sum(a.output_tokens for a in answers),
        "usd": sum(a.usd for a in answers),
        "usd_new": sum(a.usd for a in answers if not a.cached),
        "latency_p50": statistics.median(ok_lat) if ok_lat else 0.0,
        "latency_p95": percentile(ok_lat, 95),
        "stopped": stop_reason is not None,
        "stopped_at": stop_reason.partition(":")[0] if stop_reason else None,
        "stop_reason": stop_reason,
    }


def main(
    argv: list[str] | None = None,
    *,
    client=None,
    embedder=None,
    law_rows=None,
    faq_rows=None,
    golden_path: Path = GOLDEN_PATH,
    ood_path: Path = OOD_PATH,
    out_dir: Path = OUT_DIR,
    runs73: Path = RUNS73,
    cache_path: Path | None = None,
    sleep=time.sleep,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.evaluate")
    ap.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    args = ap.parse_args(argv)
    try:
        candidate = selected_candidate(runs73)
        questions = [("golden", q) for q in _load(golden_path)] + [
            ("ood", q) for q in _load(ood_path)
        ]
        client = RetryingClient(client or make_client(), sleep=sleep)
    except (FileNotFoundError, HardApiError) as e:
        print(e, file=sys.stderr)
        return 1
    model = settings.openai_gen_model
    index = Index(
        candidate,
        embedder or Embedder(settings.openai_embed_model),
        law_rows=law_rows,
        faq_rows=faq_rows,
    )
    cache = GenCache(cache_path or cache_path_for(model))
    rows, answers, stop = run_all(index, client, cache, model, questions, args.budget_usd)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    run = summarize(answers, client, stop)
    cfg_path = out_dir / "config.json"
    old = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    # API를 부른 실행의 값은 캐시만 쓴 재실행이 지우지 않는다
    first = run if run["calls"] > 0 or "first_run" not in old else old["first_run"]
    cfg = {
        "model": model,
        "k": K,
        "faq_k": FAQ_K,
        "questions": len(questions),
        "budget_usd": args.budget_usd,
        "first_run": first,
        "last_run": run,
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"질문 {len(rows)}/{len(questions)} · 호출 {run['calls']} · 재시도 {run['retries']}"
        f" · 캐시 {run['cache_hits']} · 실패 {run['failures']} · ${run['usd']:.4f}"
    )
    if stop:
        print(f"멈춤: {stop}", file=sys.stderr)
        return 3 if "예산" not in stop else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
