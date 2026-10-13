"""정답 라벨 — FAQ 답변이 인용한 규칙 조문 (#131).

#70 파서의 `cited_articles`는 법령 이름이 없어 「주택법」 제2조도 규칙 제2조로 잡는다.
답변 원문에서 인용 자리마다 같은 문장 안의 가장 가까운 앞 법령 이름을 찾아 셋으로 나눈다.

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

from cheongyak_rag.retrieval.corpus import DATA_DIR, LAW_PATH, load_articles

FAQ_PATH = DATA_DIR / "faq-20240529.jsonl"
RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"
GOLDEN_PATH = RUNS_DIR / "golden.jsonl"
SAMPLE_SIZE = 20
BEFORE_CHARS = 60
MIN_SAMPLE_CONTEXT = 20  # 답변 맨 앞 인용은 앞 글자가 없어 표본으로 못 쓴다

ARTICLE = re.compile(r"제\s?(\d+)\s?조(?:\s?의\s?(\d+))?")
QUESTION_ARTICLE = re.compile(r"제\s?\d+\s?조")
# 문장 끝(`다.` `요.`)과 목록 항목의 시작. 목록 번호 `1.` `가.`의 마침표는 끝으로 안 본다
SENTENCE_END = re.compile(r"(?<=[가-힣)”’\"'])(?<!\s[가-힣])[.?!](?=\s|$)")
LIST_START = re.compile(r"\n\s*(?:\d+[.)]|[가-힣][.)]|[①-⑳]|[-*▴○●ㆍ·※])\s")
# 「…」 ｢…｣ 안의 이름, 또는 법·령·규칙으로 끝나는 낱말, 또는 낱말 `영`
NAME = re.compile(
    r"[「｢](?P<b>[^」｣]*)[」｣]"
    r"|(?<![가-힣])(?P<w>[가-힣]*(?:시행령|시행규칙|규칙|법|령)|영)(?![가-힣])"
)
RULE_BRACKET = ("주택공급에관한규칙", "주택공급규칙")
RULE_WORDS = {"규칙", "동규칙"}  # 낱말 `규칙` 앞의 `이`·`같은`·`동`은 따로 안 봐도 규칙이다


@dataclass(frozen=True)
class Citation:
    label: str
    kind: str  # rule | other | none
    before: str  # 인용 앞 글자 (표본 출력용)


def _name_kind(m: re.Match) -> str | None:
    if m["b"] is not None:
        name = re.sub(r"\s", "", m["b"])
        return "rule" if name.startswith(RULE_BRACKET) else "other"
    word = m["w"]
    if word.endswith(
        ("방법", "부령")
    ):  # 「공개의 방법」, `국토교통부령 제512호`는 법령 이름이 아니다
        return None
    is_rule = word in RULE_WORDS or ("주택공급" in word and word.endswith("규칙"))
    return "rule" if is_rule or word.endswith("공급규칙") else "other"


def _sentence_start(text: str, pos: int) -> int:
    cuts = [m.end() for m in SENTENCE_END.finditer(text, 0, pos)]
    cuts += [m.start() + 1 for m in LIST_START.finditer(text, 0, pos)]
    return max(cuts, default=0)


def extract_citations(answer: str) -> list[Citation]:
    """답변의 `제N조` 인용을 등장 순서대로. 항·호는 뗀다. 중복은 그대로 둔다(인용 자리 수)."""
    out = []
    for m in ARTICLE.finditer(answer):
        start = _sentence_start(answer, m.start())
        sentence = answer[start : m.start()]
        kind = "none"
        for nm in NAME.finditer(sentence):
            kind = _name_kind(nm) or kind  # 가장 가까운(마지막) 이름이 이긴다
        label = f"제{m[1]}조" + (f"의{m[2]}" if m[2] else "")
        before = re.sub(r"\s+", " ", answer[max(0, m.start() - BEFORE_CHARS) : m.start()])
        out.append(Citation(label, kind, before))
    return out


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
            continue  # 인용 없는 답변은 후보가 아니다
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
