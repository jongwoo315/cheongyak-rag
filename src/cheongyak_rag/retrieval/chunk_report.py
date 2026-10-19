"""청킹 후보 비교 리포트 `docs/73-chunking.md`와 `runs/73/selected.json` (#73).

    python -m cheongyak_rag.retrieval.chunk_report

고르는 규칙은 측정 전에 정했다(설계 §1): article 대비 hybrid recall@5 차이의 95% CI 하한이 0보다 큰
후보 중 평균이 가장 큰 것. 그런 후보가 없으면 `article`을 유지한다. 평균이 같으면 청크 수가 적은 쪽.
리포트에는 시각을 넣지 않는다 — 같은 run이면 같은 글이 나온다.
"""

import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval.chunk import (
    CANDIDATES,
    SHORT_CHARS,
    check_preservation,
    law_chunks,
    load_law_rows,
    short_ratio,
    strip_head,
)
from cheongyak_rag.retrieval.compare import (
    HALF_WIDTH_LIMIT,
    N_ITER,
    Verdict,
    _ci,
    _esc,
    _p,
    _sgn,
    load_results,
    verdict,
)
from cheongyak_rag.retrieval.corpus import LAW_PATH, load_articles
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.evaluate import load_golden
from cheongyak_rag.retrieval.golden import RUNS_DIR, load_faq
from cheongyak_rag.retrieval.search import _kiwi, tokenize

REPORT_PATH = Path(__file__).resolve().parents[3] / "docs" / "73-chunking.md"
RUNS73 = RUNS_DIR / "73"
RANKERS = ("bm25", "dense", "hybrid")
BASE = "article"
PRIMARY = "recall@5"
SAMPLE_QUESTION = "무주택 세대구성원 기준이 뭔가요?"
SAMPLE_FAQ_Q_NOS = (47, 48, 50, 52, 175, 202, 203, 204)  # 설계 §3
ZONE_ALL_LOW = "모든 후보가 낮다"


@dataclass
class Inputs:
    results: dict[str, list[dict]]  # 후보 → chunk_eval 결과 줄
    stats: dict[str, dict]  # 후보 → {count, median, max}
    titles: dict[str, str]  # 조 → 제목
    long_qids: set[str]  # 정답 조가 긴 문항
    ref131: dict[str, float]  # #131 조 단위 recall@5 평균
    faq_lines: list[dict]
    self_check: dict
    spacing: dict
    samples: list[dict]
    checks: dict  # {"preservation": {후보: [문제]}, "short": {후보: {ratio, items}}}
    observation: dict = field(default_factory=dict)  # {"kiwi": [(형태소, 태그)], "bm25": [토큰]}


# ── 고르는 규칙 ─────────────────────────────────────────────────────────


def zone_of(v: Verdict) -> str:
    """실패 징후 1의 구간. 한 후보의 CI 하나를 읽는다."""
    if v.lo > 0:
        return "차이 있음"
    if v.hi < 0:
        return "낮다"
    return "차이 없음" if v.half_width <= HALF_WIDTH_LIMIT else "판정 불가"


def hybrid_diffs(base: list[dict], cand: list[dict]) -> np.ndarray:
    """질문 id로 맞춘 후보 − base의 hybrid recall@5 차이. base 순서."""
    by = {x["qid"]: x for x in cand}
    return np.array([by[b["qid"]]["hybrid"][PRIMARY] - b["hybrid"][PRIMARY] for b in base])


@dataclass
class Selection:
    chosen: str
    best: str  # base를 뺀 후보 중 평균 차이가 가장 큰 것
    zone: str
    verdicts: dict[str, Verdict]


def select(results: dict[str, list[dict]], stats: dict[str, dict]) -> Selection:
    base = results[BASE]
    others = [c for c in CANDIDATES if c != BASE]
    verdicts = {c: verdict(hybrid_diffs(base, results[c])) for c in others}

    def order(c: str) -> tuple[float, int]:
        return (-verdicts[c].mean, stats[c]["count"])  # 평균이 크고, 같으면 청크가 적은 쪽

    best = min(others, key=order)
    winners = [c for c in others if verdicts[c].lo > 0]
    if winners:
        return Selection(min(winners, key=order), best, "차이 있음", verdicts)
    if all(verdicts[c].hi < 0 for c in others):
        zone = ZONE_ALL_LOW
    else:
        zone = zone_of(verdicts[best])
        zone = zone if zone in ("차이 없음", "판정 불가") else "판정 불가"
    return Selection(BASE, best, zone, verdicts)


def long_qids(golden: list[dict], lengths: dict[str, int]) -> set[str]:
    """정답 조 중 가장 긴 조의 글자 수가 조문 글자 수 중앙값을 넘는 문항."""
    median = statistics.median(lengths.values())
    return {g["qid"] for g in golden if max(lengths[x] for x in g["gold"]) > median}


def self_band(ratio: float) -> str:
    return "통과" if ratio >= 0.95 else "놓친 것 목록" if ratio >= 0.85 else "버그"


def short_band(ratio: float) -> str:
    return "통과" if ratio <= 0.02 else "목록" if ratio <= 0.05 else "청킹 규칙 결함"


# ── 글 만들기 ───────────────────────────────────────────────────────────


def _mean(lines: list[dict], ranker: str, key: str) -> float:
    return float(np.mean([x[ranker][key] for x in lines]))


def _headline(sel: Selection) -> str:
    v = sel.verdicts[sel.best]
    stat = f"{_sgn(v.mean)} (95% CI {_ci(v)}, p={_p(v.p)})"
    if sel.chosen != BASE:
        return (
            f"고른 후보는 `{sel.chosen}`이다 — `{BASE}` 대비 hybrid {PRIMARY} 차이 {stat}, "
            "신뢰구간 하한이 0보다 커서 차이 있음 구간이다."
        )
    if sel.zone == ZONE_ALL_LOW:
        why = "모든 후보의 신뢰구간 상한이 0 미만이라 `모든 후보가 낮다` 구간이다"
    elif sel.zone == "차이 없음":
        why = f"신뢰구간이 0을 포함하고 반폭이 {v.half_width:.3f}(0.05 이하)라 차이 없음 구간이다"
    else:
        why = f"신뢰구간이 0을 포함하고 반폭이 {v.half_width:.3f}로 0.05를 넘어 판정 불가 구간이다"
    return (
        f"고른 후보는 `{BASE}`이다 — 평균 차이가 가장 큰 `{sel.best}`의 `{BASE}` 대비 "
        f"hybrid {PRIMARY} 차이는 {stat}이고 {why}."
    )


def _verdicts(results: dict[str, list[dict]], qids: set[str] | None) -> dict[str, Verdict]:
    base = [x for x in results[BASE] if qids is None or x["qid"] in qids]
    keep = {x["qid"] for x in base}
    return {
        c: verdict(hybrid_diffs(base, [x for x in results[c] if x["qid"] in keep]))
        for c in CANDIDATES
        if c != BASE
    }


def _tables(inp: Inputs, qids: set[str] | None, with_stats: bool) -> list[str]:
    res = {
        c: [x for x in lines if qids is None or x["qid"] in qids]
        for c, lines in inp.results.items()
    }
    verd = _verdicts(inp.results, qids)
    head = "| 후보 |" + (" 청크 수 | 글자 수 중앙값 | 최대 |" if with_stats else "")
    head += " bm25 recall@5 | dense recall@5 | hybrid recall@5 |"
    head += " hybrid − article | 95% CI | p | 구간 |"
    out = [head, "|" + " --- |" * (head.count("|") - 1)]
    if with_stats:
        ref = " | ".join(f"{inp.ref131[r]:.3f}" for r in RANKERS)
        a = inp.stats[BASE]
        out.append(
            f"| #131 조 단위(참고) | {a['count']} | {a['median']:g} | {a['max']} | {ref} "
            "| — | — | — | — |"
        )
    for c in CANDIDATES:
        s = inp.stats[c]
        cells = f"{s['count']} | {s['median']:g} | {s['max']} | " if with_stats else ""
        recalls = " | ".join(f"{_mean(res[c], r, PRIMARY):.3f}" for r in RANKERS)
        v = verd.get(c)
        diff = f"{_sgn(v.mean)} | {_ci(v)} | {_p(v.p)} | {zone_of(v)}" if v else "— | — | — | —"
        out.append(f"| `{c}` | {cells}{recalls} | {diff} |")
    cols = " | ".join(f"{r} {m}" for m in ("hit@1", "mrr") for r in RANKERS)
    out += ["", f"| 후보 | {cols} |"]
    out.append("|" + " --- |" * 7)
    for c in CANDIDATES:
        vals = " | ".join(f"{_mean(res[c], r, m):.3f}" for m in ("hit@1", "mrr") for r in RANKERS)
        out.append(f"| `{c}` | {vals} |")
    return out


def _section_conclusion(inp: Inputs, sel: Selection) -> list[str]:
    n = len(inp.results[BASE])
    out = ["## 1. 결론과 판정 구간", ""]
    out += [
        f"- 질문 {n}개(#131 golden 그대로), 정답은 조 단위다. 주 지표는 hybrid {PRIMARY}이고 "
        "측정 전에 정했다.",
        f"- 고르는 규칙: `{BASE}` 대비 hybrid {PRIMARY} 차이의 95% CI 하한이 0보다 큰 후보 중 "
        f"평균이 가장 큰 것. 같으면 청크 수가 적은 쪽. 그런 후보가 없으면 `{BASE}`을 유지한다.",
        f"- 신뢰구간은 paired bootstrap {N_ITER:,}회, p는 paired permutation {N_ITER:,}회"
        f"(seed 0)다. p는 {N_ITER:,}회 검정이라 0.0001이 하한이다.",
        f"- 후보 4개를 같은 `{BASE}` 하나와 비교하고 다중 비교 보정은 하지 않았다.",
        "- 구간: 하한 > 0 → 차이 있음 / 0을 포함하고 반폭 ≤ 0.05 → 차이 없음 / "
        "0을 포함하고 반폭 > 0.05 → 판정 불가 / 상한 < 0 → 낮다. "
        "네 후보 모두 낮다이면 `모든 후보가 낮다`.",
        "",
        f"### 전체 질문 — `{BASE}` 대비 hybrid {PRIMARY}",
        "",
        "| 후보 | 평균 차이 | 95% CI | p | 구간 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c, v in sel.verdicts.items():
        out.append(f"| `{c}` | {_sgn(v.mean)} | {_ci(v)} | {_p(v.p)} | {zone_of(v)} |")
    out += ["", f"- 전체 구간: **{sel.zone}** · 고른 후보: **`{sel.chosen}`**"]
    return out


def _section_table(inp: Inputs) -> list[str]:
    return ["## 2. 후보 표", ""] + _tables(inp, None, with_stats=True)


def _section_long(inp: Inputs, median: float) -> list[str]:
    n = len(inp.long_qids)
    out = ["## 3. 정답 조가 긴 문항", ""]
    out.append(
        f"정답 조 중 가장 긴 조의 글자 수가 조문 중앙값({median:g}자)을 넘는 질문 {n}개다"
        f"(전체 {len(inp.results[BASE])}개 중). "
        "긴 조 안에 상세 내용이 묻히는지 본다. 고르는 규칙에는 쓰지 않았고 같은 구간을 낸다."
    )
    out += [""] + _tables(inp, inp.long_qids, with_stats=False)
    return out


def _gold_cell(inp: Inputs, label: str, a_line: dict, c_line: dict, cand: str) -> str:
    a, c = a_line["gold_detail"][label], c_line["gold_detail"][label]
    title = inp.titles.get(label, "")
    return (
        f"{label}({title}): `{BASE}` hybrid {a['hybrid']}위 · `{cand}` hybrid {c['hybrid']}위 "
        f"· 청크 {c['path']}"
    )


def _section_split(inp: Inputs, compare: str, chosen: str) -> list[str]:
    a_by = {x["qid"]: x for x in inp.results[BASE]}
    rows = [
        (a_by[c["qid"]], c)
        for c in inp.results[compare]
        if a_by[c["qid"]]["hybrid"]["hit@5"] != c["hybrid"]["hit@5"]
    ]
    rows.sort(key=lambda r: r[1]["q_no"])
    only_c = sum(c["hybrid"]["hit@5"] for _, c in rows)
    out = ["## 4. hit@5가 갈린 문항", ""]
    if chosen == BASE:
        out.append(
            f"고른 후보가 `{BASE}`이라 고른 후보와 `{BASE}` 사이에는 갈린 문항이 없다. "
            f"비교 대상은 평균 차이가 가장 큰 후보 `{compare}`, 기준 `{BASE}`이다."
        )
    else:
        out.append(f"비교 대상은 고른 후보 `{chosen}`, 기준 `{BASE}`이다.")
    out += [
        f"hybrid `hit@5`가 다른 질문은 {len(rows)}개다(`{compare}`만 맞힘 {only_c}개, "
        f"`{BASE}`만 맞힘 {len(rows) - only_c}개). 전부 아래에 있다.",
        "",
        "| 질문 | 맞힌 쪽 | 정답 조별 순위와 `" + compare + "`에서 가장 높이 오른 청크 |",
        "| --- | --- | --- |",
    ]
    for a, c in rows:
        who = f"`{compare}`만" if c["hybrid"]["hit@5"] else f"`{BASE}`만"
        cells = "<br>".join(_gold_cell(inp, g, a, c, compare) for g in c["gold"])
        out.append(f"| {c['qid']} 「{_esc(c['question'])}」 | {who} | {cells} |")
    return out


def _section_faq(inp: Inputs) -> list[str]:
    out = ["## 5. FAQ 검색", ""]
    lines = inp.faq_lines
    out.append(
        "FAQ 청크 480개(쌍 하나 = 청크 하나)를 골든 질문으로 검색했다. "
        "자기 쌍과 같은 질문 텍스트의 쌍은 뺐다(leave-self-out). "
        "`faq_hit@k`는 상위 k개 중 하나라도 인용 조가 정답 조와 겹치면 1이다. "
        "baseline 없음 — 이번이 첫 측정."
    )
    if not lines:
        return out + ["", "FAQ run 결과가 없다. `chunk_eval --faq`를 먼저 돌린다."]
    sc = inp.self_check
    out += [
        "",
        "| 순위 | faq_hit@1 | faq_hit@5 | 자기 쌍 1위 비율(점검 run) | 구간 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in RANKERS:
        h1, h5 = _mean(lines, r, "faq_hit@1"), _mean(lines, r, "faq_hit@5")
        ratio = sc["self_top1"][r]
        out.append(f"| {r} | {h1:.3f} | {h5:.3f} | {ratio:.3f} | {self_band(ratio)} |")
    out += [
        "",
        "- 점검 run은 자기 쌍을 넣고 돌려 1위가 자기 쌍(또는 같은 질문 쌍)인 비율이다. "
        f"질문 {sc['n']}개.",
        f"- leave-self-out run의 상위 5개에 자기 쌍·같은 질문 쌍이 든 횟수: {sc['leak_count']}개 "
        "(0이어야 한다).",
    ]
    if sc["misses"]:
        out += ["", "점검 run에서 1위가 자기 쌍이 아니었던 질문:", ""]
        out += [f"- {m['qid']} ({m['ranker']}): 1위는 Q{m['top1_q_no']}" for m in sc["misses"]]
    return out


def _fmt_sample_cell(r: dict) -> tuple[str, str]:
    law = "<br>".join(f"{i}. {label} · {path}" for i, (label, path) in enumerate(r["law"], 1))
    faq = "<br>".join(f"{i}. Q{q_no} · {_esc(q)}" for i, (q_no, q) in enumerate(r["faq"], 1))
    return law, faq


def _section_samples(inp: Inputs) -> list[str]:
    out = [
        "## 6. 정의형 질문 표본",
        "",
        "이 표본의 정답은 사람이 단 라벨이 아니다. "
        "숫자 판정에 쓰지 않고 상위 결과를 나란히 찍었다. FAQ 쪽은 같은 질문 텍스트의 쌍을 뺐다.",
    ]
    for s in inp.samples:
        out += ["", f"### 「{_esc(s['question'])}」 ({s['origin']})", ""]
        out += [
            "| 구조 | 조문 상위 5개 (조 · 위치) | FAQ 상위 3개 (Q번호 · 질문) |",
            "| --- | --- | --- |",
        ]
        for cand, r in s["results"].items():
            law, faq = _fmt_sample_cell(r)
            out.append(f"| `{cand}` | {law} | {faq} |")
    obs = inp.observation
    if obs:
        kiwi = " + ".join(f"`{f}`/{t}" for f, t in obs["kiwi"])
        out += [
            "",
            "### 형태소 관찰 (이번 티켓은 바꾸지 않았다)",
            "",
            f"`무주택세대구성원`을 kiwi는 {kiwi}로 나눈다. BM25 입력 토큰은 "
            f"{', '.join(f'`{t}`' for t in obs['bm25'])}이다.",
        ]
    return out


def _section_spacing(inp: Inputs) -> list[str]:
    sp = inp.spacing
    out = ["## 7. 붙은 단어", ""]
    out += [
        f"FAQ 질문 중 목차와 공백만 다른 {len(sp['pairs'])}쌍에서, "
        "붙은 본문 질문과 목차의 띄어 쓴 질문 사이의 값이다.",
        "",
        f"- kiwi 토큰 Jaccard 평균 {sp['mean_jaccard']:.3f} "
        f"· 임베딩 코사인 평균 {sp['mean_cosine']:.3f}",
        "- 기준: 토큰 ≥ 0.95 이고 코사인 ≥ 0.98 → 영향 없음 / 토큰 < 0.90 이거나 코사인 < 0.95 → "
        "공백 복원을 별도 티켓으로 / 그 사이 → 쌍별 값 목록",
        f"- 구간: **{sp['band']}**",
        "",
        "| Q번호 | 목차 질문 | 본문 질문 | Jaccard | 코사인 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sp["pairs"]:
        out.append(
            f"| Q{r['q_no']} | {_esc(r['toc'])} | {_esc(r['body'])} | {r['jaccard']:.3f} "
            f"| {r['cosine']:.3f} |"
        )
    return out


def _section_checks(inp: Inputs) -> list[str]:
    out = ["## 8. 점검", "", "### 재현 — `article` 후보와 #131 (실패 징후 2)", ""]
    out += ["| 순위 | 이 run | #131 | 소수 셋째 자리 |", "| --- | --- | --- | --- |"]
    same_all = True
    for r in RANKERS:
        got, ref = _mean(inp.results[BASE], r, PRIMARY), inp.ref131[r]
        same = f"{got:.3f}" == f"{ref:.3f}"
        same_all &= same
        out.append(f"| {r} {PRIMARY} | {got:.3f} | {ref:.3f} | {'같음' if same else '다름'} |")
    out.append("")
    out.append(
        "셋 다 같음이면 통과."
        if same_all
        else "다름이 있다 — 버그다. 원인을 찾기 전에는 다른 후보를 재지 않는다."
    )
    out += ["", "### 청크 보존 (실패 징후 3)", "", "| 후보 | 결과 |", "| --- | --- |"]
    for c in CANDIDATES:
        problems = inp.checks["preservation"][c]
        out.append(f"| `{c}` | {'누락 0 · 중복 0' if not problems else '; '.join(problems)} |")
    out += ["", f"### 짧은 청크 (실패 징후 4) — {SHORT_CHARS}자 미만", ""]
    out += ["| 후보 | 비율 | 구간 |", "| --- | --- | --- |"]
    for c in CANDIDATES:
        ratio = inp.checks["short"][c]["ratio"]
        out.append(f"| `{c}` | {ratio:.2%} | {short_band(ratio)} |")
    for c in CANDIDATES:
        items = inp.checks["short"][c]["items"]
        if items and short_band(inp.checks["short"][c]["ratio"]) != "통과":
            out += ["", f"`{c}`의 짧은 청크 {len(items)}개 (머리를 뗀 본문 기준):", ""]
            out += [f"- {path}: {_esc(text)}" for path, text in items]
    return out


def build_report(inp: Inputs) -> tuple[str, dict]:
    sel = select(inp.results, inp.stats)
    compare = sel.chosen if sel.chosen != BASE else sel.best
    median = inp.stats[BASE]["median"]  # article 청크 = 조문 하나
    parts = [
        [_headline(sel)],
        _section_conclusion(inp, sel),
        _section_table(inp),
        _section_long(inp, median),
        _section_split(inp, compare, sel.chosen),
        _section_faq(inp),
        _section_samples(inp),
        _section_spacing(inp),
        _section_checks(inp),
    ]
    text = "\n\n".join("\n".join(p) for p in parts) + "\n"
    v = sel.verdicts[sel.best]
    selected = {
        "candidate": sel.chosen,
        "compare_candidate": compare,
        "best_candidate": sel.best,
        "zone": sel.zone,
        "best_diff": {"mean": v.mean, "lo": v.lo, "hi": v.hi, "p": v.p},
        "rule": (
            "hybrid recall@5 차이의 95% CI 하한이 0보다 큰 후보 중 평균이 가장 큰 것, "
            "없으면 article"
        ),
    }
    return text, selected


# ── 실행 ────────────────────────────────────────────────────────────────


def compute_samples(embedder, candidates: list[str], law_rows=None, faq_rows=None) -> list[dict]:
    """설계 §3의 질문 9개를 후보마다 검색한다. FAQ는 같은 질문 텍스트의 쌍을 뺀다."""
    from cheongyak_rag.retrieval.query import Index

    faq_rows = load_faq() if faq_rows is None else faq_rows
    by_no = {r["q_no"]: r["question"] for r in faq_rows}
    questions = [(SAMPLE_QUESTION, "main 세션이 쓴 질문")] + [
        (by_no[n], f"FAQ Q{n}") for n in SAMPLE_FAQ_Q_NOS
    ]
    indexes = {c: Index(c, embedder, law_rows=law_rows, faq_rows=faq_rows) for c in candidates}
    out = []
    for question, origin in questions:
        results = {}
        for c, idx in indexes.items():
            res = idx.search(question, 5, faq_k=3, exclude_same_question=True)
            results[c] = {
                "law": [(x.label, x.path) for x in res["law"]],
                "faq": [(x.meta["q_no"], x.text.partition("\n")[0]) for x in res["faq"]],
            }
        out.append({"question": question, "origin": origin, "results": results})
    return out


def _load_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _load_inputs(runs_dir: Path, embedder) -> Inputs:
    golden = load_golden()
    results = {}
    for c in CANDIDATES:
        path = runs_dir / c / "results.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"{path} 없음. 먼저 chunk_eval --candidate {c}")
        results[c] = _load_lines(path)
        if [x["qid"] for x in results[c]] != [g["qid"] for g in golden]:
            raise ValueError(f"{c} run의 질문이 golden과 다르다. 다시 돌릴 것")
    ref = {r: [x for x in v] for r, v in load_results(RUNS_DIR).items()}
    ref131 = {r: float(np.mean([x["recall@5"] for x in ref[r]])) for r in RANKERS}
    rows = load_law_rows(LAW_PATH)
    arts = load_articles(LAW_PATH)
    lengths = {a.label: len(a.text) for a in arts}
    stats, checks = {}, {"preservation": {}, "short": {}}
    for c in CANDIDATES:
        chunks = law_chunks(rows, c)
        sizes = [len(x.text) for x in chunks]
        stats[c] = {"count": len(chunks), "median": statistics.median(sizes), "max": max(sizes)}
        checks["preservation"][c] = check_preservation(rows, c)
        checks["short"][c] = {
            "ratio": short_ratio(chunks),
            "items": [(x.path, strip_head(x)) for x in chunks if len(strip_head(x)) < SHORT_CHARS],
        }
    faq_path = runs_dir / "faq" / "results.jsonl"
    spacing_path = runs_dir / "spacing.json"
    check_path = runs_dir / "faq" / "self_check.json"
    for p in (faq_path, spacing_path, check_path):
        if not p.exists():
            raise FileNotFoundError(f"{p} 없음. chunk_eval --faq 와 chunk_spacing 을 먼저 돌린다")
    term = "무주택세대구성원"
    obs = {
        "kiwi": [(t.form, t.tag) for t in _kiwi().tokenize(term)],
        "bm25": tokenize(term),
    }
    sel = select(results, stats)
    compare = sel.chosen if sel.chosen != BASE else sel.best
    samples = compute_samples(embedder, list(dict.fromkeys([BASE, compare])), rows, None)
    return Inputs(
        results=results,
        stats=stats,
        titles={a.label: a.title for a in arts},
        long_qids=long_qids(golden, lengths),
        ref131=ref131,
        faq_lines=_load_lines(faq_path),
        self_check=json.loads(check_path.read_text(encoding="utf-8")),
        spacing=json.loads(spacing_path.read_text(encoding="utf-8")),
        samples=samples,
        checks=checks,
        observation=obs,
    )


def main(runs_dir: Path = RUNS73, out: Path = REPORT_PATH, embedder=None) -> int:
    embedder = embedder or Embedder(settings.openai_embed_model)
    inp = _load_inputs(runs_dir, embedder)
    text, selected = build_report(inp)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    (runs_dir / "selected.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(text.splitlines()[0])
    print(f"→ {out} · {runs_dir / 'selected.json'} · OpenAI 호출 {embedder.api_calls}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
