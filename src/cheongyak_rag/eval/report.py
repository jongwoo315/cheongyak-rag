"""run.jsonl과 metrics.json으로 리포트 `docs/76-eval.md`를 쓴다 (#76).

python -m cheongyak_rag.eval.report [--run-dir runs/76] [--out docs/76-eval.md]
"""

import argparse
import json
import sys
from pathlib import Path

from cheongyak_rag.retrieval.index_db_report import write

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "runs/76"
OUT_MD = ROOT / "docs/76-eval.md"


def render(m: dict) -> str:
    acc = m["metrics"]["judgment_accuracy"]["total"]
    return f"# #76 eval harness 리포트\n\n- 판정 정확도: {acc['num']}/{acc['den']}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.eval.report")
    ap.add_argument("--run-dir", type=Path, default=RUN_DIR)
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)
    m = json.loads((args.run_dir / "metrics.json").read_text(encoding="utf-8"))
    write(args.out, render(m))
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
