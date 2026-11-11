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


def is_law(label: str) -> bool:
    """조문 라벨은 `제53조` 꼴, FAQ 라벨은 `Q47` 꼴이다."""
    return label.startswith("제")


def make_line(item_id: str, gold: dict, v: vd.Verdict | None, cause: str | None = None) -> dict:
    """정답 라벨 하나와 그에 맞는 시스템 판정 하나(없으면 None)의 run 줄.

    못 맞춘 줄(`matched=false`)은 시스템 칸이 비고 `cause`에 이유가 들어간다.
    """
    line = {
        "id": item_id,
        "axis": gold["axis"],
        "query": gold["query"],
        "gold_verdict": gold["verdict"],
        "gold_citations": gold["citations"],
        "matched": v is not None,
        "cause": cause,
        "sys_verdict": None,
        "sys_pre_verdict": None,
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
        lines.append(make_line(row["id"], g, v, None if v else _cause(g["axis"], plans, verdicts)))
    wanted = {(g["axis"], g["query"]) for g in row["labels"]}
    return lines, sum(1 for k in by_key if k not in wanted)


def measure(rows: list[dict], judge_fn, budget_usd: float) -> dict:
    lines, spent, extra, stop = [], 0.0, 0, None
    for row in rows:
        try:
            plans, verdicts = judge_fn(row)
        except HardApiError as e:
            stop = ("hard", f"{row['id']}: {e}")
            break
        except Exception as e:  # noqa: BLE001 — 문항 하나의 실패로 실행 전체를 잃지 않는다
            why = f"공고 판정 실패: {type(e).__name__}: {e}"
            lines += [make_line(row["id"], g, None, why) for g in row["labels"]]
            continue
        spent += sum(v.usd for v in verdicts if not v.cached)
        got, n = match_item(row, verdicts, plans)
        lines, extra = lines + got, extra + n
        if spent > budget_usd:
            stop = ("budget", f"{row['id']}: 비용 상한 ${budget_usd} 초과 (${spent:.4f})")
            break
    return {"lines": lines, "extra_system": extra, "stop": stop, "usd": spent}


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
        "metrics": metrics.compute(m["lines"]),
    }
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
