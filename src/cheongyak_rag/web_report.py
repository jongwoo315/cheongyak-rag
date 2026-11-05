"""#84 화면 측정 도우미. 브라우저 쪽 측정은 `web/e2e/measure.spec.ts`가 한다.

순서: ① `before` — 실제 DB와 이전 측정 파일에서 기대값을 만들어 `runs/84/expected.json`에 쓴다.
② `cd web && npx playwright test e2e/measure.spec.ts` — 화면에서 읽은 값을
`runs/84/raw.json`에 쓴다.
③ `after` — 캐시 줄 수·`traces` 행 수를 다시 세고 징후 1~3을 계산해 `runs/84/last_run.json`과
`docs/84-web.md`를 쓴다.

python -m cheongyak_rag.web_report before|after
"""

import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings

REPO = Path(__file__).resolve().parents[2]
RUN_DIR = REPO / "runs" / "84"
REPORT = REPO / "docs" / "84-web.md"
VERDICT_CACHE = REPO / "data" / "cache" / "verdict-gpt-5.4-mini.jsonl"
EMBED_CACHE = REPO / "data" / "cache" / "embed-text-embedding-3-small.jsonl"
NO_VERDICT = "판정 없음"  # 화면이 null 판정에 쓰는 글자
PROFILES = ("empty", "partial", "full")


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def snapshot(engine: Engine, repo: Path = REPO) -> dict:
    """기대값(실제 DB · 이전 측정 파일)과 측정 전 값(캐시 줄 수 · `traces` 마지막 id)."""
    with engine.connect() as conn:
        notices = [
            {"house_manage_no": r[0], "house_nm": r[1], "n_models": r[2]}
            for r in conn.execute(
                sa.text(
                    "SELECT n.house_manage_no, n.house_nm,"
                    " (SELECT count(*) FROM notice_models m"
                    "  WHERE m.house_manage_no = n.house_manage_no AND m.pblanc_no = n.pblanc_no)"
                    " FROM notices n ORDER BY n.house_manage_no, n.pblanc_no"
                )
            )
        ]
        max_id = conn.execute(sa.text("SELECT coalesce(max(id), 0) FROM traces")).scalar_one()
    run79 = json.loads((repo / "runs/79/last_run.json").read_text(encoding="utf-8"))
    run81 = json.loads((repo / "runs/81/last_run.json").read_text(encoding="utf-8"))
    chosen = [s["notice"] for s in run79["samples"]]
    cells = {(c["notice"], c["profile"]): c["answer"] for c in run81["cells"]}
    pairs = []
    for hmn in chosen:
        for name in PROFILES:
            a = cells[(hmn, name)]
            pairs.append(
                {
                    "notice": hmn,
                    "profile": name,
                    "profile_json": json.loads(
                        (repo / f"runs/80/profiles/{name}.json").read_text(encoding="utf-8")
                    ),
                    "expected": {
                        "verdict": a["verdict"],
                        "routes": sorted(
                            [r["key"], r["verdict"]] for r in [a["general"], *a["special"]]
                        ),
                        "n_checklist": len(a["checklist"]),
                    },
                }
            )
    return {
        "taken_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notices": notices,
        "pairs": pairs,
        "before": {
            "max_trace_id": max_id,
            "verdict_cache_lines": line_count(VERDICT_CACHE),
            "embed_cache_lines": line_count(EMBED_CACHE),
        },
    }


def count_after(engine: Engine, max_id: int) -> dict:
    with engine.connect() as conn:
        n = conn.execute(sa.text("SELECT count(*) FROM traces WHERE id > :i"), {"i": max_id})
        new_traces = n.scalar_one()
        rows = conn.execute(
            sa.text("SELECT house_manage_no, status FROM traces WHERE id > :i ORDER BY id"),
            {"i": max_id},
        ).all()
    return {
        "new_traces": new_traces,
        "new_trace_rows": [[r[0], r[1]] for r in rows],
        "verdict_cache_lines": line_count(VERDICT_CACHE),
        "embed_cache_lines": line_count(EMBED_CACHE),
    }


def _screen_verdict(v: str | None) -> str | None:
    return None if v in (None, NO_VERDICT) else v


def _screen_routes(routes: list) -> list:
    return sorted([k, _screen_verdict(v)] for k, v in routes)


def _same(expected: dict, screen: dict) -> bool:
    return (
        _screen_verdict(screen["verdict"]) == expected["verdict"]
        and _screen_routes(screen["routes"]) == expected["routes"]
        and screen["n_checklist"] == expected["n_checklist"]
    )


def judge(exp: dict, raw: dict, after: dict) -> dict:
    """징후 1~3의 값과 구간. 계산만 하고 파일을 읽지 않는다."""
    by_hmn = {n["house_manage_no"]: n for n in exp["notices"]}
    failed = []
    for p in raw["pages"]:
        n = by_hmn[p["house_manage_no"]]
        why = []
        if p["status"] != 200:
            why.append(f"HTTP {p['status']}")
        if n["house_nm"] not in (p.get("title") or ""):
            why.append(f"title에 공고 이름 없음: {p.get('title')!r}")
        if p.get("rows") != n["n_models"]:
            why.append(f"주택형 표 행 {p.get('rows')} ≠ DB {n['n_models']}")
        if why:
            failed.append({"house_manage_no": p["house_manage_no"], "why": why})
    # 측정이 중간에 끊겨 페이지가 덜 들어와도 F 0이 통과로 읽히지 않게 한다
    pages_missing = sorted(set(by_hmn) - {p["house_manage_no"] for p in raw["pages"]})
    s1 = {
        "F": len(failed),
        "pages_missing": pages_missing,
        "L": raw["links"],
        "n_pages": len(raw["pages"]),
        "failed": failed,
        "band": "통과"
        if not failed and not pages_missing and raw["links"] == len(exp["notices"])
        else "미완",
    }

    g1, still, diff, secs = [], [], [], []
    retries = 0
    for pr in raw["pairs"]:
        attempts = pr["attempts"]
        retries += len(attempts) - 1
        key = f"{pr['notice']}×{pr['profile']}"
        if not attempts[0]["shown"]:
            g1.append(key)
        final = attempts[-1]
        if not final["shown"]:
            still.append(key)
            continue
        secs.append(final["seconds"])
        want = next(
            p["expected"]
            for p in exp["pairs"]
            if p["notice"] == pr["notice"] and p["profile"] == pr["profile"]
        )
        if not _same(want, final["screen"]):
            diff.append({"pair": key, "screen": final["screen"], "expected": want})
    done = {(pr["notice"], pr["profile"]) for pr in raw["pairs"]}
    pairs_missing = [
        f"{p['notice']}×{p['profile']}"
        for p in exp["pairs"]
        if (p["notice"], p["profile"]) not in done
    ]
    if diff or still or pairs_missing:
        band2 = "미완"
    elif g1:
        band2 = "다시 잰다"
    else:
        band2 = "통과"
    s2 = {
        "G1": len(g1),
        "G1_pairs": g1,
        "G1_after_retry": len(still),
        "G2": len(diff),
        "diff": diff,
        "pairs_missing": pairs_missing,
        "n_pairs": len(raw["pairs"]),
        "retries": retries,
        "seconds_median": statistics.median(secs) if secs else None,
        "seconds_max": max(secs) if secs else None,
        "band": band2,
    }

    b = exp["before"]
    h_verdict = after["verdict_cache_lines"] - b["verdict_cache_lines"]
    h_embed = after["embed_cache_lines"] - b["embed_cache_lines"]
    expected_traces = len(raw["pairs"]) + retries
    s3 = {
        "H": h_verdict + h_embed,
        "H_verdict": h_verdict,
        "H_embed": h_embed,
        "T": after["new_traces"],
        "T_expected": expected_traces,
        "statuses": {
            s: sum(1 for r in after["new_trace_rows"] if r[1] == s)
            for s in sorted({r[1] for r in after["new_trace_rows"]})
        },
        "band": "통과"
        if h_verdict + h_embed == 0 and after["new_traces"] == expected_traces
        else "미완",
    }
    return {"s1": s1, "s2": s2, "s3": s3}


def render(exp: dict, res: dict) -> str:
    s1, s2, s3 = res["s1"], res["s2"], res["s3"]
    med = f"{s2['seconds_median']:.1f}초" if s2["seconds_median"] is not None else "-"
    mx = f"{s2['seconds_max']:.1f}초" if s2["seconds_max"] is not None else "-"
    out = [
        "# #84 화면 — 측정 리포트",
        "",
        f"- 징후 1: 공고 페이지 {s1['n_pages']}개 중 실패 F {s1['F']}"
        f" · 목록의 공고 링크 L {s1['L']} → {s1['band']}",
        f"- 징후 2: 18쌍 중 120초 안에 안 뜬 쌍 G1 {s2['G1']}"
        f"(다시 질의한 뒤에도 {s2['G1_after_retry']})"
        f" · 기대값과 다른 쌍 G2 {s2['G2']} → {s2['band']}",
        f"- 징후 3: 새 LLM 호출 H {s3['H']} · 새 trace 행 T {s3['T']}(기대 {s3['T_expected']})"
        f" → {s3['band']}",
        "",
        f"측정 시작 {exp['taken_at']} · Next.js `next start` + FastAPI(실제 DB·실제 캐시)",
        "",
        "## 1. 징후 1~3",
        "",
        "### 징후 1 — Next.js 서버가 뜬다",
        "",
        "| 값 | 측정 | 기준 |",
        "| --- | --- | --- |",
        f"| F. 공고 페이지 중 실패한 수 | {s1['F']} / {s1['n_pages']} | 0 |",
        f"| L. `/` HTML의 공고 페이지 링크 수 | {s1['L']} | {len(exp['notices'])} |",
        f"| 구간 | {s1['band']} | 통과: F 0 · L 84 / 미완: 그 밖 |",
        "",
        "- 성공 = HTTP 200 · `<title>`에 공고 이름 · 주택형 표 행 수 = DB `notice_models` 행 수",
    ]
    if s1["pages_missing"]:
        out.append(f"- 측정되지 않은 공고 페이지: {', '.join(s1['pages_missing'])}")
    for f in s1["failed"]:
        out.append(f"- 실패 {f['house_manage_no']}: {'; '.join(f['why'])}")
    out += [
        "",
        "### 징후 2 — 유저 입장에서 청약별로 질의하고 결과를 확인한다",
        "",
        "| 값 | 측정 | 기준 |",
        "| --- | --- | --- |",
        f"| G1. 120초 안에 결과가 안 뜬 쌍 | {s2['G1']}"
        f" (다시 질의한 뒤 {s2['G1_after_retry']}) | 0 |",
        f"| G2. 결과가 떴는데 기대값과 다른 쌍 | {s2['G2']} | 0 |",
        f"| 구간 | {s2['band']} | 통과: 둘 다 0 / 다시 잰다: G2 0·G1 1 이상 / 미완: G2 1 이상, 또는 다시 잰 뒤에도 G1 1 이상 |",
        "",
        f"- 쌍 {s2['n_pairs']}개(공고 6건 × 프로필 3종) · 다시 질의한 횟수 {s2['retries']}"
        f" · 걸린 시간 중앙값 {med} · 최대 {mx}",
        "- 같다 = 전역 판정 · 경로별 (key, 판정) 집합 · 체크리스트 항목 수가 셋 다"
        " `runs/81/last_run.json`의 같은 쌍 `answer`와 같다",
    ]
    if s2["G1_pairs"]:
        out.append(f"- 첫 질의에 안 뜬 쌍: {', '.join(s2['G1_pairs'])}")
    if s2["pairs_missing"]:
        out.append(f"- 측정되지 않은 쌍: {', '.join(s2['pairs_missing'])}")
    for d in s2["diff"]:
        out += [
            f"- 다른 쌍 {d['pair']}",
            f"  - 화면: {json.dumps(d['screen'], ensure_ascii=False)}",
            f"  - 기대: {json.dumps(d['expected'], ensure_ascii=False)}",
        ]
    out += [
        "",
        "### 징후 3 — 화면이 CLI와 같은 판정 흐름을 탔다",
        "",
        "| 값 | 측정 | 기준 |",
        "| --- | --- | --- |",
        f"| H. 징후 2 동안 늘어난 LLM 호출 수(캐시 줄 수 차이) | {s3['H']} (판정 {s3['H_verdict']}"
        f" + 임베딩 {s3['H_embed']}) | 0 |",
        f"| T. 새 trace 행 수 | {s3['T']} | {s3['T_expected']} |",
        f"| 구간 | {s3['band']} | 통과: H 0 · T = 기대 / 미완: 그 밖 |",
        "",
        f"- 새 trace 행 상태 분포 {s3['statuses']}",
        "",
        "## 2. 스크린샷",
        "",
        "- `docs/84-web/verdict-full.png` — 더샵 분당하이스트(`2026000103`) × `full`",
        "- `docs/84-web/verdict-empty.png` — 같은 공고 × `empty`",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ("before", "after"):
        print(__doc__, file=sys.stderr)
        return 2
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(settings.database_url)
    try:
        if argv[0] == "before":
            snap = snapshot(engine)
            (RUN_DIR / "expected.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"기대값 {RUN_DIR / 'expected.json'} — 공고 {len(snap['notices'])}건"
                f" · 쌍 {len(snap['pairs'])}개"
            )
            return 0
        exp = json.loads((RUN_DIR / "expected.json").read_text(encoding="utf-8"))
        raw = json.loads((RUN_DIR / "raw.json").read_text(encoding="utf-8"))
        after = count_after(engine, exp["before"]["max_trace_id"])
        res = judge(exp, raw, after)
        (RUN_DIR / "last_run.json").write_text(
            json.dumps(
                {"expected_taken_at": exp["taken_at"], "after": after, **res},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        REPORT.write_text(render(exp, res), encoding="utf-8")
        print(REPORT.read_text(encoding="utf-8").split("## 1.")[0])
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
