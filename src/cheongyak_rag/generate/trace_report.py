"""#83 실패 징후 1~3을 재고 리포트 `docs/83-trace.md`·`runs/83/last_run.json`을 쓴다.

python -m cheongyak_rag.generate.trace_report --report [--retry]

`runs/79/last_run.json`의 표본 공고 6건 × `runs/80/profiles/`의 프로필 3종 18쌍, 없는 관리번호 1건,
꽉 찬 프로필 × 더샵 분당하이스트 한 번 더 — 질의 20건을 `trace.run_traced`로 돌려 실제 DB `traces`에
행을 쓴다. 측정 코드는 `trace.py`의 `run_traced`만 부른다. 가리기 비교 · 해시 검사 · 꼴 찾기는 이
모듈이 따로 한다(`hide` · `plain_sha` · `date_forms`). 새 행 수는 측정 전 `max(id)` 뒤로 센다.
"""

import argparse
import dataclasses
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag import profile as prof
from cheongyak_rag import trace
from cheongyak_rag.config import settings
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate import verdict_report as vr
from cheongyak_rag.generate.answer import GenCache, HardApiError, check_model, make_client
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.ingest.notice_report import _bullets, _table
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.embed import Embedder
from cheongyak_rag.retrieval.index_db_report import now, write

ROOT = Path(__file__).resolve().parents[3]
OUT_MD = ROOT / "docs/83-trace.md"
OUT_JSON = ROOT / "runs/83/last_run.json"
PROFILES_DIR = ROOT / "runs/80/profiles"
SAMPLES_JSON = ROOT / "runs/79/last_run.json"
BASELINE_JSON = ROOT / "runs/81/last_run.json"  # #81 측정 — 하위 질의 판정 분포
EXAMPLE = ("2026000103", "full")  # 행 한 개 전문: 더샵 분당하이스트 × 꽉 찬 프로필
MISSING_NOTICE = "0000000000"  # 없는 관리번호 — 실패 행 1개가 기대값이다
MASK_TEXT = "[프로필 값]"
EXPECTED_STATUS = {"ok": 19, "error": 1}  # 징후 1 — 같이 적는 기대 분포
FIRST_CALLS_RETRY = 3  # 징후 3 — 첫 실행 호출이 1~3이면 다시 잰다, 4 이상이면 미완
DERIVED = re.compile(r"\d+년\s?\d+개?월\s?\d+일")
HEX64 = re.compile(r"[0-9a-f]{64}")


# ── 프로필 (trace.py를 부르지 않고 다시 만든다) ───────────────────────────


def profile_dict(p: prof.Profile) -> dict:
    return {
        f.name: v.isoformat() if isinstance(v := getattr(p, f.name), date) else v
        for f in dataclasses.fields(p)
    }


def iso_values(p: prof.Profile) -> list[str]:
    """프로필의 글자 값. 날짜가 ISO 꼴(`2012-05-20`)로 든다. 긴 것부터."""
    return sorted(
        (v for v in profile_dict(p).values() if isinstance(v, str)), key=len, reverse=True
    )


def date_forms(p: prof.Profile) -> dict[str, list[str]]:
    """프로필 날짜마다 ISO가 아닌 네 꼴. 가리기가 놓치기 쉬운 쪽이다."""
    out = {}
    for f in dataclasses.fields(p):
        d = getattr(p, f.name)
        if isinstance(d, date):
            out[d.isoformat()] = [
                f"{d.year}년 {d.month}월 {d.day}일",
                f"{d.year}년 {d.month:02d}월 {d.day:02d}일",
                f"{d.year}.{d.month:02d}.{d.day:02d}",
                f"{d.year}/{d.month:02d}/{d.day:02d}",
            ]
    return out


def plain_sha(p: prof.Profile) -> str:
    """키 없는 SHA-256 — 해시가 이것과 같으면 비밀 키가 안 쓰인 것이다."""
    return hashlib.sha256(json.dumps(profile_dict(p), sort_keys=True).encode()).hexdigest()


def hide(obj, p: prof.Profile):
    """반환 응답에 따로 가리기를 해서 저장된 `answer`와 비교할 기대값을 만든다."""
    secrets = iso_values(p)

    def walk(x):
        if isinstance(x, str):
            for s in secrets:
                x = x.replace(s, MASK_TEXT)
            return x
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [walk(v) for v in x]
        return x

    return walk(obj)


# ── 구간 ─────────────────────────────────────────────────────────────────


def zone_rows(a: int, b: int) -> str:
    """징후 1 — 행 쓰기는 결정론적이라 1 이상이면 코드나 측정이 틀렸다. 다시 잴 구간이 없다."""
    return "통과" if a == 0 and b == 0 else "미완"


def zone_hide(c: int, d: int, e: int, retry: bool) -> str:
    """징후 2 — C·E가 0이고 D만 1 이상이면 다시 잰다. 이미 다시 쟀는데도 D가 남으면 미완이다."""
    if c or e:
        return "미완"
    if d == 0:
        return "통과"
    return "미완" if retry else "다시 잰다"


def zone_calls(first: int, second: int | None, dist_same: bool, stopped: bool) -> str:
    """징후 3 — 첫 실행 호출 0 · 두 번째 실행 호출 0 · 분포 같음이면 통과."""
    if stopped or not dist_same or first > FIRST_CALLS_RETRY:
        return "미완"
    if first > 0:
        return "다시 잰다"
    if second is None:
        return "미측정"
    return (
        "통과" if second == 0 else "판정 불가"
    )  # 첫 실행 0인데 두 번째가 0이 아닌 구간은 plan에 없다


# ── 측정 ─────────────────────────────────────────────────────────────────


def sample_pairs(notices: list[str], profile_names: list[str]) -> list[tuple[str, str, bool]]:
    """(관리번호, 프로필 이름, 18쌍 밖에 덧붙인 질의인지). 덧붙인 것은 두 건이다."""
    pairs = [(h, p, False) for h in notices for p in profile_names]
    return [*pairs, (MISSING_NOTICE, "full", True), (*EXAMPLE, True)]


def max_id(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT COALESCE(max(id), 0) FROM traces")).scalar_one()


def new_rows(engine: Engine, base: int) -> list[dict]:
    """측정 전 `max(id)` 뒤로 생긴 행. `json`은 행 전체를 JSON 글자로 직렬화한 것이다."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT t.id, t.house_manage_no, t.pblanc_no, t.profile_hash, t.status, t.error,"
                " t.verdict, t.seconds, t.steps, t.answer, row_to_json(t)::text AS json,"
                " pg_column_size(t.*) AS size FROM traces t WHERE t.id > :b ORDER BY t.id"
            ),
            {"b": base},
        )
        return [dict(r._mapping) for r in rows]


def measure(
    engine: Engine, embedder, client, cache, model: str, notices: list[str],
    profiles: dict[str, prof.Profile], *, key: str,
) -> dict:  # fmt: skip
    """질의 20건을 `run_traced`로 돌린다. 인증 오류면 거기서 멈춘다."""
    base = max_id(engine)
    search_cache: axes.Cache = {}
    queries, stop = [], None
    for hmn, pname, extra in sample_pairs(notices, list(profiles)):
        t0 = time.perf_counter()
        q = {"notice": hmn, "profile": pname, "extra": extra, "ok": False, "error": None}
        try:
            out = trace.run_traced(
                engine, embedder, client, model, hmn, profiles[pname], cache=cache, key=key,
                search_cache=search_cache,
            )  # fmt: skip
        except HardApiError as e:
            q["error"] = f"{type(e).__name__}: {e}"
            queries.append(q | {"seconds": time.perf_counter() - t0})
            stop = ("hard", f"{hmn} × {pname}: {e}")
            break
        except Exception as e:  # noqa: BLE001 — 질의 하나의 실패로 리포트 전체를 잃지 않는다
            q["error"] = f"{type(e).__name__}: {e}"
            queries.append(q | {"seconds": time.perf_counter() - t0})
            continue
        queries.append(
            q
            | {
                "ok": True,
                "seconds": time.perf_counter() - t0,
                "trace_id": out.trace_id,
                "trace_error": out.trace_error,
                "answer": json.loads(json.dumps(dataclasses.asdict(out.answer), default=str)),
                "verdicts": [
                    {"axis": v.axis, "query": v.query, "verdict": v.verdict, "cached": v.cached,
                     "no_context": v.no_context, "error": v.error}
                    for v in out.verdicts
                ],
            }
        )  # fmt: skip
    return {"base": base, "queries": queries, "rows": new_rows(engine, base), "stop": stop}


# ── 징후 1 — 행이 한 건씩 쌓이는가 ────────────────────────────────────────


def row_mismatches(queries: list[dict], rows: list[dict], profiles: dict) -> list[dict]:
    """B — 질의와 새 행을 순서대로 짝지어 넷 다 참인지 본다. 짝이 없는 행도 어긋난 행이다."""
    out = []
    for i, r in enumerate(rows):
        q = queries[i] if i < len(queries) else None
        if q is None:
            out.append(
                {"id": r["id"], "notice": r["house_manage_no"], "why": ["짝이 되는 질의 없음"]}
            )
            continue
        why = []
        if r["house_manage_no"] != q["notice"]:
            why.append(f"관리번호 {r['house_manage_no']} ≠ {q['notice']}")
        want = "ok" if q["ok"] else "error"
        if r["status"] != want:
            why.append(f"status {r['status']} ≠ {want}")
        if q["ok"]:
            if r["answer"] != hide(q["answer"], profiles[q["profile"]]):
                why.append("answer가 반환 응답을 가린 것과 다르다")
            n = len((r["steps"] or {}).get("queries", []))
            if n != len(q["answer"]["checklist"]):
                why.append(f"steps 하위 질의 {n} ≠ 체크리스트 {len(q['answer']['checklist'])}")
        elif r["answer"] is not None:
            why.append("실패 행의 answer가 null이 아니다")
        if why:
            out.append({"id": r["id"], "notice": q["notice"], "profile": q["profile"], "why": why})
    return out


def status_stats(queries: list[dict], rows: list[dict]) -> dict:
    secs = [q["seconds"] for q in queries]
    sizes = [r["size"] for r in rows]
    return {
        "status": dict(Counter(r["status"] for r in rows)),
        "errors": [r["error"] for r in rows if r["status"] == "error"],
        "size_median": statistics.median(sizes) if sizes else 0,
        "size_max": max(sizes, default=0),
        "seconds_median": statistics.median(secs) if secs else 0.0,
    }


# ── 징후 2 — 프로필 원본을 남기지 않는가 ──────────────────────────────────


def leaks(queries: list[dict], rows: list[dict], profiles: dict) -> dict:
    """C(ISO 꼴 그대로 나온 행) · D(다른 꼴로 나온 행) · 가린 횟수 · 파생값이 나온 행."""
    c, d, masked, derived = [], [], [], []
    for i, r in enumerate(rows):
        if i >= len(queries):
            break
        p = profiles[queries[i]["profile"]]
        text = r["json"]
        hit_c = [v for v in iso_values(p) if v in text]
        forms = date_forms(p)
        hit_d = [f for fs in forms.values() for f in fs if f in text]
        known = set(hit_d)  # D에서 센 꼴은 파생값에서 뺀다
        hit_x = sorted({m for m in DERIVED.findall(text) if m not in known})
        n_mask = text.count(MASK_TEXT)
        masked.append({"id": r["id"], "n": n_mask})
        if hit_c:
            c.append({"id": r["id"], "profile": queries[i]["profile"], "found": hit_c})
        if hit_d:
            d.append({"id": r["id"], "profile": queries[i]["profile"], "found": hit_d})
        if hit_x:
            derived.append({"id": r["id"], "profile": queries[i]["profile"], "found": hit_x})
    return {"C": c, "D": d, "masked": masked, "derived": derived}


def hash_problems(queries: list[dict], rows: list[dict], profiles: dict) -> list[dict]:
    """E — 해시 검사에 걸린 행. 넷 중 하나라도 걸리면 그 행을 센다."""
    by_profile: dict[str, str] = {}
    owner: dict[str, set[str]] = {}
    for i, r in enumerate(rows[: len(queries)]):
        by_profile.setdefault(queries[i]["profile"], r["profile_hash"])
        owner.setdefault(r["profile_hash"], set()).add(queries[i]["profile"])
    out = []
    for i, r in enumerate(rows[: len(queries)]):
        name, h = queries[i]["profile"], r["profile_hash"]
        why = []
        if h != by_profile[name]:
            why.append("같은 프로필 다른 해시")
        if len(owner[h]) > 1:
            why.append("다른 프로필과 해시가 겹친다")
        if h == plain_sha(profiles[name]):
            why.append("키 없는 SHA-256과 같다")
        if not HEX64.fullmatch(h or ""):
            why.append("64자 16진수가 아니다")
        if why:
            out.append({"id": r["id"], "profile": name, "why": why})
    return out


# ── 징후 3 — 같은 응답을 읽었나 ───────────────────────────────────────────


def distribution(cells: list[dict]) -> dict:
    """프로필 → 축 → 최종 판정 개수."""
    out: dict = {}
    for c in cells:
        for v in c["verdicts"]:
            n = out.setdefault(c["profile"], {}).setdefault(v["axis"], Counter())
            n[v["verdict"] or "판정 없음"] += 1
    return {p: {a: dict(sorted(n.items())) for a, n in sorted(ax.items())} for p, ax in out.items()}


def dist_diffs(queries: list[dict], baseline: dict, notices: list[str]) -> list[dict]:
    """18쌍의 분포를 #81 측정과 (프로필, 축) 칸마다 맞춰 다른 칸."""
    mine = distribution([q for q in queries if q["ok"] and not q["extra"]])
    old = distribution([c for c in baseline["cells"] if c["notice"] in notices])
    return [
        {"profile": p, "axis": a, "now": mine.get(p, {}).get(a), "before": old.get(p, {}).get(a)}
        for p in sorted(set(mine) | set(old))
        for a in sorted(set(mine.get(p, {})) | set(old.get(p, {})))
        if mine.get(p, {}).get(a) != old.get(p, {}).get(a)
    ]


def usage(m: dict, client) -> dict:
    return {"calls": client.calls, "retries": client.retries}


def attach_runs(run: dict, prev: dict | None) -> None:
    """첫 실행(`first_run`)과 같은 명령을 한 번 더 돌린 실행(`second_run`)을 가른다.

    직전 기록이 같은 프롬프트·모델의 첫 실행을 갖고 있으면 이번 완주 실행은 두 번째 실행이다.
    멈춘 실행은 첫 실행으로 치지 않는다.
    """
    prev = prev or {}
    same = prev.get("system_sha") == run["system_sha"] and prev.get("model") == run["model"]
    old = prev.get("first_run") if same else None
    cur = run["usage"]
    stopped = bool(run["stop"])
    first, second = (old, None if stopped else cur) if old else (None if stopped else cur, None)
    run["first_run"], run["second_run"] = first, second
    base = first or cur
    z = run["symptoms"]["zones"]
    z["calls"] = zone_calls(
        base["calls"], second["calls"] if second else None,
        not run["symptoms"]["dist_diffs"], stopped,
    )  # fmt: skip


def symptoms(m: dict, profiles: dict, baseline: dict, notices: list[str], retry: bool) -> dict:
    q, rows = m["queries"], m["rows"]
    a = abs(len(q) - len(rows))
    bad = row_mismatches(q, rows, profiles)
    lk = leaks(q, rows, profiles)
    e = hash_problems(q, rows, profiles)
    diffs = dist_diffs(q, baseline, notices)
    return {
        "queries": len(q),
        "new_rows": len(rows),
        "A": a,
        "B": len(bad),
        "diffs_b": bad,
        "stats": status_stats(q, rows),
        "C": len(lk["C"]),
        "D": len(lk["D"]),
        "E": len(e),
        "leaks": lk,
        "diffs_e": e,
        "dist_diffs": diffs,
        "zones": {
            "rows": zone_rows(a, len(bad)),
            "hide": zone_hide(len(lk["C"]), len(lk["D"]), len(e), retry),
            "calls": "미측정",
        },
    }


# ── 리포트 ───────────────────────────────────────────────────────────────


def first_lines(s: dict) -> list[str]:
    return [
        f"징후 1: 질의 {s['queries']}건에 새 행 {s['new_rows']}개 — 차이 A {s['A']} ·"
        f" 맞지 않는 행 B {s['B']} → {s['zones']['rows']}",
        f"징후 2: ISO 꼴 그대로 나온 행 C {s['C']} · 다른 꼴로 나온 행 D {s['D']} ·"
        f" 해시 검사에 걸린 행 E {s['E']} → {s['zones']['hide']}",
    ]


def _short(h: str | None) -> str:
    return (h or "")[:12]


def _json(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2, default=str)


def render(run: dict, baseline: dict) -> str:
    s, m = run["symptoms"], run["measure"]
    qs, rows = m["queries"], m["rows"]
    st = s["stats"]
    lk = s["leaks"]
    out = [
        "# #83 trace 저장 — 측정 리포트",
        "",
        *[f"- {x}" for x in first_lines(s)],
        "",
        f"실행 {run['run_at']} · 모델 `{run['model']}` · 프롬프트 {run['system_sha']}"
        f" · 공고 {len(run['notices'])}건 × 프로필 {len(run['profiles'])}종"
        + (" · 다시 잰 실행(`--retry`)" if run["retry"] else ""),
        "",
        "## 1. 징후 1~3",
        "",
        "### 징후 1 — 질의 한 건이 행 한 개씩 쌓이는가",
        "",
        *_table(
            ["값", "측정", "기준"],
            [
                (
                    "A. 질의 수와 새 행 수의 차이",
                    f"{s['A']} (질의 {s['queries']} · 새 행 {s['new_rows']})",
                    "0",
                ),
                ("B. 질의와 맞지 않는 새 행", s["B"], "0"),
                ("구간", s["zones"]["rows"], "통과: A 0 · B 0 / 미완: 1 이상"),
            ],
        ),
        "",
        *_bullets(
            [
                f"status 분포 {st['status']} (기대값 {EXPECTED_STATUS})",
                "실패 행의 `error`: " + (" / ".join(st["errors"]) or "없음"),
                f"행당 크기(`pg_column_size`) 중앙값 {st['size_median']:,.0f}바이트 · 최대"
                f" {st['size_max']:,}바이트",
                f"질의당 걸린 시간 중앙값 {st['seconds_median']:.2f}초",
            ]
        ),
    ]
    if s["diffs_b"]:
        out += [
            "",
            "맞지 않는 행",
            "",
            *_bullets([f"행 {x['id']} — {'; '.join(x['why'])}" for x in s["diffs_b"]]),
        ]
    n_mask = sum(x["n"] for x in lk["masked"])
    out += [
        "",
        "### 징후 2 — 프로필 원본을 남기지 않는가",
        "",
        *_table(
            ["값", "측정", "기준"],
            [
                ("C. ISO 꼴(`YYYY-MM-DD`) 그대로 나온 행", s["C"], "0"),
                ("D. 다른 꼴(`YYYY년 M월 D일`·`YYYY.MM.DD` 등 네 가지)로 나온 행", s["D"], "0"),
                ("E. 해시 검사에 걸린 행", s["E"], "0"),
                (
                    "구간",
                    s["zones"]["hide"],
                    "통과: 셋 다 0 / 다시 잰다: D만 1 이상 / 미완: C·E 1 이상, 다시 잰 뒤에도 D",
                ),
            ],
        ),
        "",
        *_bullets(
            [
                f"가린 횟수 전체 {n_mask}번 — 행마다: "
                + (", ".join(f"{x['id']}:{x['n']}" for x in lk["masked"]) or "없음"),
                f"파생값(`N년 N개월 N일` 꼴 기간)이 나온 행 {len(lk['derived'])}개 — 판정 안 함"
                " (설계 §이번에 안 하는 것). D에서 센 날짜 꼴은 뺐다",
                "착수 때 main 세션이 #81 측정(`runs/81/last_run.json`)에서 센 값: LLM 이유 135개 중"
                " 프로필 날짜를 그대로 적은 것 10개",
            ]
        ),
    ]
    for key, label in (("C", "ISO 꼴"), ("D", "다른 꼴")):
        if lk[key]:
            out += [
                "",
                f"{label}로 나온 행",
                "",
                *_bullets([f"행 {x['id']} ({x['profile']}) — {x['found']}" for x in lk[key]]),
            ]
    if s["diffs_e"]:
        out += [
            "",
            "해시 검사에 걸린 행",
            "",
            *_bullets(
                [f"행 {x['id']} ({x['profile']}) — {'; '.join(x['why'])}" for x in s["diffs_e"]]
            ),
        ]
    u = run["usage"]
    out += [
        "",
        "### 징후 3 — 같은 응답을 읽었나",
        "",
        *_table(
            ["값", "측정", "기준"],
            [
                (
                    "첫 실행 LLM 호출 수(캐시 제외)",
                    run["first_run"]["calls"] if run["first_run"] else "—",
                    "0",
                ),
                (
                    "같은 명령 두 번째 실행 호출 수",
                    run["second_run"]["calls"] if run["second_run"] else "아직 안 잼",
                    "0",
                ),
                ("이번 실행 호출 수", u["calls"], ""),
                ("18쌍 최종 판정 분포가 #81과 다른 (프로필, 축) 칸", len(s["dist_diffs"]), "0"),
                (
                    "구간",
                    s["zones"]["calls"],
                    "통과: 둘 다 0, 분포 같음 / 다시 잰다: 첫 실행 1~3 / "
                    "미완: 첫 실행 4 이상 또는 분포 다름",
                ),
            ],
        ),
    ]
    if s["dist_diffs"]:
        out += [
            "",
            "분포가 다른 칸",
            "",
            *_bullets(
                [
                    f"{x['profile']} · {x['axis']}: 이번 {x['now']} / #81 {x['before']}"
                    for x in s["dist_diffs"]
                ]
            ),
        ]
    ex = next((i for i, q in enumerate(qs) if (q["notice"], q["profile"]) == EXAMPLE), None)
    fail = [r for r in rows if r["status"] == "error"]
    out += [
        "",
        "## 2. 질의 20건과 행",
        "",
        *_table(
            [
                "#",
                "관리번호",
                "프로필",
                "status",
                "전역 판정",
                "해시 앞 12자",
                "가린 횟수",
                "크기(바이트)",
            ],
            [
                (
                    i + 1,
                    q["notice"],
                    q["profile"],
                    rows[i]["status"] if i < len(rows) else "행 없음",
                    (rows[i]["verdict"] or "—") if i < len(rows) else "—",
                    _short(rows[i]["profile_hash"]) if i < len(rows) else "—",
                    lk["masked"][i]["n"] if i < len(lk["masked"]) else "—",
                    f"{rows[i]['size']:,}" if i < len(rows) else "—",
                )
                for i, q in enumerate(qs)
            ],
        ),
        "",
        "## 3. 행 한 개 전문 — 더샵 분당하이스트 × 꽉 찬 프로필",
        "",
    ]
    if ex is not None and ex < len(rows):
        r = rows[ex]
        out += [
            f"행 {r['id']}. 가린 자리에는 `{MASK_TEXT}`가 적혀 있다.",
            "",
            "`steps`",
            "",
            "```json",
            _json(r["steps"]),
            "```",
            "",
            "`answer`",
            "",
            "```json",
            _json(r["answer"]),
            "```",
        ]
    else:
        out += ["이번 실행에 이 질의의 행이 없다."]
    out += ["", "## 4. 실패 행 전문", ""]
    if fail:
        for r in fail:
            shown = {k: v for k, v in r.items() if k not in ("json",)} | {
                "profile_hash": _short(r["profile_hash"]) + "…"
            }
            out += [f"행 {r['id']}", "", "```json", _json(shown), "```", ""]
    else:
        out += ["이번 실행에 실패 행이 없다.", ""]
    out += ["## 5. 파생값이 나온 행", ""]
    out += _bullets([f"행 {x['id']} ({x['profile']}) — {x['found']}" for x in lk["derived"][:50]])
    out += [
        "",
        "## 6. 표본",
        "",
        *_bullets(
            [
                "공고: " + ", ".join(run["notices"]),
                "프로필: " + ", ".join(run["profiles"]),
                f"덧붙인 질의 2건: 없는 관리번호 `{MISSING_NOTICE}` × full, "
                f"{EXAMPLE[0]} × {EXAMPLE[1]} 한 번 더",
                f"분포 비교 기준: `runs/81/last_run.json`(프롬프트 {baseline.get('system_sha')})",
                "측정 전 `max(id)` " + str(m["base"]),
            ]
        ),
    ]
    return "\n".join(out) + "\n"


def slim(m: dict) -> dict:
    """JSON에 남길 질의와 행. 응답 전문 · `steps`는 DB 행에 있다."""
    return {
        "queries": [
            {k: v for k, v in q.items() if k not in ("answer", "verdicts")} for q in m["queries"]
        ],
        "rows": [
            {k: v for k, v in r.items() if k not in ("json", "steps", "answer")}
            | {"profile_hash": _short(r["profile_hash"])}
            for r in m["rows"]
        ],
        "base": m["base"],
        "stop": m["stop"],
    }


def dump(run: dict) -> str:
    return json.dumps(run, ensure_ascii=False, indent=2, default=str) + "\n"


def load_baseline(path: Path) -> dict:
    """#81 측정 기록. 없거나 못 읽으면 예외 — 비교 대상 없이 재면 같은 응답을 읽었는지 모른다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("system_sha", "cells"):
        data[key]  # noqa: B018 — 없는 키는 KeyError로 준비 실패가 된다
    return data


def _read_prev(path: Path) -> dict | None:
    return vr._read_prev(path)


# ── 실행 ─────────────────────────────────────────────────────────────────


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    embedder=None,
    client=None,
    cache_path: Path | None = None,
    trace_key: str | None = None,
    samples_json: Path = SAMPLES_JSON,
    profiles_dir: Path = PROFILES_DIR,
    baseline_json: Path = BASELINE_JSON,
    out_md: Path = OUT_MD,
    out_json: Path = OUT_JSON,
    sleep=time.sleep,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.trace_report")
    ap.add_argument(
        "--report", action="store_true", required=True,
        help="질의 20건을 run_traced로 돌려 징후 1~3을 잰다",
    )  # fmt: skip
    ap.add_argument(
        "--retry", action="store_true", help="징후 2가 다시 잰다여서 고친 뒤 다시 잰 실행"
    )
    ap.add_argument("--model", default=settings.openai_gen_model)
    args = ap.parse_args(argv)
    key = settings.trace_hash_key if trace_key is None else trace_key
    if not key:
        print("`TRACE_HASH_KEY`가 없다. .env에 채운다 (.env.example 참고)", file=sys.stderr)
        return 2
    try:
        notices = vr.sample_notices(samples_json)
        profiles = vr.load_profiles(profiles_dir)
        baseline = load_baseline(baseline_json)
        prev = _read_prev(out_json)  # 호출 비용을 쓰기 전에 읽는다
        check_model(args.model)
        client = RetryingClient(client or make_client(), sleep=sleep)
    except (OSError, KeyError, ValueError, HardApiError) as e:
        print(f"준비 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            ready = conn.execute(sa.text("SELECT to_regclass('traces')")).scalar()
        if ready is None:
            print("traces 테이블이 없다. 먼저 uv run alembic upgrade head", file=sys.stderr)
            return 2
        cache = GenCache(cache_path or vd.cache_path_for(args.model))
        m = measure(
            engine, embedder or Embedder(settings.openai_embed_model), client, cache, args.model,
            notices, profiles, key=key,
        )  # fmt: skip
        run = {
            "run_at": now(),
            "model": args.model,
            "system_sha": vr.system_sha(),
            "notices": notices,
            "profiles": list(profiles),
            "retry": args.retry,
            "stop": m["stop"],
            "symptoms": symptoms(m, profiles, baseline, notices, args.retry),
            "usage": usage(m, client),
        }
        attach_runs(run, prev)
        text = render({**run, "measure": m}, baseline)
        saved = {**run, **slim(m)}
        write(out_md, text)
        write(out_json, dump(saved))
        print("\n".join(first_lines(run["symptoms"])))
        print("구간: " + " · ".join(f"{k} {v}" for k, v in run["symptoms"]["zones"].items()))
        print(f"→ {out_md} · {out_json}")
        if run["stop"]:
            print(f"멈춤({run['stop'][0]}): {run['stop'][1]}", file=sys.stderr)
        z = run["symptoms"]["zones"]
        # 징후 1 또는 2가 미완이거나 실행이 멈췄으면 리포트를 쓴 뒤 exit 1
        return 1 if run["stop"] or "미완" in (z["rows"], z["hide"]) else 0
    except SQLAlchemyError as e:
        print(f"DB 오류: {type(e).__name__}: {getattr(e, 'orig', e)}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
