"""#79 실패 징후 1~6을 재고 리포트 `docs/79-axis-search.md`·`runs/79/last_run.json`을 쓴다.

    python -m cheongyak_rag.retrieval.axes_report --report

공고 전부를 `axes.plan`·`axes.search`로 돌린다. 구간 이름(통과·다시 잰다·미완)과 경계는
plan §실패 징후의 것이다. 켜진 축 목록은 측정 코드가 SQL로 따로 다시 계산해 견준다
(`independent_on` — `axes.plan`을 부르지 않는다). 메모리 쪽 기준은 `query.Index`다.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag.config import settings
from cheongyak_rag.ingest.notice_report import _bullets, _table
from cheongyak_rag.retrieval import axes, index_db
from cheongyak_rag.retrieval.chunk_eval import RUNS73
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import now, write
from cheongyak_rag.retrieval.query import Index, format_result, selected_candidate

OUT_MD = Path("docs/79-axis-search.md")
OUT_JSON = Path("runs/79/last_run.json")

LAW_K, FAQ_K = 5, 3
SHOW = 10  # 표에 풀어 쓰는 항목 수
EXPECT_PASS, EXPECT_RETRY = 6, 4  # 징후 2 — 기대 조가 든 축 수의 경계
RATIO_PASS, RATIO_RETRY = 0.98, 0.90  # 징후 3
CALLS_PASS, CALLS_RETRY = 50, 150  # 징후 4
MEDIAN_PASS, MEDIAN_RETRY = 2.0, 5.0  # 징후 5 — 초
SHORT_RETRY = 3  # 징후 1 — 적게 돌아온 (공고, 축)이 이 개수까지면 다시 잰다
# 착수 실측(2026-10-29): 공고 84건 중 특별공급 축 둘이 꺼진 공고 · 재당첨제한 축이 꺼진 공고
BASELINE = {"notices": 84, "special_off": 5, "rewin_off": 48}


# ── 구간 ─────────────────────────────────────────────────────────────────


def zone_run(*, errors: int, no_mst: int, list_diff: int, short: int, sample_ok: bool) -> str:
    """징후 1 — 예외·MST·목록이 0이고 표본이 빠짐없으면 적게 돌아온 수로 가른다(0 통과)."""
    if errors or no_mst or list_diff or short > SHORT_RETRY or not sample_ok:
        return "미완"
    return "통과" if short == 0 else "다시 잰다"


def zone_expected(n_axes: int) -> str:
    return "통과" if n_axes >= EXPECT_PASS else "다시 잰다" if n_axes >= EXPECT_RETRY else "미완"


def zone_same(ratio: float) -> str:
    return "통과" if ratio >= RATIO_PASS else "다시 잰다" if ratio >= RATIO_RETRY else "미완"


def zone_calls(n: int) -> str:
    return "통과" if n <= CALLS_PASS else "다시 잰다" if n <= CALLS_RETRY else "미완"


def zone_median(seconds: float) -> str:
    return "통과" if seconds <= MEDIAN_PASS else "다시 잰다" if seconds <= MEDIAN_RETRY else "미완"


def zone_off(got: dict, n_notices: int) -> str:
    """징후 6 — 같으면 통과. 다른데 공고 수도 달라졌으면 데이터가 바뀐 것으로 보고 다시 잰다."""
    if all(got[k] == BASELINE[k] for k in ("special_off", "rewin_off")):
        return "통과"
    return "다시 잰다" if n_notices != BASELINE["notices"] else "미완"


# ── 읽기 ─────────────────────────────────────────────────────────────────

INDEPENDENT_SQL = sa.text(
    "SELECT n.house_manage_no AS h, n.pblanc_no AS p,"
    " coalesce(n.speclt_rdn_earth_at, false) AS f1, coalesce(n.mdat_trget_area_secd, false) AS f2,"
    " coalesce(n.parcprc_uls_at, false) AS f3, coalesce(n.public_house_earth_at, false) AS f4,"
    " (SELECT coalesce(sum(m.spsply_hshldco), 0) FROM notice_models m"
    "   WHERE m.house_manage_no = n.house_manage_no AND m.pblanc_no = n.pblanc_no) AS special,"
    " (SELECT coalesce(sum(nullif(m.raw->>'OLD_PARNTS_SUPORT_HSHLDCO', '')::int), 0)"
    "   FROM notice_models m"
    "   WHERE m.house_manage_no = n.house_manage_no AND m.pblanc_no = n.pblanc_no) AS parents"
    " FROM notices n ORDER BY n.house_manage_no, n.pblanc_no"
)


def independent_on(engine: Engine) -> dict[tuple[str, str], list[str]]:
    """공고 → 켜진 축 id 목록. `axes.plan`을 안 부르고 `notices`·`notice_models`를 직접 읽는다."""
    with engine.connect() as conn:
        rows = conn.execute(INDEPENDENT_SQL).mappings().all()
    out = {}
    for r in rows:
        on = {"homeless", "account", "residence"}
        if r["special"] > 0:
            on |= {"income_asset", "special_type"}
        if r["f1"] or r["f2"] or r["f3"] or r["f4"]:
            on.add("rewin")
        if r["f1"] or r["f2"] or r["parents"] > 0:
            on.add("householder")
        out[(r["h"], r["p"])] = [a.id for a in axes.AXES if a.id in on]
    return out


def _notices(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT house_manage_no, pblanc_no FROM notices ORDER BY 1, 2")
        ).all()
    return [(r[0], r[1]) for r in rows]


def _chunk_ids(chunks) -> list[str]:
    return [c.chunk_id for c in chunks]


def _lines(hit: axes.QueryHits) -> list[str]:
    return format_result({"law": hit.law, "faq": hit.faq}).splitlines()


# ── 측정 ─────────────────────────────────────────────────────────────────


def measure(engine: Engine, embedder, index: Index, *, api_start: int) -> dict:
    """공고 전부를 돌려 징후 1~6의 값을 모은다. 예외는 공고별로 모아 계속 돈다."""
    keys = _notices(engine)
    errors, plans_by, names = [], {}, {}
    for key in keys:  # 1차 — 켜짐 여부·하위 질의만 모은다
        try:
            _, names[key], facts = axes.load_facts(engine, *key)
            plans_by[key] = axes.plan_from_facts(facts)
        except Exception as e:  # noqa: BLE001 — 징후 1이 예외 공고를 세려고 모두 잡는다
            errors.append({"notice": key[0], "stage": "plan", "error": f"{type(e).__name__}: {e}"})
    all_queries = list(dict.fromkeys(q for ps in plans_by.values() for p in ps for q in p.queries))
    try:
        if all_queries:
            embedder.embed(all_queries)  # 캐시에 없는 질의는 여기서 한 번에 보낸다
    except Exception as e:  # noqa: BLE001
        errors.append({"notice": "*", "stage": "embed", "error": f"{type(e).__name__}: {e}"})

    cache: axes.Cache = {}
    t0 = time.perf_counter()
    mst = next((p.law_mst for ps in plans_by.values() for p in ps if p.law_mst), None)
    if mst is not None:
        axes._corpus(engine, "law", mst, cache)
    axes._corpus(engine, "faq", None, cache)
    warmup = time.perf_counter() - t0

    results, timing = {}, {}
    for key in keys:  # 2차 — 공고 하나씩 plan부터 search까지 시간을 잰다
        if key not in plans_by:
            continue
        t0 = time.perf_counter()
        try:
            axes.load_facts(engine, *key)
            t1 = time.perf_counter()
            results[key] = axes.search(
                engine, embedder, *key, k=LAW_K, faq_k=FAQ_K, plans=plans_by[key], cache=cache
            )
            timing[key] = (t1 - t0, time.perf_counter() - t1)
        except Exception as e:  # noqa: BLE001
            errors.append(
                {"notice": key[0], "stage": "search", "error": f"{type(e).__name__}: {e}"}
            )

    sql_on = independent_on(engine)
    list_diff, short, no_mst, kinds = [], [], [], {}
    for key, plans in plans_by.items():
        on = [p.id for p in plans if p.on]
        if on != sql_on.get(key):
            list_diff.append({"notice": key[0], "plan": on, "sql": sql_on.get(key)})
        if plans[0].law_mst is None:
            no_mst.append(key[0])
        kinds.setdefault(tuple(on), key)
        for r in results.get(key, []):
            bad = [h for h in r.hits if len(h.law) < LAW_K or len(h.faq) < FAQ_K]
            if bad:
                h = bad[0]
                if plans[0].law_mst is None:
                    cause = "MST 없음"
                elif len(h.law) >= LAW_K:
                    cause = "FAQ가 faq_k개보다 적게 돌아왔다"
                elif h.law_dense < h.law_pool:
                    cause = "필터 × ANN — dense가 후보를 덜 돌려줬다"
                else:
                    cause = "행이 모자란다"
                short.append(
                    {
                        "notice": key[0],
                        "axis": r.id,
                        "query": h.query,
                        "law": len(h.law),
                        "faq": len(h.faq),
                        "pool": h.law_pool,
                        "dense": h.law_dense,
                        "cause": cause,
                    }
                )

    samples = [
        _sample(key, names[key], list(on), results.get(key, [])) for on, key in kinds.items()
    ]
    axis_rows, mem_diffs, miss = _per_query(results, plans_by, index)
    n_hit = sum(1 for a in axis_rows if a["queries"] and a["hit"] == len(a["queries"]))
    all_q = [q for a in axis_rows for q in a["queries"]]
    n_same = sum(q["same"] for q in all_q)
    ratio = n_same / len(all_q) if all_q else 0.0
    elapsed = [sum(t) for t in timing.values()]
    off = {
        "special_off": sum(
            not any(p.on for p in ps if p.id in ("income_asset", "special_type"))
            for ps in plans_by.values()
        ),
        "rewin_off": sum(not p.on for ps in plans_by.values() for p in ps if p.id == "rewin"),
    }
    # 종류마다 표본이 하나이고, 표본마다 켜진 축 전부의 결과가 실려 있어야 한다
    sample_ok = len(samples) == len(kinds) and all(
        [a["id"] for a in s["axes"]] == s["on"] for s in samples
    )
    msts = sorted({ps[0].law_mst or "없음" for ps in plans_by.values()})
    run = {
        "run_at": now(),
        "notices": len(keys),
        "errors": errors,
        "no_mst": no_mst,
        "msts": msts,
        "list_diff": list_diff,
        "short": short,
        "kinds": len(kinds),
        "samples": samples,
        "axes": axis_rows,
        "expected_axes": n_hit,
        "memory": {
            "same": n_same,
            "n": len(all_q),
            "ratio": ratio,
            "diffs": mem_diffs,
            "zone": zone_same(ratio),
        },
        "miss": miss,
        "api_calls": embedder.api_calls - api_start,
        "time": {
            "median": statistics.median(elapsed) if elapsed else 0.0,
            "max": max(elapsed) if elapsed else 0.0,
            "warmup": warmup,
            "plan_median": statistics.median(t[0] for t in timing.values()) if timing else 0.0,
            "search_median": statistics.median(t[1] for t in timing.values()) if timing else 0.0,
        },
        "off": off,
    }
    run["zones"] = {
        "run": zone_run(
            errors=len(errors),
            no_mst=len(no_mst),
            list_diff=len(list_diff),
            short=len(short),
            sample_ok=sample_ok,
        ),
        "expected": zone_expected(n_hit),
        "memory": run["memory"]["zone"],
        "calls": zone_calls(run["api_calls"]),
        "time": zone_median(run["time"]["median"]),
        "off": zone_off(off, len(keys)),
    }
    return run


def _sample(key, name: str, on: list[str], results: list[axes.AxisResult]) -> dict:
    return {
        "notice": key[0],
        "name": name,
        "on": on,
        "axes": [
            {
                "id": r.id,
                "name": r.name,
                "hits": [{"query": h.query, "lines": _lines(h)} for h in r.hits],
            }
            for r in results
        ],
    }


def _per_query(results: dict, plans_by: dict, index: Index) -> tuple[list[dict], list[dict], list]:
    """하위 질의 문장마다 한 번 — 기대 조가 상위 5개에 드는지, 메모리 검색과 같은지."""
    first: dict[tuple[str, str], axes.QueryHits] = {}
    n_on = {a.id: 0 for a in axes.AXES}
    for rs in results.values():
        for r in rs:
            n_on[r.id] += 1
            for h in r.hits:
                first.setdefault((r.id, h.query), h)
    rows, diffs, miss = [], [], []
    for axis in axes.AXES:
        queries = []
        for (axis_id, query), h in first.items():
            if axis_id != axis.id:
                continue
            labels = [c.label for c in h.law]
            hit = any(x in labels for x in axis.expected)
            mem = index.search(query, LAW_K, faq_k=FAQ_K)
            miss_law = sorted(set(_chunk_ids(mem["law"])) - set(_chunk_ids(h.law)))
            extra_law = sorted(set(_chunk_ids(h.law)) - set(_chunk_ids(mem["law"])))
            miss_faq = sorted(set(_chunk_ids(mem["faq"])) - set(_chunk_ids(h.faq)))
            extra_faq = sorted(set(_chunk_ids(h.faq)) - set(_chunk_ids(mem["faq"])))
            same = not (miss_law or extra_law or miss_faq or extra_faq)
            if not same:
                diffs.append(
                    {
                        "axis": axis.id,
                        "query": query,
                        "missing": miss_law + miss_faq,
                        "extra": extra_law + extra_faq,
                    }
                )
            if not hit:
                miss.append({"axis": axis.id, "query": query, "labels": labels})
            queries.append({"query": query, "hit": hit, "same": same, "labels": labels})
        rows.append(
            {
                "id": axis.id,
                "name": axis.name,
                "n_on": n_on[axis.id],
                "expected": expected_text(axis),
                "queries": queries,
                "hit": sum(q["hit"] for q in queries),
            }
        )
    return rows, diffs, miss


def expected_text(axis: axes.AxisDef) -> str:
    if axis.id == "special_type":
        return "제35조~제47조(의N 포함) 중 하나"
    return " · ".join(axis.expected)


# ── 리포트 ───────────────────────────────────────────────────────────────


def summary_line(run: dict) -> str:
    return (
        f"공고 {run['notices']}건 중 예외 {len(run['errors'])}건,"
        f" 켜진 축 목록이 다시 계산한 것과 다른 공고 {len(run['list_diff'])}건,"
        f" 적게 돌아온 축 {len(run['short'])}개이고,"
        f" 기대 조가 든 축은 {len(axes.AXES)}개 중 {run['expected_axes']}개다."
    )


def _prev_table(run: dict, prev: dict | None) -> list[str]:
    """직전 실행과 하위 질의 문장이 달라진 축의 고치기 전·후 값."""
    if not prev:
        return ["- 직전 실행 기록이 없다(첫 실행)"]
    before = {a["id"]: a for a in prev.get("axes", [])}
    rows = []
    for a in run["axes"]:
        b = before.get(a["id"])
        if b is None or [q["query"] for q in b["queries"]] == [q["query"] for q in a["queries"]]:
            continue
        rows.append(
            (
                a["name"],
                " / ".join(q["query"] for q in b["queries"]),
                f"{b['hit']}/{len(b['queries'])}",
                " / ".join(q["query"] for q in a["queries"]),
                f"{a['hit']}/{len(a['queries'])}",
            )
        )
    if not rows:
        return [f"- 직전 실행({prev.get('run_at', '?')})과 문장이 바뀐 축이 없다"]
    return [
        f"직전 실행({prev.get('run_at', '?')})과 문장이 바뀐 축. 값은 (든 하위 질의 / 하위 질의)다",
        "",
        *_table(["축", "고치기 전 문장", "전 값", "고친 뒤 문장", "후 값"], rows),
    ]


def render(run: dict, prev: dict | None = None) -> str:
    z, t, m, off = run["zones"], run["time"], run["memory"], run["off"]
    shorts = run["short"]
    lines = [
        summary_line(run),
        "",
        "# #79 공고별 요건 7축 검색 결과",
        "",
        f"실행 {run['run_at']} · 공고 {run['notices']}건 · 켜진 축 목록 종류 {run['kinds']}가지",
        "",
        "## 1. 실패 징후 측정값",
        "",
    ]
    lines += _table(
        ["지표", "측정값", "구간"],
        [
            (
                "1. 7축 검색이 끝까지 동작하고 켜진 축 목록과 축마다 top-k가 나온다 (jw 기준)",
                f"예외 {len(run['errors'])}건 · MST 못 정한 공고 {len(run['no_mst'])}건"
                f" · 목록이 다시 계산한 것과 다른 공고 {len(run['list_diff'])}건"
                f" · 적게 돌아온 (공고, 축) {len(shorts)}개"
                f" · 표본 {len(run['samples'])}건 ↔ 목록 종류 {run['kinds']}가지",
                z["run"],
            ),
            (
                "2. 축마다 기대 조가 조문 상위 5개 안에 든다",
                f"든 축 {run['expected_axes']}/{len(axes.AXES)} ("
                + " · ".join(f"{a['id']} {a['hit']}/{len(a['queries'])}" for a in run["axes"])
                + ")",
                z["expected"],
            ),
            (
                "3. DB 경로 상위 k가 메모리 검색(`query.Index`)과 같다",
                f"하위 질의 {m['same']}/{m['n']} ({m['ratio']:.1%}) 같음",
                z["memory"],
            ),
            ("4. 임베딩 API 호출 수", f"{run['api_calls']}회", z["calls"]),
            (
                "5. 공고 하나 처리 시간 (캐시가 찬 상태)",
                f"중앙값 {t['median']:.3f}초 · 최댓값 {t['max']:.3f}초"
                f" (plan 중앙값 {t['plan_median']:.3f}초"
                f" · search 중앙값 {t['search_median']:.3f}초)",
                z["time"],
            ),
            (
                "6. 꺼진 축 수가 착수 실측과 같다",
                f"특별공급 축 둘이 꺼진 공고 {off['special_off']}건(착수 실측"
                f" {BASELINE['special_off']}) · 재당첨제한 축이 꺼진 공고"
                f" {off['rewin_off']}건(착수 실측 {BASELINE['rewin_off']})"
                f" · 공고 {run['notices']}건(착수 실측 {BASELINE['notices']})",
                z["off"],
            ),
        ],
    )
    lines += ["", "구간 기준과 경계는 plan §실패 징후와 같다.", ""]
    lines += ["### 읽는 법", ""]
    lines += _bullets(
        [
            "1번 켜진 축 목록 대조: `axes.plan`의 켜짐 여부와, 이 측정 코드가 `notices`·"
            "`notice_models`를 SQL로 직접 읽어 따로 계산한 켜짐 여부를 비교했다."
            " 두 쪽을 같은 사람이 같은 설계에서 옮겨 적었으므로 같이 틀릴 수 있다",
            "2번 기대 조는 main 세션이 구현 전에 조 제목만 보고 정했다. 정답 대조가 아니라"
            " 「이 질의가 그럴듯한 조를 찾는가」를 보는 확인이다. 축 하나의 하위 질의가 여럿이면"
            " 전부에서 들어야 「든 축」으로 센다",
            "3번은 DB 경로(dense=`nearest`, BM25=앱, 합치기=`rrf`)와 메모리 경로"
            f"(`query.Index`)가 같은 하위 질의에서 조문 상위 {LAW_K}개·FAQ 상위 {FAQ_K}개 집합이"
            " 같은지다. 순서는 보지 않는다",
            f"공고가 가리킨 법령 버전(MST)은 {', '.join(run['msts'])}이다. 3번의 메모리 `Index`는"
            " 법령 파일 하나(시행 2026-06-15)로 만들어서, 버전이 둘 이상이면 다른 버전 공고는"
            " 견주지 못한다",
            "2번 `special_type`의 기대 조는 제35조~제47조 16개라 특별공급 질의가 들기 쉽다."
            " 8/9는 검색 품질의 증거가 아니라 질의가 특별공급 조로 간다는 확인이다",
            f"5번 시간은 공고마다 `load_facts`부터 `search`까지다. BM25 색인은 (source, MST)마다"
            f" 처음 한 번 만들고 그 시간({t['warmup']:.3f}초)은 공고별 시간에서 뺐다."
            " 하위 질의 임베딩은 시간 재기 전에 한 번에 보냈다",
        ]
    )
    lines += ["", "## 2. 축 7개", ""]
    lines += _table(
        ["축", "켜는 조건", "켜진 공고 수", "하위 질의 문장", "기대 조", "기대 조 든 질의"],
        [
            (
                f"{a['name']} (`{a['id']}`)",
                axes.AXIS_BY_ID[a["id"]].condition,
                f"{a['n_on']}/{run['notices']}",
                "<br>".join(q["query"] for q in a["queries"]) or "—",
                a["expected"],
                f"{a['hit']}/{len(a['queries'])}",
            )
            for a in run["axes"]
        ],
    )
    lines += ["", "### 하위 질의 문장을 고친 기록", ""]
    lines += _prev_table(run, prev)
    lines += ["", "## 3. 표본 — 켜진 축 목록 종류마다 공고 하나", ""]
    lines += [
        f"켜진 축 목록이 서로 다른 공고가 {run['kinds']}종이다."
        " 종류마다 처음 나온 공고를 하나씩 골라"
        f" 축마다 조문 상위 {LAW_K}개·FAQ 상위 {FAQ_K}개 전체를 싣는다.",
        "",
    ]
    for s in run["samples"]:
        lines += [
            f"### {s['name']} (`{s['notice']}`)",
            "",
            "켜진 축: " + " · ".join(axes.AXIS_BY_ID[x].name for x in s["on"]),
            "",
        ]
        for a in s["axes"]:
            lines += [f"#### {a['name']}", ""]
            for h in a["hits"]:
                lines += [f"- 질의: {h['query']}"]
                lines += [f"  - {x}" for x in h["lines"]]
            lines.append("")
    lines += ["## 4. 어긋난 곳", ""]
    lines += ["### 켜진 축 목록이 다시 계산한 것과 다른 공고", ""]
    lines += _bullets(
        [f"{d['notice']}: plan {d['plan']} ↔ SQL {d['sql']}" for d in run["list_diff"][:SHOW]]
    )
    lines += ["", f"### 조문 {LAW_K}개·FAQ {FAQ_K}개보다 적게 돌아온 (공고, 축)", ""]
    lines += _bullets(
        [
            f"{x['notice']} · {x['axis']}: 조문 {x['law']}개 · FAQ {x['faq']}개"
            f" (후보 행 {x['pool']} · dense {x['dense']}) — {x['cause']}"
            for x in shorts[:SHOW]
        ]
    )
    lines += ["", "### 예외·MST 못 정한 공고", ""]
    lines += _bullets(
        [f"{e['notice']} ({e['stage']}): {e['error']}" for e in run["errors"][:SHOW]]
        + [f"MST 못 정함: {n}" for n in run["no_mst"][:SHOW]]
    )
    lines += ["", "### 기대 조가 상위 5개에 안 든 하위 질의", ""]
    lines += _bullets(
        [
            f"`{x['axis']}` · {x['query']} → 상위 5개 {', '.join(x['labels']) or '없음'}"
            for x in run["miss"]
        ]
    )
    lines += ["", f"### 메모리 검색과 집합이 다른 하위 질의 ({len(m['diffs'])}건)", ""]
    lines += _bullets(
        [
            f"`{x['axis']}` · {x['query']} → DB에 없는 청크 {x['missing']}"
            f" · 메모리에 없는 청크 {x['extra']}"
            for x in m["diffs"][:SHOW]
        ]
    )
    lines += ["", "## 5. 열린 질문에서 고른 것 (설계 §2·§7)", ""]
    lines += _bullets(OPEN_QUESTIONS + [f"임베딩 API 호출 {run['api_calls']}회"])
    return "\n".join(lines) + "\n"


# 켜는 조건을 쓰기 전에 법령 본문(`data/processed/law-008243-20260615.jsonl`)을 읽고 확인한 것
OPEN_QUESTIONS = [
    "`householder`(세대주 여부)의 켜는 조건을 설계 §2의 「항상」에서 바꿨다."
    " 제28조제1항제1호다목은 「세대주일 것」을 투기과열지구·청약과열지역에서만 요건으로 건다"
    "(가목 수도권·나목 수도권 외·라목 위축지역에는 없다). 제27조도 같다."
    " 특별공급에서 세대주를 한정하는 곳은 제46조(노부모 부양 — 무주택세대구성원은 세대주에 한정)다."
    " 그래서 투기과열지구·청약과열지역 표시가 하나라도 참이거나 노부모 부양 특별공급 세대수가"
    " 0보다 크면 켠다. 제43조(생애최초)의 「세대주」는 면적 구분에 쓰이는 낱말이라"
    " 조건에 넣지 않았다",
    "`rewin`(재당첨제한)의 켜는 조건은 설계 그대로 두었다."
    " 제54조제1항은 분양가상한제 적용주택(3호)·"
    "투기과열지구(6호)·청약과열지역(7호) 공급 주택에 당첨된 세대를 제한한다."
    " 본문에 「공공택지」라는 낱말은 없어서 이 표시를 켜는 조건에 넣은 근거는 확인하지 못했다"
    "(공공택지 표시가 참이면 분양가상한제 적용 대상인 경우가 많을 것으로 본다 — 추정)."
    " 제54조는 분양전환공공임대(4호)·토지임대주택(5호)·이전기관 특별공급(2호)에도 걸리는데,"
    " 이는 공고의 규제 표시 칸으로는 알 수 없어서 켜는 조건에 넣지 않았다."
    " 그래서 이 축이 꺼진 공고도 이 조가 적용될 수 있다",
    "`residence`는 설계대로 항상 켠다. 제4조는 주택건설지역 거주 요건(제1항)과 거주기간 우선공급"
    "(제5항)을 정하고 투기과열지구 여부에 따라 달라지지만, 공고마다 달라지는 것은 하위 질의에"
    " 끼우는 공급지역명뿐이다",
    "`special_type`은 특별공급 세대수 합이 0보다 큰데 유형별 세대수가 전부 0이면 유형을 모르므로"
    " 유형 이름 없는 문장 하나로 검색한다",
]


def dump(run: dict) -> str:
    return json.dumps(run, ensure_ascii=False, indent=2) + "\n"


# ── 실행 ─────────────────────────────────────────────────────────────────


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    embedder=None,
    index: Index | None = None,
    runs_dir: Path = RUNS73,
    out_md: Path = OUT_MD,
    out_json: Path = OUT_JSON,
    law_rows=None,
    faq_rows=None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.retrieval.axes_report")
    ap.add_argument(
        "--report", action="store_true", required=True, help="공고 전부를 돌려 징후 1~6을 잰다"
    )
    ap.parse_args(argv)
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        if not index_db._table_ready(engine):
            print("chunks 테이블이 없다. 먼저 uv run alembic upgrade head", file=sys.stderr)
            return 2
        embedder = embedder or Embedder(settings.openai_embed_model)
        api_start = embedder.api_calls
        index = index or Index(
            selected_candidate(runs_dir), embedder, law_rows=law_rows, faq_rows=faq_rows
        )
        prev = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else None
        run = measure(engine, embedder, index, api_start=api_start)
        write(out_md, render(run, prev))
        write(out_json, dump(run))
        print(summary_line(run))
        print("구간: " + " · ".join(f"{k} {v}" for k, v in run["zones"].items()))
        print(f"→ {out_md} · {out_json}")
        return 1 if run["zones"]["run"] == "미완" else 0
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 3  # 1은 징후 1 미완, 2는 DB 오류
    except SQLAlchemyError as e:
        print(f"DB 오류: {type(e).__name__}: {getattr(e, 'orig', e)}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
