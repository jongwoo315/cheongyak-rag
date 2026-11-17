"""정답 라벨 — FAQ 답변이 인용한 규칙 조문 (#131).

인용 자리를 규칙·다른 법령·이름 없음으로 나누는 분류(`extract_citations`)는 #135에서
`ingest/citations.py`로 옮겼다. 여기서는 그 분류로 정답 라벨 파일을 만든다.

    rule  규칙 — 정답에 넣는다
    other 다른 법령 — 안 넣는다 (셈만 한다)
    none  이름 없음 — FAQ가 청약 FAQ라 규칙으로 보고 넣는다
"""

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cheongyak_rag.ingest.citations import (  # noqa: F401  (Citation은 다시 내보낸다)
    Citation,
    extract_citations,
)
from cheongyak_rag.retrieval.corpus import DATA_DIR, LAW_PATH, load_articles

FAQ_PATH = DATA_DIR / "faq-20240529.jsonl"
RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"
GOLDEN_PATH = RUNS_DIR / "golden.jsonl"
SAMPLE_SIZE = 20
MIN_SAMPLE_CONTEXT = 20  # 답변 맨 앞 인용은 앞 글자가 없어 표본으로 못 쓴다

QUESTION_ARTICLE = re.compile(r"제\s?\d+\s?조")


def has_article_in_question(question: str) -> bool:
    return bool(QUESTION_ARTICLE.search(question))


@dataclass
class GoldenResult:
    rows: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"rule": 0, "other": 0, "none": 0})
    dropped: dict[str, int] = field(default_factory=dict)
    none_samples: list[str] = field(
        default_factory=list
    )  # 이름 없음 인용 앞 60자, 고르게 뽑은 20개


def build_golden(faq_rows: list[dict], labels: set[str]) -> GoldenResult:
    res = GoldenResult()
    dropped: Counter[str] = Counter()
    none_all: list[str] = []
    for r in faq_rows:
        cites = extract_citations(r["answer"])
        if not cites:
            dropped["조문 인용 없는 답변"] += 1  # 후보가 아니다. 그래도 뺀 수에는 센다
            continue
        for c in cites:
            res.counts[c.kind] += 1
            if c.kind == "none" and len(c.before.strip()) >= MIN_SAMPLE_CONTEXT:
                none_all.append(f"q{r['q_no']}: …{c.before}【{c.label}】")
        gold = list(dict.fromkeys(c.label for c in cites if c.kind != "other"))
        if not gold:
            dropped["다른 법령 인용뿐"] += 1
        elif any(g not in labels for g in gold):
            dropped["현행에 없는 조를 인용"] += 1
        else:
            res.rows.append(
                {
                    "qid": f"faq-{r['q_no']}",
                    "q_no": r["q_no"],
                    "question": r["question"],
                    "gold": gold,
                    "has_article_in_question": has_article_in_question(r["question"]),
                }
            )
    res.dropped = dict(dropped)
    step = max(1, len(none_all) // SAMPLE_SIZE)
    res.none_samples = none_all[::step][:SAMPLE_SIZE]
    return res


def load_faq(path: Path = FAQ_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main(out: Path = GOLDEN_PATH) -> int:
    labels = {a.label for a in load_articles(LAW_PATH)}
    res = build_golden(load_faq(), labels)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res.rows), encoding="utf-8"
    )
    names = {"rule": "규칙", "other": "다른 법령", "none": "이름 없음"}
    print("인용 수 (분류별): " + " · ".join(f"{names[k]} {v}" for k, v in res.counts.items()))
    print(f"남은 질문: {len(res.rows)}  → {out}")
    print(f"뺀 질문: {sum(res.dropped.values())}")
    for reason, n in res.dropped.items():
        print(f"  - {reason}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
