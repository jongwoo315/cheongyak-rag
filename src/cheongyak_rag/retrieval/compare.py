"""세 run을 비교해 `docs/131-dense-vs-hybrid.md` 한 장을 쓴다 (#131).

    python -m cheongyak_rag.retrieval.compare

판정: 문항별 차이로 paired permutation 검정(10,000회, seed 0)과 bootstrap 95% 신뢰구간
(10,000회, seed 0). 주 지표는 측정 전에 recall@5로 정했다.
"""

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cheongyak_rag.retrieval.corpus import LAW_PATH, Article, load_articles
from cheongyak_rag.retrieval.evaluate import RRF_K, K
from cheongyak_rag.retrieval.golden import (
    GOLDEN_PATH,
    RUNS_DIR,
    GoldenResult,
    build_golden,
    load_faq,
)

REPORT_PATH = Path(__file__).resolve().parents[3] / "docs" / "131-dense-vs-hybrid.md"
N_ITER = 10_000
HALF_WIDTH_LIMIT = 0.05
Z95 = 1.96
PRIMARY = "recall@5"
METRICS = ("recall@5", "hit@1", "hit@5", "mrr")
RUNS = ("bm25", "dense", "hybrid")
LENGTH_BINS = ((0, 500), (500, 1000), (1000, 2000), (2000, math.inf))


# ── 통계 ────────────────────────────────────────────────────────────────


def paired_permutation_p(diffs: np.ndarray, n_iter: int = N_ITER, seed: int = 0) -> float:
    """문항별 차이의 부호를 무작위로 뒤집어 평균 절댓값이 관측치 이상인 비율.

    양측 검정이고 더하기 1 보정을 한다.
    """
    diffs = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_iter, len(diffs)))
    means = np.abs((signs * diffs).mean(axis=1))
    observed = abs(diffs.mean())
    return float((np.sum(means >= observed - 1e-12) + 1) / (n_iter + 1))


def bootstrap_ci(
    diffs: np.ndarray, n_iter: int = N_ITER, seed: int = 0, level: float = 0.95
) -> tuple[float, float]:
    diffs = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diffs), size=(n_iter, len(diffs)))
    means = diffs[idx].mean(axis=1)
    lo, hi = np.percentile(means, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


@dataclass
class Verdict:
    kind: str  # 차이 있음 | 차이 없음 | 판정 불가
    mean: float
    lo: float
    hi: float
    p: float
    sd: float
    needed_n: int | None  # 판정 불가일 때, 반폭 0.05에 필요한 문항 수

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2


def verdict(diffs: np.ndarray) -> Verdict:
    diffs = np.asarray(diffs, dtype=float)
    lo, hi = bootstrap_ci(diffs)
    p = paired_permutation_p(diffs)
    mean = float(diffs.mean())
    sd = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 0.0
    needed = None
    if lo > 0 or hi < 0:
        kind = "차이 있음"
    elif (hi - lo) / 2 <= HALF_WIDTH_LIMIT:
        kind = "차이 없음"
    else:
        kind = "판정 불가"
        needed = math.ceil((Z95 * sd / HALF_WIDTH_LIMIT) ** 2)
    return Verdict(kind, mean, lo, hi, p, sd, needed)


# ── 읽기·검사 ───────────────────────────────────────────────────────────


def load_results(runs_dir: Path) -> dict[str, list[dict]]:
    out = {}
    for run in RUNS:
        path = runs_dir / run / "results.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"{path} 없음. 먼저 evaluate --run {run}")
        out[run] = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    return out


def check_runs(results: dict[str, list[dict]], golden: list[dict]) -> None:
    """세 run이 golden과 같은 질문 집합이어야 비교가 성립한다."""
    want = [g["qid"] for g in golden]
    for run, lines in results.items():
        got = [x["qid"] for x in lines]
        if len(got) != len(want) or set(got) != set(want):
            raise ValueError(f"{run} run의 질문이 golden과 다르다 (줄 {len(got)} vs {len(want)})")


def _pair(results: dict[str, list[dict]]) -> list[tuple[dict, dict, dict]]:
    """질문 id로 맞춘 (bm25, dense, hybrid) 줄. golden 순서."""
    by = {run: {x["qid"]: x for x in lines} for run, lines in results.items()}
    return [(by["bm25"][q], by["dense"][q], by["hybrid"][q]) for q in by["dense"]]


# ── 글 만들기 ───────────────────────────────────────────────────────────


def _sgn(x: float) -> str:
    return f"{x:+.3f}"


def _ci(v: Verdict) -> str:
    return f"[{_sgn(v.lo)}, {_sgn(v.hi)}]"


def _esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _title(titles: dict[str, str], label: str) -> str:
    return f"{label}({titles[label]})"


def _stat_row(name: str, diffs: np.ndarray) -> str:
    v = verdict(diffs)
    return f"| {name} | {_sgn(v.mean)} | {_ci(v)} | {v.p:.4f} | {v.kind} |"


def _conclusion(v: Verdict) -> str:
    head = f"hybrid가 dense보다 {PRIMARY}가 {_sgn(v.mean)} (95% CI {_ci(v)}, p={v.p:.4f})"
    if v.kind == "차이 있음":
        return f"{head} — 신뢰구간이 0을 포함하지 않아 차이 있음."
    if v.kind == "차이 없음":
        return f"{head} — 신뢰구간이 0을 포함하고 반폭이 {v.half_width:.3f}(0.05 이하)라 차이 없음."
    return (
        f"{head} — 신뢰구간이 0을 포함하고 반폭이 {v.half_width:.3f}로 0.05를 넘어 "
        f"문항 부족으로 판정 불가."
    )


def _subset_line(name: str, full: Verdict, rows, keep) -> tuple[str, Verdict | None]:
    """부분집합(keep으로 거른 질문)에서 hybrid−dense recall@5 차이와 부호 비교 한 줄."""
    sub = [(d, h) for _, d, h in rows if keep(d)]
    if not sub:
        return f"- {name}: 남는 질문이 없다", None
    v = verdict(np.array([h[PRIMARY] - d[PRIMARY] for d, h in sub]))
    opposite = full.mean * v.mean < 0
    mark = "⚠ 부호가 전체 결과와 반대" if opposite else "부호는 전체와 같다"
    return (
        f"- {name}: 질문 {len(sub)}개, hybrid−dense {PRIMARY} {_sgn(v.mean)} "
        f"(95% CI {_ci(v)}, p={v.p:.4f}) — {mark}",
        v,
    )


def _rank_cell(titles, label, bm, dn, hy) -> str:
    return f"{_title(titles, label)}: BM25 {bm} · dense {dn} · hybrid {hy}"


def _split(rows):
    """hit@5 기준 dense/hybrid 네 칸."""
    both, d_only, h_only, neither = [], [], [], []
    for row in rows:
        d, h = row[1], row[2]
        (
            both
            if d["hit@5"] and h["hit@5"]
            else d_only
            if d["hit@5"]
            else h_only
            if h["hit@5"]
            else neither
        ).append(row)
    return both, d_only, h_only, neither


def _best(detail: dict, gold: list[str], key: str) -> int:
    return min(detail[g][key] for g in gold)


def _reason(row) -> tuple[str, str]:
    """(맞힌 쪽, 묶음 이름). 정답이 여럿이면 가장 높은 순위를 쓴다."""
    _, d, h = row
    detail = h["gold_detail"]
    b = _best(detail, h["gold"], "bm25")
    if h["hit@5"]:
        if b <= K:
            return "hybrid", "BM25가 끌어올림"
        return "hybrid", "합산 효과"
    if b > K:
        return "dense", "BM25가 끌어내림"
    return "dense", "합쳤더니 다른 조가 위로"


REASON_TEXT = {
    "BM25가 끌어올림": "정답의 BM25 순위가 5위 안이고 dense는 5위 밖이다. BM25가 정답을 올렸다",
    "합산 효과": "BM25와 dense 모두 정답이 5위 밖인데 RRF로 합치니 5위 안이 됐다",
    "BM25가 끌어내림": "dense는 5위 안인데 정답의 BM25 순위가 5위 밖이라 합친 순위가 밀렸다",
    "합쳤더니 다른 조가 위로": "BM25·dense 모두 정답이 5위 안인데 합치니 다른 조 5개가 위다",
}


def _section_summary(results, rows, articles_n, golden_n, full: Verdict) -> list[str]:
    out = ["## 1. 요약", ""]
    out.append(
        f"- 질문 {golden_n}개, 문서(현행 조문) {articles_n}개. 세 run이 같은 질문 집합에서 돌았다"
        f"(질문 id 집합 일치를 확인했다)."
    )
    out.append("- baseline 없음 — 이번이 첫 측정, 다음 티켓의 기준이 된다.")
    out.append(
        f"- `{PRIMARY}`는 질문마다 정답 조 중 상위 {K}개 안에 든 비율이다. "
        "측정 전에 주 지표로 정했다. "
        "`hit@k`는 정답이 하나라도 상위 k개 안에 있는 질문의 비율, "
        "`mrr`은 첫 정답 순위의 역수 평균이다."
    )
    out += ["", "### 세 run의 평균", "", "| run | " + " | ".join(METRICS) + " |"]
    out.append("|" + " --- |" * (len(METRICS) + 1))
    for i, run in enumerate(RUNS):
        vals = " | ".join(f"{np.mean([r[i][m] for r in rows]):.3f}" for m in METRICS)
        out.append(f"| {run} | {vals} |")
    out += ["", "### dense 대비 hybrid", ""]
    out += [
        "| 지표 | hybrid−dense 평균 | 95% CI | p (permutation) | 구간 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in METRICS:
        out.append(
            _stat_row(
                m + (" (주)" if m == PRIMARY else ""), np.array([r[2][m] - r[1][m] for r in rows])
            )
        )
    out += ["", "참고 — BM25 대비 hybrid (본 비교는 dense 대비다):", ""]
    out += [
        "| 지표 | hybrid−BM25 평균 | 95% CI | p (permutation) | 구간 |",
        "| --- | --- | --- | --- | --- |",
    ]
    out.append(
        _stat_row(f"{PRIMARY} (주)", np.array([r[2][PRIMARY] - r[0][PRIMARY] for r in rows]))
    )
    out += ["", "### 판정 구간 (주 지표)", ""]
    out.append(f"- 구간: **{full.kind}**")
    if full.kind == "판정 불가":
        out.append(
            f"- 문항별 차이의 표준편차 {full.sd:.3f}로 반폭 0.05에 필요한 문항 수를 계산하면 "
            f"{full.needed_n}개다 (⌈(1.96×{full.sd:.3f}/0.05)²⌉). 지금은 {golden_n}개다."
        )
    return out


def _rrf_example(rows, titles) -> list[str]:
    _, d_only, h_only, _ = _split(rows)
    pool = [r for r in h_only if len(r[2]["gold"]) == 1] or h_only or d_only or rows
    row = pool[0]
    h = row[2]
    top = h["top5_detail"]
    labels = list(top) + [g for g in h["gold"] if g not in top]
    out = ["## 2. RRF 풀이 — 질문 한 건", ""]
    out.append(
        f"{h['qid']}: 「{_esc(h['question'])}」 — 정답 "
        + ", ".join(_title(titles, g) for g in h["gold"])
    )
    out += [
        "",
        f"RRF 점수는 `Σ 1/({RRF_K} + 순위)`이고 순위는 1부터 센다.",
        "점수가 같으면 BM25 순위가 앞선 쪽이 위다.",
        "",
    ]
    out += [
        "| hybrid 순위 | 조 | 정답 | BM25 순위 | BM25 몫 | dense 순위 | dense 몫 | 합 (RRF 점수) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label in labels:
        d = top.get(label) or h["gold_detail"][label]
        rank = h["top5"].index(label) + 1 if label in h["top5"] else h["gold_rank"][label]
        mark = "정답" if label in h["gold"] else ""
        out.append(
            f"| {rank} | {_title(titles, label)} | {mark} | {d['bm25']} "
            f"| {1 / (RRF_K + d['bm25']):.6f} "
            f"| {d['dense']} | {1 / (RRF_K + d['dense']):.6f} | {d['rrf']:.6f} |"
        )
    g = h["gold"][0]
    gd = h["gold_detail"][g]
    out += [
        "",
        f"정답 {g}: BM25 {gd['bm25']}위 → 1/({RRF_K}+{gd['bm25']}) "
        f"= {1 / (RRF_K + gd['bm25']):.6f}, "
        f"dense {gd['dense']}위 → 1/({RRF_K}+{gd['dense']}) = {1 / (RRF_K + gd['dense']):.6f}, "
        f"합 {gd['rrf']:.6f} → hybrid {h['gold_rank'][g]}위.",
    ]
    return out


def _section_2x2(rows) -> list[str]:
    both, d_only, h_only, neither = _split(rows)
    return [
        "## 3. 2×2 표 — `hit@5` 기준",
        "",
        "| | hybrid 맞힘 | hybrid 놓침 |",
        "| --- | --- | --- |",
        f"| dense 맞힘 | {len(both)} | {len(d_only)} |",
        f"| dense 놓침 | {len(h_only)} | {len(neither)} |",
        "",
        f"dense와 hybrid의 `hit@5`가 다른 질문은 {len(d_only) + len(h_only)}개다. "
        "다음 절에 전부 있다.",
    ]


def _section_disagreements(rows, titles) -> tuple[list[str], list[tuple]]:
    _, d_only, h_only, _ = _split(rows)
    diff = sorted(d_only + h_only, key=lambda r: r[2]["q_no"])
    out = [
        "## 4. 갈린 질문 전부",
        "",
        f"`hit@5`가 dense와 hybrid에서 다른 {len(diff)}개 질문이다. "
        "정답이 여럿이면 줄마다 정답 조를 따로 적는다.",
        "",
    ]
    out += ["| 질문 | 맞힌 쪽 | 정답 조별 순위 | dense 상위 3개 |", "| --- | --- | --- | --- |"]
    for _, d, h in diff:
        cells = []
        for g in h["gold"]:
            det = h["gold_detail"].get(g)
            hy, dn = h["gold_rank"].get(g), d["gold_rank"].get(g)
            if det is None or hy is None or dn is None or det["dense"] != dn:
                raise ValueError(f"{h['qid']} {g}: 순위 칸이 비었거나 dense run과 어긋난다")
            cells.append(_rank_cell(titles, g, det["bm25"], det["dense"], hy))
        who = "hybrid만" if h["hit@5"] else "dense만"
        top3 = ", ".join(_title(titles, x) for x in d["top5"][:3])
        out.append(
            f"| {h['qid']} 「{_esc(h['question'])}」 | {who} | {'<br>'.join(cells)} | {top3} |"
        )
    return out, diff


def _section_reasons(diff) -> list[str]:
    groups: dict[str, list[str]] = {}
    for row in diff:
        _, name = _reason(row)
        groups.setdefault(name, []).append(row[2]["qid"])
    out = [
        "## 5. 갈린 이유 묶음",
        "",
        "정답이 여럿이면 가장 높은 순위를 쓴다. 기준은 위 절의 순위 칸이다.",
        "",
    ]
    out += ["| 묶음 | 맞힌 쪽 | 뜻 | 질문 수 | 질문 |", "| --- | --- | --- | --- | --- |"]
    for name in REASON_TEXT:
        qids = groups.get(name, [])
        side = "hybrid만" if name in ("BM25가 끌어올림", "합산 효과") else "dense만"
        out.append(
            f"| {name} | {side} | {REASON_TEXT[name]} | {len(qids)} | {', '.join(qids) or '—'} |"
        )
    return out


def _section_labels(gr: GoldenResult) -> list[str]:
    names = {"rule": "규칙", "other": "다른 법령", "none": "이름 없음"}
    out = ["## 6. 정답 라벨 — 표본 20개와 분류별 인용 수", ""]
    out.append(
        "FAQ 답변 원문에서 인용 자리마다 같은 문장 안의 가장 가까운 앞 법령 이름을 보고 나눴다. "
        "규칙과 이름 없음을 정답에 넣고 다른 법령은 뺐다. 「이름 없음 = 규칙」은 가정이다 — "
        "아래 표본으로 눈으로 확인한다."
    )
    out += ["", "| 분류 | 인용 수 | 정답에 넣나 |", "| --- | --- | --- |"]
    for k, put in (("rule", "넣는다"), ("none", "넣는다 (가정)"), ("other", "안 넣는다")):
        out.append(f"| {names[k]} | {gr.counts[k]} | {put} |")
    dropped = ", ".join(f"{k} {v}개" for k, v in gr.dropped.items()) or "없음"
    out += [
        "",
        f"남은 질문 {len(gr.rows)}개. 뺀 질문: {dropped}.",
        "",
        "이름 없음 인용 표본 (인용 앞 60자, 【】가 인용):",
        "",
    ]
    out += [f"1. {_esc(s)}" for s in gr.none_samples] or ["(이름 없는 인용이 없다)"]
    return out


def _section_subsets(full: Verdict, rows) -> tuple[list[str], list[str]]:
    l1, _ = _subset_line(
        "질문에 `제N조`가 든 질문을 뺀 결과", full, rows, lambda d: not d["has_article_in_question"]
    )
    l2, _ = _subset_line(
        "`제53조`가 정답에 든 질문을 뺀 결과", full, rows, lambda d: "제53조" not in d["gold"]
    )
    n1 = sum(d["has_article_in_question"] for _, d, _ in rows)
    n2 = sum("제53조" in d["gold"] for _, d, _ in rows)
    out = ["## 7. 질문에 `제N조`가 든 질문을 뺀 결과", ""]
    out.append(
        f"질문 원문에 `제N조`가 든 질문이 {n1}개다. BM25는 숫자를 그대로 맞히므로 이 질문들이 "
        "결과를 끌고 가는지 본다."
    )
    out += ["", l1, "", "## 8. `제53조`가 정답에 든 질문을 뺀 결과", ""]
    out.append(
        f"`제53조`가 정답에 든 질문이 {n2}개다 (한 조에 몰린 질문이 평균을 끌고 가는지 본다)."
    )
    out += ["", l2]
    return out, [l1, l2]


def _section_sanity(rows: list[dict] | None) -> list[str]:
    out = ["## 9. 점검 run — 조문 첫 문장을 질문으로 넣었을 때", ""]
    if not rows:
        return out + ["점검 결과 파일이 없다. `evaluate --sanity`를 먼저 돌린다."]
    n = len(rows)
    bm = sum(r["bm25_rank"] == 1 for r in rows)
    dn = sum(r["dense_rank"] == 1 for r in rows)
    bm_band = (
        "통과"
        if bm == 20
        else "놓친 것을 PR 본문에 적는다"
        if bm >= 18
        else "토크나이저·색인 버그 — 고친다"
    )
    dn_band = (
        "통과"
        if dn >= 18
        else "놓친 것을 PR 본문에 적는다"
        if dn >= 15
        else "임베딩 입력 의심 — 고친다"
    )
    out.append(
        f"현행 조문 {n}개(조 번호 순으로 고르게)의 본문 첫 문장을 질문으로 넣어 "
        "그 조가 1위인지 봤다."
    )
    out += ["", f"- BM25 {bm}/{n}개 1위 — {bm_band}", f"- dense {dn}/{n}개 1위 — {dn_band}", ""]
    for name in ("bm25", "dense"):
        for r in rows:
            if r[f"{name}_rank"] != 1:
                out.append(
                    f"- {name} 놓침 {r['label']}: 질문 「{_esc(r['query'][:60])}」 → "
                    f"1위 {r[f'{name}_top1']}, 자기 순위 {r[f'{name}_rank']}"
                )
    return out


def _section_length(rows, articles: list[Article]) -> list[str]:
    length = {a.label: len(a.text) for a in articles}
    out = ["## 10. 정답 조 글자 수별 `recall@5`", ""]
    out.append(
        "질문마다 정답 조 중 가장 긴 조의 글자 수로 묶었다. 긴 조가 dense에서 불리한지 본다."
    )
    out += ["", "| 글자 수 | 질문 수 | BM25 | dense | hybrid |", "| --- | --- | --- | --- | --- |"]
    for lo, hi in LENGTH_BINS:
        sel = [r for r in rows if lo <= max(length[g] for g in r[1]["gold"]) < hi]
        if not sel:
            continue
        name = f"{lo}자 이상" if math.isinf(hi) else f"{lo}~{hi - 1}자"
        vals = " | ".join(f"{np.mean([r[i][PRIMARY] for r in sel]):.3f}" for i in range(3))
        out.append(f"| {name} | {len(sel)} | {vals} |")
    return out


def build_report(
    results: dict[str, list[dict]],
    golden_result: GoldenResult,
    articles: list[Article],
    sanity_rows: list[dict] | None,
) -> str:
    rows = _pair(results)
    titles = {a.label: a.title for a in articles}
    full = verdict(np.array([h[PRIMARY] - d[PRIMARY] for _, d, h in rows]))
    sub_out, sub_lines = _section_subsets(full, rows)
    summary = _section_summary(results, rows, len(articles), len(rows), full)
    summary += ["", "### 부분집합에서도 같은 방향인가", ""] + sub_lines
    dis_out, diff = _section_disagreements(rows, titles)
    parts = [
        [_conclusion(full)],
        summary,
        _rrf_example(rows, titles),
        _section_2x2(rows),
        dis_out,
        _section_reasons(diff),
        _section_labels(golden_result),
        sub_out,
        _section_sanity(sanity_rows),
        _section_length(rows, articles),
    ]
    return "\n\n".join("\n".join(p) for p in parts) + "\n"


def main(runs_dir: Path = RUNS_DIR, out: Path = REPORT_PATH) -> int:
    golden = [json.loads(x) for x in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if x]
    results = load_results(runs_dir)
    check_runs(results, golden)
    articles = load_articles(LAW_PATH)
    gr = build_golden(load_faq(), {a.label for a in articles})
    sanity_path = runs_dir / "sanity" / "results.jsonl"
    sanity = (
        [json.loads(x) for x in sanity_path.read_text(encoding="utf-8").splitlines() if x]
        if sanity_path.exists()
        else None
    )
    text = build_report(results, gr, articles, sanity)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.splitlines()[0])
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
