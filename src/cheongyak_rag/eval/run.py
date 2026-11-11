"""골든셋 문항을 지금 배포된 판정 흐름에 돌려 하위 질의마다 한 줄씩 쓴다 (#76).

python -m cheongyak_rag.eval.run [--budget-usd 10] [--limit N] [--out-dir runs/76]

`generate.verdict.judge`를 문항마다 부른다(`trace.run_traced`는 부르지 않는다 — `traces`에 쓴다).
정답 라벨마다 한 줄을 `run.jsonl`에 쓰고 지표는 `metrics.json`에 쓴다. 리포트는 `eval.report`다.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import sqlalchemy as sa

from cheongyak_rag.config import settings
from cheongyak_rag.eval import metrics
from cheongyak_rag.eval.metrics import is_law
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate.answer import GenCache, HardApiError, check_model, make_client
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.profile import Profile
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import now, write

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "runs/75/golden.jsonl"
OUT_DIR = ROOT / "runs/76"
BUDGET_USD = 10.0


def make_line(row: dict, gold: dict, v: vd.Verdict | None, cause: str | None = None) -> dict:
    """정답 라벨 하나와 그에 맞는 시스템 판정 하나(없으면 None)의 run 줄.

    못 맞춘 줄(`matched=false`)은 시스템 칸이 비고 `cause`에 이유가 들어간다.
    """
    line = {
        "id": row["id"],
        "notice_name": row["notice_name"],
        "axis": gold["axis"],
        "query": gold["query"],
        "gold_verdict": gold["verdict"],
        "gold_citations": gold["citations"],
        "gold_reason": gold["reason"],
        "matched": v is not None,
        "cause": cause,
        "sys_verdict": None,
        "sys_pre_verdict": None,
        "sys_reason": None,
        "sys_citations": [],
        "law_top5": [],
        "faq_top3": [],
        "error": None,
        "usd": 0.0,
        "cached": False,
    }
    if v is not None:
        ctx = v.context_labels
        line.update(
            sys_verdict=v.verdict,
            sys_pre_verdict=v.original_verdict if (v.guarded or v.forced) else v.verdict,
            sys_reason=v.reason,
            sys_citations=v.citations,
            law_top5=list(dict.fromkeys(c for c in ctx if is_law(c))),
            faq_top3=list(dict.fromkeys(c for c in ctx if not is_law(c))),
            error=v.error,
            usd=v.usd,
            cached=v.cached,
        )
    return line


def _cause(axis: str, plans: list[axes.AxisPlan], verdicts: list[vd.Verdict]) -> str:
    """정답 라벨에 맞는 시스템 하위 질의가 없는 이유."""
    on = {p.id for p in plans if p.on}
    if axis not in on:
        return "축이 꺼졌다"
    if any(v.axis == axis for v in verdicts):
        return "질의 문장이 다르다"
    return "축이 켜졌는데 하위 질의가 없다"


def match_item(
    row: dict, verdicts: list[vd.Verdict], plans: list[axes.AxisPlan]
) -> tuple[list[dict], int]:
    """`(axis, query)`로 정답 라벨과 시스템 판정을 맞춘다.

    반환: (정답 라벨마다 한 줄, 정답 라벨이 없는 시스템 하위 질의 수).
    """
    by_key = {(v.axis, v.query): v for v in verdicts}
    lines = []
    for g in row["labels"]:
        v = by_key.get((g["axis"], g["query"]))
        lines.append(make_line(row, g, v, None if v else _cause(g["axis"], plans, verdicts)))
    wanted = {(g["axis"], g["query"]) for g in row["labels"]}
    return lines, sum(1 for k in by_key if k not in wanted)


def measure(rows: list[dict], judge_fn, budget_usd: float) -> dict:
    lines, spent, calls, cache_hits, extra, stop = [], 0.0, 0, 0, 0, None
    for row in rows:
        try:
            plans, verdicts = judge_fn(row)
        except HardApiError as e:
            stop = ("hard", f"{row['id']}: {e}")
            break
        except Exception as e:  # noqa: BLE001 — 문항 하나의 실패로 실행 전체를 잃지 않는다
            why = f"공고 판정 실패: {type(e).__name__}: {e}"
            lines += [make_line(row, g, None, why) for g in row["labels"]]
            continue
        spent += sum(v.usd for v in verdicts if not v.cached)
        calls += sum(1 for v in verdicts if not v.cached and not v.no_context)  # 실제 LLM 호출
        cache_hits += sum(1 for v in verdicts if v.cached)
        got, n = match_item(row, verdicts, plans)
        lines, extra = lines + got, extra + n
        if spent > budget_usd:
            stop = ("budget", f"{row['id']}: 비용 상한 ${budget_usd} 초과 (${spent:.4f})")
            break
    return {
        "lines": lines,
        "extra_system": extra,
        "stop": stop,
        "usd": spent,
        "calls": calls,
        "cache_hits": cache_hits,
    }


USAGE_KEYS = ("calls", "cache_hits", "retries", "usd")


def attach_runs(res: dict, prev: dict | None) -> dict:
    """첫 실행(`first_run`)과 같은 명령을 한 번 더 돌린 실행(`second_run`)을 가른다.

    직전 기록이 같은 모델·문항 수의 완주 실행이면 이번 완주 실행은 두 번째 실행이다.
    멈췄거나 판정이 실패한 줄이 있는 실행은 완주가 아니다. 그런 실행이 이어지면 호출 수와
    비용을 더해 다음 완주 실행의 첫 실행 값으로 쓴다 — 캐시가 찬 뒤의 비용만 적지 않으려는 것이다.
    """
    same = bool(prev) and (prev["model"], prev["items"]) == (res["model"], res["items"])
    prev = prev if same else {}
    usage = {k: res[k] for k in USAGE_KEYS}
    carried = prev.get("usage_total") if prev.get("incomplete") else None
    total = {k: usage[k] + carried[k] for k in USAGE_KEYS} if carried else usage
    incomplete = bool(res["stop"] or res["counts"]["verdict_errors"])
    snap = {"run_at": res["run_at"], "metrics": res["metrics"], "counts": res["counts"]}
    old = prev.get("first_run")
    if incomplete:
        first, second = old, None
    elif old:
        first, second = old, {**snap, **usage}
    else:
        first, second = {**snap, **total}, None
    return {
        "incomplete": incomplete,
        "usage_total": total,
        "first_run": first,
        "second_run": second,
    }


def make_judge_fn(engine, embedder, client, cache, model):
    search_cache: axes.Cache = {}

    def judge_fn(row):
        _, plans, verdicts = vd.judge(
            engine, embedder, client, model, row["house_manage_no"],
            Profile.from_dict(row["profile"]), row["pblanc_no"], cache=cache,
            search_cache=search_cache,
        )  # fmt: skip
        return plans, verdicts

    return judge_fn


def _read_prev(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(
    argv: list[str] | None = None, *, judge_fn=None, golden: Path = GOLDEN, engine=None
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.eval.run")
    ap.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    ap.add_argument("--limit", type=int, default=None, help="앞에서부터 문항 N개만")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--model", default=settings.openai_gen_model)
    args = ap.parse_args(argv)
    rows = [json.loads(x) for x in golden.read_text(encoding="utf-8").splitlines() if x]
    rows = rows[: args.limit]
    client = None
    if judge_fn is None:
        try:
            check_model(args.model)
            client = RetryingClient(make_client())
        except (OSError, KeyError, ValueError, HardApiError) as e:
            print(f"준비 실패: {type(e).__name__}: {e}", file=sys.stderr)
            return 3
        engine = engine or sa.create_engine(settings.database_url)
        judge_fn = make_judge_fn(
            engine, Embedder(settings.openai_embed_model), client,
            GenCache(vd.cache_path_for(args.model)), args.model,
        )  # fmt: skip
    prev = _read_prev(args.out_dir / "metrics.json")  # 새 기록을 쓰기 전에 읽는다
    t0 = time.perf_counter()
    m = measure(rows, judge_fn, args.budget_usd)
    out = args.out_dir
    write(out / "run.jsonl", "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in m["lines"]))
    result = {
        "run_at": now(),
        "model": args.model,
        "items": len(rows),
        "seconds": round(time.perf_counter() - t0, 1),
        "stop": m["stop"],
        "usd": m["usd"],
        "calls": m["calls"],
        "cache_hits": m["cache_hits"],
        "retries": client.retries if client else 0,
        "metrics": metrics.compute(m["lines"]),
        "counts": {**metrics.counts(m["lines"]), "unmatched_system_queries": m["extra_system"]},
    }
    result.update(attach_runs(result, prev))
    write(out / "metrics.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    acc = result["metrics"]["judgment_accuracy"]["total"]
    print(f"문항 {len(rows)}개 · 줄 {len(m['lines'])} · 판정 정확도 {acc['num']}/{acc['den']}")
    print(f"→ {out / 'run.jsonl'} · {out / 'metrics.json'}")
    if m["stop"]:
        print(f"멈춤({m['stop'][0]}): {m['stop'][1]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
