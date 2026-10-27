"""#74 실패 징후 1~6을 재고 리포트 `docs/74-pg-index.md`·`runs/74/last_run.json`을 쓴다.

측정은 전부 실제 DB에 적재한 뒤 한다. 구간 이름(통과·다시 잰다·미완)과 경계는
plan §실패 징후의 것이다.
메모리 쪽 기준은 `query.Index`(전수 계산)이고 DB 쪽은 `index_db.nearest`(HNSW)다.
"""

import json
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.ingest.notice_report import _bullets, _table
from cheongyak_rag.retrieval import index_db
from cheongyak_rag.retrieval.embed import text_key
from cheongyak_rag.retrieval.search import dense_rank

LAW_K, FAQ_K = 5, 3
VEC_TOL = 1e-6  # float4 저장 vs float64 캐시
PASS_RATIO, RETRY_RATIO = 0.98, 0.90
EF_RETRY = 100
INDEX_NAMES = ("chunks_embedding_law_hnsw", "chunks_embedding_faq_hnsw", "chunks_tokens_gin")
SHOW = 10  # 표에 풀어 쓰는 항목 수


# ── 구간 ─────────────────────────────────────────────────────────────────


def zone_count(n: int, *, retry_max: int) -> str:
    """0 통과 · 1~retry_max 다시 잰다 · 그 이상 미완. 실패 징후 3·4·6이 쓴다."""
    return "통과" if n == 0 else "다시 잰다" if n <= retry_max else "미완"


def zone_topk(ratio: float) -> str:
    return "통과" if ratio >= PASS_RATIO else "다시 잰다" if ratio >= RETRY_RATIO else "미완"


def zone_load(
    *, rows, expected, missing, extra, text_diff, vec_diff, no_index: list[str], uses_index: bool
) -> str:
    if rows != expected or missing or extra or text_diff or vec_diff or no_index:
        return "미완"
    return "통과" if uses_index else "다시 잰다"


# ── 읽기 ─────────────────────────────────────────────────────────────────


def snapshot(engine: Engine) -> dict[str, tuple[str, str]]:
    """chunk_id → (text, embedding 원문). 재실행 때 바뀐 것이 있는지 본다."""
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT chunk_id, text, embedding::text FROM chunks")).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _vec(text: str) -> np.ndarray:
    return np.array([float(x) for x in text.strip("[]").split(",")])


def measure_load(engine, embedder, chunks, probe_vec) -> dict:
    """실패 징후 1 — 메모리 계산이 쓰는 청크와 DB를 대조하고 인덱스·EXPLAIN을 본다."""
    db = snapshot(engine)
    want = {c.chunk_id: c.text for c in chunks}
    missing = sorted(want.keys() - db.keys())
    extra = sorted(db.keys() - want.keys())
    both = sorted(want.keys() & db.keys())
    text_diff = [i for i in both if db[i][0] != want[i]]
    vec_diff = [
        i
        for i in both
        if np.abs(_vec(db[i][1]) - np.array(embedder.cache[text_key(want[i])])).max() > VEC_TOL
    ]
    with engine.connect() as conn:
        indexes = sorted(
            conn.execute(
                sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
            ).scalars()
        )
    explain, uses = {}, {}
    for source, k, name in (
        ("law", LAW_K, INDEX_NAMES[0]),
        ("faq", FAQ_K, INDEX_NAMES[1]),
    ):
        default = index_db.explain(engine, probe_vec, source, k)
        forced = index_db.explain(engine, probe_vec, source, k, seqscan_off=True)
        explain[source] = {"default": default, "seqscan_off": forced}
        uses[source] = name in forced
    no_index = [n for n in INDEX_NAMES if n not in indexes]
    zone = zone_load(
        rows=len(db),
        expected=len(want),
        missing=len(missing),
        extra=len(extra),
        text_diff=len(text_diff),
        vec_diff=len(vec_diff),
        no_index=no_index,
        uses_index=all(uses.values()),
    )
    return {
        "rows": len(db),
        "expected": len(want),
        "missing": missing,
        "extra": extra,
        "text_diff": len(text_diff),
        "text_diff_ids": text_diff[:SHOW],
        "vec_diff": len(vec_diff),
        "vec_diff_ids": vec_diff[:SHOW],
        "indexes": indexes,
        "no_index": no_index,
        "explain": explain,
        "uses_index": uses,
        "zone": zone,
    }


def _topk_one(engine, index, golden, qvecs, ef_search) -> tuple[dict, list[dict], dict]:
    """질문마다 DB top-k와 메모리 top-k를 비교한다 → (일치 비율, 다른 문항, k개 미만 문항)."""
    out = {}
    diffs: list[dict] = []
    short: dict[str, list[str]] = {"law": [], "faq": []}
    for source, k, ids, vecs in (
        ("law", LAW_K, [c.chunk_id for c in index.law], index.law_vecs),
        ("faq", FAQ_K, [c.chunk_id for c in index.faq], index.faq_vecs),
    ):
        same = 0
        for g, qv in zip(golden, qvecs, strict=True):
            mem = dense_rank(qv, vecs, ids)[:k]
            got = [
                cid
                for cid, _ in index_db.nearest(engine, qv, source, k, ef_search=ef_search,
                                               force_index=True)
            ]  # fmt: skip
            if len(got) < k:
                short[source].append(g["qid"])
            if set(got) == set(mem):
                same += 1
            else:
                diffs.append(
                    {
                        "qid": g["qid"],
                        "question": g["question"],
                        "source": source,
                        "missing": sorted(set(mem) - set(got)),
                        "extra": sorted(set(got) - set(mem)),
                    }
                )
        out[source] = {"same": same, "n": len(golden), "ratio": same / len(golden)}
    return out, diffs, short


def measure_topk(engine, index, golden, qvecs) -> dict:
    """실패 징후 2·3 — 같은 문항·k로 HNSW top-k 일치와 k개 미만 문항을 센다."""
    base, diffs, short = _topk_one(engine, index, golden, qvecs, None)
    worst = min(v["ratio"] for v in base.values())
    result = {"default": base, "diffs": diffs, "zone": zone_topk(worst), "ef100": None}
    if RETRY_RATIO <= worst < PASS_RATIO:
        again, diffs100, _ = _topk_one(engine, index, golden, qvecs, EF_RETRY)
        result["ef100"] = again
        result["diffs_ef100"] = diffs100
        result["zone_ef100"] = zone_topk(min(v["ratio"] for v in again.values()))
    qids = sorted(set(short["law"]) | set(short["faq"]))
    count = len(qids)
    return result, {
        "count": count,
        "law": len(short["law"]),
        "faq": len(short["faq"]),
        "qids": qids[:SHOW],
        "zone": zone_count(count, retry_max=3),
    }


def measure_cache(rows, cache_before, golden, api_calls) -> dict:
    """실패 징후 4 — 이번 실행 전 캐시에 없던 청크 텍스트."""
    missing = [r["chunk_id"] for r in rows if r["text_sha256"] not in cache_before]
    questions = {g["question"] for g in golden}
    return {
        "missing_chunks": len(missing),
        "missing_ids": missing[:SHOW],
        "golden_misses": sum(text_key(q) not in cache_before for q in questions),
        "api_calls": api_calls,
        "zone": zone_count(len(missing), retry_max=5),
    }


def measure_rerun(before: dict, after: dict) -> dict:
    """실패 징후 5 — 두 번 적재한 뒤 행 수·chunk_id 집합·벡터가 같은가."""
    ids_changed = sorted(before.keys() ^ after.keys())
    content_changed = sorted(i for i in before.keys() & after.keys() if before[i] != after[i])
    changed = len(ids_changed) + len(content_changed)
    return {
        "rows_before": len(before),
        "rows_after": len(after),
        "ids_changed": ids_changed[:SHOW],
        "content_changed": len(content_changed),
        "changed": changed,
        "zone": "통과" if changed == 0 else "미완",
    }


def measure_tokens(engine) -> dict:
    """실패 징후 6 — 빈 `tokens` 행."""
    with engine.connect() as conn:
        ids = list(
            conn.execute(
                sa.text("SELECT chunk_id FROM chunks WHERE tokens = '' ORDER BY chunk_id")
            ).scalars()
        )
    return {"empty": len(ids), "ids": ids[:SHOW], "zone": zone_count(len(ids), retry_max=3)}


def versions(engine) -> dict:
    with engine.connect() as conn:
        pgvector = conn.execute(
            sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    return {"pgvector": pgvector, "kiwipiepy": version("kiwipiepy")}


# ── 리포트 ───────────────────────────────────────────────────────────────


def _pct(r: dict) -> str:
    return f"{r['ratio']:.1%} ({r['same']}/{r['n']})"


def summary_line(run: dict) -> str:
    load, topk, cache = run["load"], run["topk"]["default"], run["cache"]
    return (
        f"{load['rows']}행을 적재했고, 벡터가 캐시와 다른 행은 {load['vec_diff']}개,"
        f" 설계한 인덱스는 {len(INDEX_NAMES) - len(load['no_index'])}개가 있고,"
        f" HNSW top-k가 전수 계산과 같은 문항은 조문 {topk['law']['ratio']:.1%}"
        f"·FAQ {topk['faq']['ratio']:.1%}, 캐시에 없던 청크는 {cache['missing_chunks']}개다."
    )


def render(run: dict) -> str:
    load, topk, short = run["load"], run["topk"], run["short"]
    cache, rerun, tokens, ver = run["cache"], run["rerun"], run["tokens"], run["versions"]
    d = topk["default"]
    lines = [
        summary_line(run),
        "",
        "# #74 검색 색인 적재 결과",
        "",
        f"실행 {run['run_at']} · 청킹 후보 `{run['candidate']}`"
        f" · 임베딩 모델 `{run['embed_model']}`",
        "",
        "## 1. 실패 징후 측정값",
        "",
    ]
    ef = topk["ef100"]
    topk_text = f"조문 {_pct(d['law'])} · FAQ {_pct(d['faq'])}"
    if ef:
        topk_text += (
            f" → `hnsw.ef_search = {EF_RETRY}`로 다시 재면 조문 {_pct(ef['law'])}"
            f" · FAQ {_pct(ef['faq'])} ({topk['zone_ef100']})"
        )
    lines += _table(
        ["지표", "측정값", "구간"],
        [
            (
                "1. 적재와 인덱스 (jw 기준)",
                f"행 {load['rows']}/{load['expected']} · 집합 차이 빠짐 {len(load['missing'])}"
                f"·남음 {len(load['extra'])} · `text` 다른 행 {load['text_diff']}"
                f" · 벡터 다른 행 {load['vec_diff']} · 인덱스 {', '.join(load['indexes'])}"
                f" · `enable_seqscan=off`에서 부분 인덱스를 탄 쪽: "
                + ", ".join(
                    f"{s} {'예' if u else '아니오'}" for s, u in load["uses_index"].items()
                ),
                load["zone"],
            ),
            ("2. HNSW top-k = 전수 top-k인 문항 비율", topk_text, topk["zone"]),
            (
                "3. k개보다 적게 돌아온 문항 수",
                f"{short['count']}문항 (조문 {short['law']} · FAQ {short['faq']})",
                short["zone"],
            ),
            (
                "4. 캐시에 없던 청크 텍스트",
                f"{cache['missing_chunks']}개 (골든 질문 캐시 미스 {cache['golden_misses']}개"
                f" · 임베딩 API 호출 {cache['api_calls']}회는 판정에 안 쓴다)",
                cache["zone"],
            ),
            (
                "5. 재실행",
                f"행 {rerun['rows_before']}→{rerun['rows_after']} · 바뀐 chunk_id"
                f" {len(rerun['ids_changed'])}개 · 내용이 바뀐 행 {rerun['content_changed']}개",
                rerun["zone"],
            ),
            ("6. 빈 `tokens` 행", f"{tokens['empty']}개", tokens["zone"]),
        ],
    )
    lines += ["", "구간 기준과 경계는 plan §실패 징후와 같다.", ""]
    lines += ["## 2. 어긋난 곳", ""]
    problems = []
    if load["missing"] or load["extra"]:
        problems.append(
            f"DB에 없는 청크 {load['missing'][:SHOW]} · DB에만 있는 청크 {load['extra'][:SHOW]}"
        )
    if load["text_diff"]:
        problems.append(f"`text`가 다른 행 {load['text_diff_ids']}")
    if load["vec_diff"]:
        problems.append(f"벡터가 다른 행 {load['vec_diff_ids']}")
    if cache["missing_chunks"]:
        problems.append(f"캐시에 없던 청크 {cache['missing_ids']}")
    if short["count"]:
        problems.append(f"k개보다 적게 돌아온 문항 {short['qids']}")
    if tokens["empty"]:
        problems.append(f"빈 `tokens` 행 {tokens['ids']}")
    if rerun["changed"]:
        problems.append(f"재실행에서 바뀐 chunk_id {rerun['ids_changed']}")
    lines += _bullets(problems)
    diffs = topk["diffs"]
    lines += ["", f"### HNSW top-k가 전수 계산과 다른 문항 ({len(diffs)}건)", ""]
    if diffs:
        lines += _table(
            ["문항", "질문", "대상", "빠진 청크", "대신 들어온 청크"],
            [
                (
                    x["qid"],
                    x["question"][:40],
                    x["source"],
                    ", ".join(x["missing"]),
                    ", ".join(x["extra"]),
                )  # fmt: skip
                for x in diffs
            ],
        )
    else:
        lines.append("- 없다")
    lines += ["", "## 3. EXPLAIN 원문", ""]
    lines.append(
        "568행이면 planner가 인덱스 대신 전수 스캔을 고를 수 있다. 위 표의 top-k는"
        " `enable_seqscan=off`에서 쟀다(`nearest(force_index=True)`)."
    )
    for source in ("law", "faq"):
        for label, key in (("기본 설정", "default"), ("enable_seqscan=off", "seqscan_off")):
            lines += ["", f"### {source} · {label}", "", "```", load["explain"][source][key], "```"]
    lines += ["", "## 4. 열린 질문에서 고른 값 (설계 §5)", ""]
    lines += _bullets(
        [
            "HNSW `m`·`ef_construction`: pgvector 기본값(16·64) 그대로."
            f" `ef_search`는 기본 40이고 {'올려서 다시 쟀다' if ef else '올리지 않았다'}",
            f"`law_mst`: {run['law_mst'] or '없음(null)'}"
            f" — `law_versions`에서 시행일 {index_db.LAW_EFFECTIVE} 행의 MST",
            f"pgvector {ver['pgvector']} · kiwipiepy {ver['kiwipiepy']}"
            " — `tokens`를 다시 만들어야 하는지 볼 때 쓰는 버전",
            f"임베딩 API 호출 {cache['api_calls']}회",
        ]
    )
    return "\n".join(lines) + "\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dump(run: dict) -> str:
    return json.dumps(run, ensure_ascii=False, indent=2) + "\n"
