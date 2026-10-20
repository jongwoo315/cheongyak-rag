"""#131 점검 run에서 놓친 조를 청킹 후보로 다시 보기 (#138).

    python -m cheongyak_rag.retrieval.miss

묶음 A — #131 점검 질문 20개를 후보 5개로 다시 넣는다(`sanity_by_candidate`).
묶음 B — #131 hybrid가 golden에서 hit@5 = 0이던 문항을 `runs/73/`에서 다시 읽는다(`golden_misses`).
원인 — `article` 후보에서 놓친 조의 점수·코사인·글자 수(`build_causes`).
새 검색 구조를 정하지 않는다. `runs/73/selected.json`과 #131 run은 읽기만 한다.
"""

import json
import re
import statistics
import sys
from pathlib import Path

import numpy as np

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval import chunk_eval
from cheongyak_rag.retrieval.chunk import CANDIDATES, law_chunks, load_law_rows
from cheongyak_rag.retrieval.corpus import LAW_PATH, Article, load_articles
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.evaluate import SANITY_N, first_sentence, pick_sanity
from cheongyak_rag.retrieval.golden import RUNS_DIR
from cheongyak_rag.retrieval.search import BM25, dense_rank


def sanity_by_candidate(
    rows: list[dict],
    articles: list[Article],
    embedder,
    candidates: tuple[str, ...] = CANDIDATES,
    n: int = SANITY_N,
) -> list[dict]:
    """후보 × 점검 질문 한 줄씩. 질문은 #131 `run_sanity`와 같은 `pick_sanity`·`first_sentence`."""
    picked = pick_sanity(articles, n)
    queries = [first_sentence(a) for a in picked]
    out = []
    for cand in candidates:
        chunks = law_chunks(rows, cand)
        by_id = {c.chunk_id: c for c in chunks}
        ids = list(by_id)
        bm25 = BM25([chunk_eval._Doc(c.chunk_id, c.text) for c in chunks])
        vecs = embedder.embed([c.text for c in chunks] + queries)
        doc_vecs, query_vecs = vecs[: len(chunks)], vecs[len(chunks) :]
        for art, q, qv in zip(picked, queries, query_vecs, strict=True):
            ar = chunk_eval.article_ranks(
                [by_id[x] for x in bm25.rank(q)], [by_id[x] for x in dense_rank(qv, doc_vecs, ids)]
            )
            line = {"candidate": cand, "label": art.label, "query": q, "query_chars": len(q)}
            for name in chunk_eval.RANKERS:
                line[f"{name}_rank"] = ar.pos[name][art.label]
                line[f"{name}_top1"] = ar.rankings[name][0]
            for name in ("bm25", "dense"):
                own = by_id[f"law:{ar.paths[name][art.label]}"]
                line[f"{name}_own_path"] = own.path
                line[f"{name}_own_chars"] = len(own.text)
                line[f"{name}_own_has_query"] = q in own.text
            out.append(line)
    return out


# ── 묶음 B — golden에서 #131 hybrid가 놓친 문항 ─────────────────────────────

GAP = 3  # 실패 징후 1 B — F − L이 이 값 이상이면 찾은 쪽, 이 값 이하(음수)면 놓친 쪽


def golden_band(found: int, lost: int) -> str:
    diff = found - lost
    if diff >= GAP:
        return "찾은 것이 더 많다"
    if diff <= -GAP:
        return "놓친 것이 더 많다"
    return "차이 없음"


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def compare_golden(base: list[dict], cand: list[dict]) -> dict:
    """#131 hybrid 줄(`base`)과 후보 run 줄(`cand`)을 같은 질문끼리 대조한다.

    found = #131이 놓쳤는데 후보가 맞힌 문항, lost = #131이 맞혔는데 후보가 놓친 문항.
    순위는 정답 조 중 가장 높은 것.
    """
    if [x["qid"] for x in base] != [x["qid"] for x in cand]:
        raise ValueError("두 run의 질문(qid)과 순서가 다르다")
    found, lost = [], []
    for b, c in zip(base, cand, strict=True):
        ch = c["hybrid"]
        if b["hit@5"] == ch["hit@5"]:
            continue
        row = {
            "qid": b["qid"],
            "question": b["question"],
            "gold": b["gold"],
            "base_rank": min(b["gold_rank"].values()),
            "cand_rank": min(ch["gold_rank"].values()),
        }
        (found if b["hit@5"] == 0 else lost).append(row)
    return {
        "found_count": len(found),
        "lost_count": len(lost),
        "band": golden_band(len(found), len(lost)),
        "found": found,
        "lost": lost,
    }


def golden_misses(
    runs_dir: Path = RUNS_DIR,
    runs73: Path | None = None,
    candidates: tuple[str, ...] = CANDIDATES,
) -> dict:
    """{"total": 질문 수, "missed": #131 hybrid가 놓친 qid, "candidates": {후보: 대조 결과}}."""
    base = _read_lines(runs_dir / "hybrid" / "results.jsonl")
    runs73 = runs73 or runs_dir / "73"
    return {
        "total": len(base),
        "missed": [x["qid"] for x in base if x["hit@5"] == 0],
        "candidates": {
            cand: compare_golden(base, _read_lines(runs73 / cand / "results.jsonl"))
            for cand in candidates
        },
    }


# ── 원인 — `article` 후보에서 놓친 조 ────────────────────────────────────────

TOP_TERMS = 5  # 낱말별 기여 중 보여줄 상위 개수
SUM_TOLERANCE = 1e-9  # 실패 징후 4 — 낱말별 기여의 합과 BM25.scores의 차


def bm25_terms(bm25: BM25, query: str, label: str) -> dict[str, float]:
    """질문 낱말마다 그 문서의 BM25 점수 기여(idf × tf 항). 기여가 큰 순서.

    `BM25.scores`와 같은 식이다 — 질문 낱말은 집합으로 세고, 문서에 없는 낱말은 기여 0이라 뺀다.
    """
    i = bm25.labels.index(label)
    tf, length = bm25.tf[i], bm25.lengths[i]
    norm = bm25.k1 * (1 - bm25.b + bm25.b * length / bm25.avg_len)
    terms = set(bm25.tokenizer(query)) & bm25.idf.keys()
    contrib = {t: bm25.idf[t] * tf[t] * (bm25.k1 + 1) / (tf[t] + norm) for t in terms if t in tf}
    return dict(sorted(contrib.items(), key=lambda kv: (-kv[1], kv[0])))


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def _terms_text(terms: dict[str, float]) -> str:
    top = list(terms.items())[:TOP_TERMS]
    return ", ".join(f"{t} {v:.3f}" for t, v in top) or "없음"


CITED_KEYS = {
    "bm25": ("own_score", "top1_score"),
    "dense": ("own_cos", "top1_cos", "item_best_cos"),
}


def cites_number(cause: dict) -> bool:
    """원인 문장이 그 retriever의 숫자(점수 둘 또는 코사인 셋)를 모두 글자로 담고 있나(실패 징후 3).

    숫자는 앞뒤에 숫자·점이 붙지 않은 낱개 토큰으로 찾는다.
    `32.079`가 `132.0791` 안에서 걸리지 않는다.
    """
    return all(
        re.search(rf"(?<![\d.]){re.escape(f'{cause[k]:.3f}')}(?!\d)", cause["sentence"])
        for k in CITED_KEYS[cause["retriever"]]
    )


def build_causes(
    lines: list[dict], articles: list[Article], rows: list[dict], embedder
) -> list[dict]:
    """`article` 후보 점검 줄 중 자기 조가 1위가 아니던 (retriever, 조) 마다 원인 숫자와 문장."""
    misses = [
        (name, x)
        for x in lines
        if x["candidate"] == "article"
        for name in ("bm25", "dense")
        if x[f"{name}_rank"] != 1
    ]
    if not misses:
        return []
    by_label = {a.label: i for i, a in enumerate(articles)}
    chars = [len(a.text) for a in articles]
    median = statistics.median(chars)
    bm25 = BM25(articles)
    items = law_chunks(rows, "item")
    queries = list(dict.fromkeys(x["query"] for _, x in misses))
    vecs = embedder.embed([a.text for a in articles] + [c.text for c in items] + queries)
    art_vecs = vecs[: len(articles)]
    item_vecs = vecs[len(articles) : len(articles) + len(items)]
    query_vecs = dict(zip(queries, vecs[len(articles) + len(items) :], strict=True))
    out = []
    for name, x in misses:
        label, top1, q = x["label"], x[f"{name}_top1"], x["query"]
        own_i, top_i = by_label[label], by_label[top1]
        cause = {
            "retriever": name,
            "label": label,
            "query": q,
            "own_rank": x[f"{name}_rank"],
            "top1": top1,
            "own_chars": chars[own_i],
            "top1_chars": chars[top_i],
            "median_chars": median,
            "own_tokens": bm25.lengths[own_i],
            "top1_tokens": bm25.lengths[top_i],
            "avg_tokens": bm25.avg_len,
        }
        size = (
            f"자기 조 {chars[own_i]}자(조문 글자 수 중앙값 {median:g}자의"
            f" {chars[own_i] / median:.1f}배)·토큰 {bm25.lengths[own_i]}개,"
            f" 1위 {top1} {chars[top_i]}자·토큰 {bm25.lengths[top_i]}개"
        )
        if name == "bm25":
            own_t, top_t = bm25_terms(bm25, q, label), bm25_terms(bm25, q, top1)
            scores = bm25.scores(q)
            cause |= {
                "own_score": scores[own_i],
                "top1_score": scores[top_i],
                "own_terms": own_t,
                "top1_terms": top_t,
                "own_terms_gap": abs(sum(own_t.values()) - scores[own_i]),
                "top1_terms_gap": abs(sum(top_t.values()) - scores[top_i]),
            }
            cause["sentence"] = (
                f"{label}: BM25 점수 {scores[own_i]:.3f}(자기 조 {x['bm25_rank']}위),"
                f" 1위 {top1} {scores[top_i]:.3f}."
                f" 낱말별 기여 — 자기 조 {_terms_text(own_t)} / 1위 조 {_terms_text(top_t)}."
                f" {size}(토큰 평균 {bm25.avg_len:.1f}개)."
            )
        else:
            qv = query_vecs[q]
            own_cos, top_cos = _cos(qv, art_vecs[own_i]), _cos(qv, art_vecs[top_i])
            own_items = [
                (c.path, _cos(qv, v))
                for c, v in zip(items, item_vecs, strict=True)
                if c.label == label
            ]
            best_path, best_cos = max(own_items, key=lambda kv: kv[1])
            cause |= {
                "own_cos": own_cos,
                "top1_cos": top_cos,
                "item_best_path": best_path,
                "item_best_cos": best_cos,
            }
            cause["sentence"] = (
                f"{label}: 질문과의 코사인 {own_cos:.3f}(자기 조 {x['dense_rank']}위),"
                f" 1위 {top1} {top_cos:.3f}. {size}."
                f" `item` 후보에서 자기 조 청크 중 질문과 가장 가까운 {best_path}의"
                f" 코사인은 {best_cos:.3f}."
            )
        out.append(cause)
    return out


# ── 묶음 A 요약 · 재현 ───────────────────────────────────────────────────

RUNS138 = RUNS_DIR / "138"
REPORT_PATH = Path(__file__).resolve().parents[3] / "docs" / "138-sanity-miss.md"
REPRO_KEYS = ("label", "query", "bm25_rank", "bm25_top1", "dense_rank", "dense_top1")


def band_a(found: int, total: int) -> str:
    """실패 징후 1 A — 놓쳤던 건 중 자기 조가 1위가 된 건수의 구간."""
    if total == 0:
        return "해당 없음"
    return "찾음" if found == total else "못 찾음" if found == 0 else "일부 찾음"


def summarize_a(lines: list[dict]) -> dict:
    """`article` 후보에서 놓친 (retriever, 질문) 건을 후보별로 다시 본다.

    후보마다 줄 순서가 같으므로(`sanity_by_candidate`) 질문은 후보 안의 순번으로 짝짓는다.
    """
    by_cand: dict[str, list[dict]] = {}
    for x in lines:
        by_cand.setdefault(x["candidate"], []).append(x)
    art = by_cand["article"]
    misses = [
        (name, i) for name in ("bm25", "dense") for i, x in enumerate(art) if x[f"{name}_rank"] != 1
    ]
    cands = {}
    for cand, sel in by_cand.items():
        picks = [(name, sel[i]) for name, i in misses]
        found = [(name, x) for name, x in picks if x[f"{name}_rank"] == 1]
        cands[cand] = {
            "top1": {r: sum(x[f"{r}_rank"] == 1 for x in sel) for r in chunk_eval.RANKERS},
            "ranks": [x[f"{name}_rank"] for name, x in picks],
            "found": len(found),
            "band": band_a(len(found), len(misses)),
            "top1_has_query": sum(x[f"{name}_own_has_query"] for name, x in found),
            "top1_chars": [x[f"{name}_own_chars"] for name, x in found],
            "query_chars": [x["query_chars"] for _, x in found],
        }
    return {
        "n": len(art),
        "misses": [(name, art[i]["label"]) for name, i in misses],
        "candidates": cands,
    }


def reproduce(lines: list[dict], sanity_rows: list[dict]) -> dict:
    """실패 징후 2 — `article` 후보 점검 줄이 #131 `runs/sanity`와 질문마다 같은가."""
    art = [x for x in lines if x["candidate"] == "article"]
    diffs = []
    if len(art) != len(sanity_rows):
        diffs.append({"key": "질문 수", "now": len(art), "before": len(sanity_rows)})
    for now, before in zip(art, sanity_rows, strict=False):
        diffs += [
            {"label": before["label"], "key": k, "now": now[k], "before": before[k]}
            for k in REPRO_KEYS
            if now[k] != before[k]
        ]
    return {
        "n": len(art),
        "diffs": diffs,
        "bm25_top1": sum(x["bm25_rank"] == 1 for x in art),
        "dense_top1": sum(x["dense_rank"] == 1 for x in art),
    }


# ── 리포트 ──────────────────────────────────────────────────────────────

OTHERS = CANDIDATES[1:]  # `article`은 #131과 같은 구조라 비교 기준이다
RETRIEVER_NAME = {"bm25": "BM25", "dense": "dense"}


def _c(cand: str) -> str:
    return f"`{cand}`"


def _esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    return out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def _list(nums: list[int]) -> str:
    return "·".join(str(n) for n in nums) or "—"


def _conclusion(a: dict, golden: dict) -> str:
    ca, gc = a["candidates"], golden["candidates"]
    part_a = " · ".join(f"{_c(c)} {ca[c]['found']}건({ca[c]['band']})" for c in OTHERS)
    part_b = " · ".join(
        f"{_c(c)} F {gc[c]['found_count']} · L {gc[c]['lost_count']}({gc[c]['band']})"
        for c in OTHERS
    )
    base_b = f"F {gc['article']['found_count']} · L {gc['article']['lost_count']}"
    return (
        f"#131 점검 run에서 놓친 {len(a['misses'])}건 중 자기 조가 1위가 된 건수는 {part_a}"
        f"(비교: `article` {ca['article']['found']}건)이며,"
        f" #131 hybrid가 놓친 golden {len(golden['missed'])}문항 중 후보가 맞힌 수 F와"
        f" #131이 맞힌 문항 중 후보가 놓친 수 L은 {part_b}(비교: `article` {base_b})이다."
    )


def _section_a(a: dict) -> list[str]:
    ca, n = a["candidates"], a["n"]
    miss_names = [f"{RETRIEVER_NAME[r]} {label}" for r, label in a["misses"]]
    out = [
        "## 1. 묶음 A — 점검 run을 후보별로 다시 돌린 값",
        "",
        "질문은 조문 머리 줄 다음 첫 줄의 첫 문장이다."
        f" `article` 후보에서는 {n}개 모두 자기 조 청크 안에 글자 그대로 있다."
        " 다른 후보에서는 자기 조 순위를 정하는 청크가 질문이 든 청크가 아닐 수 있다"
        "(아래 「글자 그대로 들어 있는 1위 청크」 열). 청크가 작을수록 청크와 질문이 거의 같은"
        " 글이 되므로, 아래 1위가 실제 사용자 질문에서도 나오는지는 이 측정만으로 알 수 없다.",
        "",
        f"### 질문 {n}개 중 자기 조가 1위인 수",
        "",
    ]
    out += _table(
        ["후보", "BM25", "dense", "hybrid"],
        [[_c(c)] + [f"{ca[c]['top1'][r]}/{n}" for r in chunk_eval.RANKERS] for c in ca],
    )
    out += ["", "### 놓쳤던 건의 자기 조 순위 (그 retriever에서)", ""]
    out += _table(
        ["후보"] + miss_names + ["찾은 건수", "구간"],
        [
            [_c(c), *ca[c]["ranks"], f"{ca[c]['found']}/{len(miss_names)}", ca[c]["band"]]
            for c in ca
        ],
    )
    out += [
        "",
        "### 찾은 건의 1위 청크 (찾지 못한 건은 1위가 다른 조라 뺐다)",
        "",
        "이 값은 구간을 바꾸지 않는다.",
        "",
    ]
    out += _table(
        ["후보", "질문 문장이 글자 그대로 들어 있는 1위 청크", "1위 청크 글자 수", "질문 글자 수"],
        [
            [
                _c(c),
                f"{ca[c]['top1_has_query']}/{ca[c]['found']}",
                _list(ca[c]["top1_chars"]),
                _list(ca[c]["query_chars"]),
            ]
            for c in ca
        ],
    )
    return out


def _qrows(rows: list[dict]) -> list[list]:
    return [
        [r["qid"], _esc(r["question"][:50]), "·".join(r["gold"]), r["base_rank"], r["cand_rank"]]
        for r in rows
    ]


def _section_b(golden: dict) -> list[str]:
    gc, m = golden["candidates"], len(golden["missed"])
    out = [
        "## 2. 묶음 B — golden에서 #131 hybrid가 놓친 문항",
        "",
        "이미 커밋된 run을 다시 읽은 값이다. 새로 잰 것이 아니다(`runs/hybrid`, `runs/73/<후보>`)."
        f" 질문 {golden['total']}개 중 #131 hybrid의 hit@5가 0인 문항은 {m}개다.",
        "",
    ]
    out += _table(
        ["후보", "찾은 수 F", "놓친 수 L", "F − L", "구간"],
        [
            [
                _c(c),
                gc[c]["found_count"],
                gc[c]["lost_count"],
                gc[c]["found_count"] - gc[c]["lost_count"],
                gc[c]["band"],
            ]
            for c in gc
        ],
    )
    head = ["qid", "질문", "정답 조", "#131 순위", "후보 순위"]
    for c in OTHERS:
        for title, key in (("찾은 문항", "found"), ("놓친 문항", "lost")):
            out += ["", f"### {_c(c)} {title} {len(gc[c][key])}개", ""]
            out += _table(head, _qrows(gc[c][key])) if gc[c][key] else ["없다."]
    return out


def _section_causes(causes: list[dict]) -> list[str]:
    gaps = [g for c in causes for k, g in c.items() if k.endswith("_terms_gap")]
    out = [
        "## 3. 원인 — `article`에서 놓친 건",
        "",
        "`item` 후보 코사인은 청크 본문이 질문과 글자까지 같으면 1.000이 된다."
        " 질문이 조문 첫 문장이라서 생기는 값이다.",
        "",
    ]
    out += [f"- {_esc(c['sentence'])}" for c in causes] or ["- 놓친 건이 없다."]
    out += [
        "",
        f"- 숫자를 인용하지 않은 원인 문장: {sum(not cites_number(c) for c in causes)}건",
        f"- BM25 낱말별 기여의 합과 `BM25.scores`의 차: 최대 {max(gaps, default=0.0):.1e}"
        f"(기준 {SUM_TOLERANCE:.0e})",
    ]
    return out


def _section_repro(repro: dict) -> list[str]:
    n = repro["n"]
    out = [
        "## 4. 재현 — `article` 후보 점검 run과 #131 `runs/sanity`",
        "",
        f"- `article` 후보: BM25 {repro['bm25_top1']}/{n} · dense {repro['dense_top1']}/{n}개 1위",
    ]
    if repro["diffs"]:
        out.append(f"- #131 `runs/sanity`와 다른 값 {len(repro['diffs'])}개:")
        out += [f"  - {d}" for d in repro["diffs"]]
    else:
        out.append(f"- 질문 {n}개 모두 자기 순위와 1위 조가 #131 `runs/sanity`와 같다.")
    return out


def build_report(lines: list[dict], golden: dict, causes: list[dict], repro: dict) -> str:
    a = summarize_a(lines)
    parts = [
        [_conclusion(a, golden)],
        _section_a(a),
        _section_b(golden),
        _section_causes(causes),
        _section_repro(repro),
    ]
    return "\n\n".join("\n".join(p) for p in parts) + "\n"


# ── 실행 ────────────────────────────────────────────────────────────────


def _dump_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(
    runs_dir: Path = RUNS_DIR,
    out: Path = REPORT_PATH,
    embedder=None,
    law_path: Path = LAW_PATH,
    n: int = SANITY_N,
) -> int:
    rows, articles = load_law_rows(law_path), load_articles(law_path)
    embedder = embedder or Embedder(settings.openai_embed_model)
    lines = sanity_by_candidate(rows, articles, embedder, n=n)
    golden = golden_misses(runs_dir)
    causes = build_causes(lines, articles, rows, embedder)
    sanity_path = runs_dir / "sanity" / "results.jsonl"
    repro = reproduce([x for x in lines if x["candidate"] == "article"], _read_lines(sanity_path))
    dest = runs_dir / "138"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "sanity.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8"
    )
    _dump_json(dest / "golden_misses.json", golden)
    _dump_json(dest / "causes.json", causes)
    report = build_report(lines, golden, causes, repro)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report.splitlines()[0])
    print(f"OpenAI 호출 {embedder.api_calls}회 → {dest} · {out}")
    bad = {
        "재현(징후 2)": len(repro["diffs"]),
        "숫자 없는 원인 문장(징후 3)": sum(not cites_number(c) for c in causes),
        "낱말 기여 검산 실패(징후 4)": sum(
            g >= SUM_TOLERANCE for c in causes for k, g in c.items() if k.endswith("_terms_gap")
        ),
    }
    for name, count in bad.items():
        if count:
            print(f"실패 징후 {name}: {count}건", file=sys.stderr)
    return 1 if any(bad.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
