"""golden 123문항 + 범위 밖 10문항 일괄 답 생성 (#139).

    python -m cheongyak_rag.generate.evaluate [--budget-usd 6]

`runs/139/answers.jsonl` — 질문 한 줄. 같은 입력이면 바이트까지 같아야 하므로(캐시로 재현)
`latency_s`·`cached`처럼 실행마다 달라지는 값은 넣지 않고 `config.json`의 요약으로 뺀다.
`config.json`의 `first_run`은 답을 처음 만든 실행의 요약이고, 같은 답이 다시 나온 실행은
`second_run`에 둔다. 멈춘 실행(예산·인증·연속 실패)은 `*.partial.*`로 따로 쓴다.
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

from openai import APIConnectionError

from cheongyak_rag.config import settings
from cheongyak_rag.generate.answer import (
    Answer,
    GenCache,
    HardApiError,
    cache_path_for,
    check_model,
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
MAX_CONSECUTIVE_ERRORS = 5  # 장애가 이어지면 질문마다 재시도 대기를 쓰며 끝까지 가지 않는다
BACKOFF_S = 2.0
HARD_STATUS = (401, 403)


def _is_transient(e: Exception) -> bool:
    """429(요청 한도) · 5xx · 연결 오류. 시간 초과(`APITimeoutError`)는 연결 오류의 하위다."""
    status = getattr(e, "status_code", None)
    return (
        status == 429
        or (isinstance(status, int) and status >= 500)
        or isinstance(e, APIConnectionError)
    )


def _is_hard(e: Exception) -> bool:
    return getattr(e, "status_code", None) in HARD_STATUS or (
        getattr(e, "code", None) == "insufficient_quota"
    )


class RetryingClient:
    """`chat.completions.create`에 재시도를 씌운다. 시도마다 `calls`를 센다.

    429 · 5xx · 연결 오류는 2·4·8·16·32초를 기다려 최대 5번 다시 보낸다.
    인증·권한·쿼터 오류는 `HardApiError`.
    """

    def __init__(self, client, *, sleep=time.sleep):
        self._client, self._sleep = client, sleep
        self.calls = self.retries = 0
        self.last_attempt_s = 0.0  # 마지막 시도 하나의 시간 (대기 제외)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        for attempt in range(MAX_RETRIES + 1):
            self.calls += 1
            t0 = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(**kw)
                self.last_attempt_s = time.perf_counter() - t0
                return resp
            except Exception as e:
                if _is_hard(e):
                    raise HardApiError(f"{type(e).__name__}: {e}") from e
                if not _is_transient(e) or attempt == MAX_RETRIES:
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
    """질문마다 검색 → 답. (rows, answers, stop). 멈추면 stop = (종류, 사유), 아니면 None.

    종류: budget(예산 초과 — 그 질문까지 하고 멈춘다) · hard(인증·쿼터) ·
    errors(연속 실패, 검색 실패).
    """
    rows, answers, spent, streak = [], [], 0.0, 0
    for kind, q in questions:
        try:
            result = index.search(q["question"], K, faq_k=FAQ_K, exclude_same_question=True)
        except Exception as e:  # noqa: BLE001 — 임베딩 호출 실패 때 그때까지의 결과를 잃지 않는다
            return rows, answers, ("errors", f"{q['qid']}: 검색 실패 {type(e).__name__}: {e}")
        try:
            a = generate(q["question"], result, client, model, cache)
        except HardApiError as e:
            return rows, answers, ("hard", f"{q['qid']}: {e}")
        rows.append(_row(a, q, kind, result))
        answers.append(a)
        spent += 0.0 if a.cached else a.usd
        streak = streak + 1 if a.error else 0
        if spent > budget_usd:
            return rows, answers, ("budget", f"{q['qid']}: 예산 ${budget_usd} 초과 (${spent:.4f})")
        if streak >= MAX_CONSECUTIVE_ERRORS:
            return rows, answers, ("errors", f"{q['qid']}: 연속 {streak}건 실패 ({a.error})")
    return rows, answers, None


def summarize(answers: list[Answer], client, stop: tuple[str, str] | None) -> dict:
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
        "stopped": stop is not None,
        "stopped_at": stop[1].partition(":")[0] if stop else None,
        "stop_reason": stop[1] if stop else None,
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
        check_model(settings.openai_gen_model)
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
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    run = summarize(answers, client, stop)
    cfg = {
        "model": model,
        "k": K,
        "faq_k": FAQ_K,
        "questions": len(questions),
        "budget_usd": args.budget_usd,
    }
    if stop:
        # 멈춘 실행은 끝까지 돈 결과를 덮어쓰지 않도록 따로 쓴다
        (out_dir / "answers.partial.jsonl").write_text(text, encoding="utf-8")
        partial = {**cfg, "stopped_run": run}
        (out_dir / "config.partial.json").write_text(
            json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        ans_path, cfg_path = out_dir / "answers.jsonl", out_dir / "config.json"
        old = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        # 답이 이전과 바이트까지 같으면 재실행이다 — 첫 실행의 값은 지우지 않고 second_run에 둔다
        rerun = "first_run" in old and ans_path.exists() and ans_path.read_text("utf-8") == text
        ans_path.write_text(text, encoding="utf-8")
        cfg["first_run"] = old["first_run"] if rerun else run
        if rerun:
            cfg["second_run"] = run
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"질문 {len(rows)}/{len(questions)} · 호출 {run['calls']} · 재시도 {run['retries']}"
        f" · 캐시 {run['cache_hits']} · 실패 {run['failures']} · ${run['usd']:.4f}"
    )
    if stop:
        print(f"멈춤({stop[0]}): {stop[1]}", file=sys.stderr)
        return 2 if stop[0] == "budget" else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
