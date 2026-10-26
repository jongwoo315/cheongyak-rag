"""공고별로 유효한 「주택공급에 관한 규칙」 버전을 확인한다 (#78).

view `notice_law_versions`(마이그레이션 0003)가 공고마다 고른 버전을 읽고, 서로 다른
(MST, 시행일)마다 법령 본문을 받아 `기본정보.시행일자`·`공포번호`가 `law_versions` 행과
같은지 대조한다.
본문은 `data/raw/law-008243-<시행일>.json`에 두고, 파일이 있으면 받지 않는다.
결과는 `runs/78/last_run.json`과 `docs/78-asof.md`다.
구간 문구는 plan §실패 징후의 문장을 따르되, 일부는 코드가 덧붙인다
(착수 실측과 다르다, 어긋났다 → 미완).
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings
from cheongyak_rag.ingest.law import (
    LAW_NAME,
    RAW_DIR,
    ROOT,
    SERVICE_URL,
    LawApiError,
    _check_name,
    _get_json,
    _require_oc,
)
from cheongyak_rag.ingest.notice_report import _bullets, _table

LAW_ID = "008243"
RUN_PATH = Path("runs/78/last_run.json")
VERSIONS_RUN = Path("runs/78/law_versions.json")
OUT_PATH = Path("docs/78-asof.md")
SAMPLES = 5
MAX_UNRESOLVED = 3  # plan §실패 징후 1: 안 정해진 공고가 이보다 많으면 미완
# 착수 시점(2026-10-25) 실측이다. 새 개정이나 새 공고가 나오면 구간 문구가 「다르다」를 낸다.
# 결과가 틀렸다는 뜻은 아니다. 공고 84건 전부 이 버전이었다
EXPECTED_VERSION = ("286965", "2026-06-15")
EXPECTED_ROWS = 129  # 착수 실측: 법령명이 정확히 일치하는 행 수
LATEST_AT_KICKOFF = "2026-06-15"


def _iso(v: date | None) -> str | None:
    return v.isoformat() if v else None


# ── 읽기 ─────────────────────────────────────────────────────────────────


def gather(engine: Engine) -> dict:
    with engine.connect() as conn:

        def q(sql: str, **params):
            return conn.execute(sa.text(sql), params).all()

        notices = q("SELECT count(*) FROM notices")[0][0]
        view = q(
            "SELECT v.house_manage_no, v.pblanc_no, n.house_nm, v.rcrit_pblanc_de, v.mst,"
            " v.effective_date, v.promulgation_no FROM notice_law_versions v"
            " JOIN notices n USING (house_manage_no, pblanc_no)"
            " ORDER BY v.rcrit_pblanc_de DESC, v.house_manage_no DESC"
        )
        n_rows, oldest, newest = q(
            "SELECT count(*), min(effective_date), max(effective_date) FROM law_versions"
            " WHERE law_id = :l",
            l=LAW_ID,
        )[0]
        same_day = q(
            "SELECT effective_date, array_agg(mst ORDER BY mst),"
            " (array_agg(mst ORDER BY promulgation_date DESC NULLS LAST,"
            " length(mst) DESC, mst DESC))[1]"
            " FROM law_versions WHERE law_id = :l GROUP BY effective_date"
            " HAVING count(DISTINCT mst) > 1 ORDER BY effective_date DESC",
            l=LAW_ID,
        )
        later = q(
            "SELECT effective_date, mst, promulgation_no FROM law_versions"
            " WHERE law_id = :l AND effective_date > :d ORDER BY effective_date, mst",
            l=LAW_ID,
            d=date.fromisoformat(LATEST_AT_KICKOFF),
        )
        earliest_notice = q("SELECT min(rcrit_pblanc_de) FROM notices")[0][0]

    counts: dict[tuple, dict] = {}
    for r in view:
        if r.mst is None:
            continue
        key = (r.mst, r.effective_date)
        entry = counts.setdefault(
            key,
            {
                "mst": r.mst,
                "effective_date": _iso(r.effective_date),
                "promulgation_no": r.promulgation_no,
                "notices": 0,
            },
        )
        entry["notices"] += 1
    return {
        "notices": notices,
        "view_rows": len(view),
        "decided": sum(1 for r in view if r.mst is not None),
        "unresolved": [
            {
                "house_manage_no": r.house_manage_no,
                "pblanc_no": r.pblanc_no,
                "house_nm": r.house_nm,
                "rcrit_pblanc_de": _iso(r.rcrit_pblanc_de),
            }
            for r in view
            if r.mst is None
        ],
        "by_version": sorted(
            counts.values(), key=lambda e: (e["effective_date"], e["mst"]), reverse=True
        ),
        "versions": {
            "rows": n_rows,
            "oldest": _iso(oldest),
            "newest": _iso(newest),
            "earliest_notice": _iso(earliest_notice),
            "after_kickoff": [
                {"effective_date": _iso(d), "mst": m, "promulgation_no": p} for d, m, p in later
            ],
        },
        "same_day_multi_mst": [
            {"effective_date": _iso(d), "msts": msts, "picked": picked}
            for d, msts, picked in same_day
        ],
        "samples": [
            {
                "house_nm": r.house_nm,
                "rcrit_pblanc_de": _iso(r.rcrit_pblanc_de),
                "mst": r.mst,
                "effective_date": _iso(r.effective_date),
            }
            for r in view[:SAMPLES]
        ],
    }


# ── 본문 대조 ────────────────────────────────────────────────────────────


def _dest(raw_dir: Path, effective: str) -> Path:
    return raw_dir / f"law-{LAW_ID}-{effective.replace('-', '')}.json"


def _load_body(oc: str, mst: str, effective: str, dest: Path, client: httpx.Client) -> dict:
    if dest.exists():
        try:
            cached = json.loads(dest.read_text(encoding="utf-8"))
        except ValueError as e:
            raise LawApiError(f"캐시가 깨졌다. 지우고 다시 실행할 것: {dest} ({e})") from None
        if not isinstance(cached, dict):
            raise LawApiError(f"캐시가 법령 응답이 아니다. 지우고 다시 실행할 것: {dest}")
        return _check_name(cached, oc)
    params = {"OC": oc, "target": "eflaw", "MST": mst, "efYd": effective.replace("-", ""),
              "type": "JSON"}  # fmt: skip
    body = _get_json(client, SERVICE_URL, params, oc)
    if not isinstance(body, dict):
        raise LawApiError(f"본문 응답이 법령 객체가 아니다: {type(body).__name__}")
    return _check_name(body, oc)


def _save(body: dict, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def compare(
    versions: list[dict], raw_dir: Path, oc: str, client: httpx.Client
) -> tuple[list[dict], int]:
    """고른 버전마다 본문의 시행일자·공포번호를 `law_versions` 행과 대조한다 → (결과, API 호출 수).

    일치한 본문만 파일로 둔다. 어긋난 본문을 두면 다음 실행이 같은 어긋남을 캐시에서 읽는다.
    본문을 못 읽은 버전은 `error`를 적고 다음 버전으로 간다.
    그래야 이미 읽은 결과가 리포트에 남는다.
    """
    results, calls = [], 0
    for v in versions:
        dest = _dest(raw_dir, v["effective_date"])
        cached = dest.exists()
        calls += not cached
        expected = {
            "시행일자": v["effective_date"].replace("-", ""),
            "공포번호": v["promulgation_no"],
        }
        actual = error = None
        try:
            body = _load_body(oc, v["mst"], v["effective_date"], dest, client)
        except LawApiError as e:
            error = str(e)
        else:
            info = body.get("법령", {}).get("기본정보", {})
            actual = {"시행일자": info.get("시행일자"), "공포번호": info.get("공포번호") or None}
            if expected == actual and not cached:
                _save(body, dest)
        results.append(
            {
                **{k: v[k] for k in ("mst", "effective_date", "notices")},
                "source": "cache" if cached else "api",
                "file": _rel(dest),
                "ok": error is None and expected == actual,
                "expected": expected,
                "actual": actual,
                "error": error,
            }  # fmt: skip
        )
    return results, calls


# ── 리포트 ───────────────────────────────────────────────────────────────


def _band_versions(unresolved: int, mismatch: int, picked: set[tuple]) -> str:
    if unresolved == 0 and mismatch == 0:
        band = "두 값 모두 0 → 통과"
    elif unresolved <= MAX_UNRESOLVED and mismatch == 0:
        band = (
            "안 정해진 공고 1~3건이고 불일치 0 → 그 공고 목록과 모집공고일, 원인을 리포트에 적는다"
        )
    else:
        band = (
            "안 정해진 공고 4건 이상, 또는 불일치 1건 이상"
            " → 미완. 규칙이나 목록 수집을 고치고 다시 잰다"
        )
    if picked != {EXPECTED_VERSION}:
        band += f". 착수 실측(전부 MST {EXPECTED_VERSION[0]})과 다르다 → 다른 MST가 나왔으면 미완"
    return band


def _band_rows(rows: int, duplicates: int | None) -> str:
    if duplicates:
        return "(MST, 시행일) 중복이 있다 → 미완"
    if rows == EXPECTED_ROWS:
        return f"{EXPECTED_ROWS}행 → 통과"
    if rows > EXPECTED_ROWS:
        return (
            f"{EXPECTED_ROWS + 1}행 이상 → 그 사이 개정이 나온 것이다."
            " 늘어난 행 목록을 리포트에 적는다"
        )
    return f"{EXPECTED_ROWS - 1}행 이하 → 미완. 페이지 넘김을 고친다"


def _band_calls(total: int) -> str:
    if total <= 5:
        return "5 이하 정상"
    return "6~10 재시도 원인을 리포트에" if total <= 10 else "11 이상 페이지 넘김·재시도 결함"


def _rerun(c: dict | None) -> tuple[str, bool | None]:
    prev = (c or {}).get("previous")
    if not prev:
        return "이전 실행이 없어 비교할 수 없다", None
    same = prev["rows_after"] == c["rows_after"] and prev["pk_digest"] == c["pk_digest"]
    ok = same and c["inserted"] == 0
    state = "그대로" if same else "달라졌다"
    return f"행 수와 PK 집합이 {state}, 새로 들어간 행은 {c['inserted']}건", ok


def _verdict(c: dict) -> str:
    if c["ok"]:
        return "일치"
    if c["error"]:
        return f"읽지 못했다: {c['error']}"
    return f"어긋남: 기대 {c['expected']} / 받은 값 {c['actual']}"


def render(run: dict) -> str:
    cmp_ = run["compare"]
    n_ok = sum(1 for c in cmp_ if c["ok"])
    mismatch = len(cmp_) - n_ok
    v, coll = run["versions"], run.get("collection")
    # 징후 2는 법제처 목록이 준 행 수다. 수집이 옛 행을 지우지 않으므로 테이블 행 수는 더 클 수 있다
    listed = coll["received"] if coll and "received" in coll else v["rows"]
    picked = {(e["mst"], e["effective_date"]) for e in run["by_version"]}
    rerun_text, rerun_ok = _rerun(coll)
    first = (
        f"공고 {run['decided']}/{run['notices']}건의 버전이 정해졌고,"
        f" 고른 버전은 {len(run['by_version'])}개이며, 본문 대조는 {n_ok}/{len(cmp_)}건 일치한다."
    )
    unresolved = run["unresolved"]
    if coll:
        total_calls = coll["calls"] + run["calls"]
        calls_text = f"{total_calls}회 (수집 목록 {coll['pages']}페이지 + 본문 대조 {run['calls']})"
        calls_band = _band_calls(total_calls)
    else:
        calls_text, calls_band = (
            f"본문 대조 {run['calls']}회. 수집 실행 요약이 없어 합계를 못 잰다",
            "—",
        )
    lines = [
        first,
        "",
        "# #78 공고별 유효 법령 버전 확인 결과",
        "",
        f"실행 {run['run_at']} · 법령 「{LAW_NAME}」(법령ID {LAW_ID}) · 공고 {run['notices']}건",
        "",
        "## 1. 실패 징후 측정값",
        "",
    ]
    rows = [
        (
            "1. 버전이 안 정해진 공고 수 · 본문 대조 불일치 수",
            f"안 정해진 공고 {len(unresolved)}건 · 불일치 {mismatch}건"
            f" (고른 버전 {', '.join(f'MST {m} 시행 {d}' for m, d in sorted(picked)) or '없음'})",
            _band_versions(len(unresolved), mismatch, picked),
        ),
        (
            "2. 목록 완결성",
            f"법령명 일치 {listed}행"
            + (f"(테이블에는 {v['rows']}행)" if listed != v["rows"] else "")
            + f" · 시행일 {v['oldest']} ~ {v['newest']}"
            f" · 가장 이른 모집공고일 {v['earliest_notice']}"
            f" · (MST, 시행일) 중복 {coll.get('duplicates', '—') if coll else '—'}건",
            _band_rows(listed, coll.get("duplicates") if coll else None),
        ),
        (
            "3. 같은 날 여러 MST",
            f"{len(run['same_day_multi_mst'])}일 (아래 표)",
            "판정 구간 없음 — 기록만",
        ),
        ("4. 호출", calls_text, calls_band),
        (
            "5. 재실행",
            rerun_text,
            "행 수와 PK 집합이 그대로이고 새로 들어간 행이 0이어야 한다"
            + ("" if rerun_ok is not False else ". 어긋났다 → 미완"),
        ),  # fmt: skip
        (
            "6. 키 노출",
            # main이 실행 요약 JSON과 이 리포트에서 키를 찾고, 있으면 파일을 쓰지 않고 exit 1이다
            "실행 요약 JSON 0회 · 이 리포트 0회(쓰기 전에 검사한다)",
            "테스트에서 가짜 OC 문자열이 출력·예외·리포트에 0회 나타나야 한다. 1회라도 나오면 버그",
        ),
    ]
    lines += _table(["지표", "측정값", "해당 구간 (plan 문구)"], rows)

    lines += ["", "## 2. 버전별 공고 수와 본문 대조", ""]
    by_key = {(c["mst"], c["effective_date"]): c for c in cmp_}
    lines += _table(
        ["MST", "시행일", "공고 수", "본문 출처", "본문 대조"],
        [
            (
                e["mst"],
                e["effective_date"],
                e["notices"],
                by_key[(e["mst"], e["effective_date"])]["source"],
                _verdict(by_key[(e["mst"], e["effective_date"])]),
            )
            for e in run["by_version"]
        ],
    )
    lines += ["", "### 버전이 안 정해진 공고", ""]
    lines += _bullets(
        [
            f"`{u['house_manage_no']}/{u['pblanc_no']}` {u['house_nm']} — 모집공고일"
            f" {u['rcrit_pblanc_de']}"
            for u in unresolved
        ]
    )
    if listed > EXPECTED_ROWS:
        lines += [
            "",
            f"### 착수 실측 뒤에 늘어난 행 (시행일이 {LATEST_AT_KICKOFF}보다 늦은 것)",
            "",
        ]
        lines += _bullets(
            [
                f"시행 {a['effective_date']} · MST {a['mst']} · 공포번호 {a['promulgation_no']}"
                for a in v["after_kickoff"]
            ]  # fmt: skip
        )

    same_days = {s["effective_date"] for s in run["same_day_multi_mst"]}
    same_day_hit = sum(e["notices"] for e in run["by_version"] if e["effective_date"] in same_days)
    lines += [
        "",
        "## 3. 같은 날 여러 MST",
        "",
        "고르는 규칙: 공포일이 늦은 쪽, 같으면 MST가 큰 쪽(설계 §1)."
        f" 이번 공고 중 고른 시행일이 이 날짜들에 드는 것은 {same_day_hit}건이다.",
        "",
    ]
    lines += _table(
        ["시행일", "MST 목록", "view가 고를 MST"],
        [
            (s["effective_date"], ", ".join(s["msts"]), s["picked"])
            for s in run["same_day_multi_mst"]
        ],
    )
    lines += ["", f"## 4. 공고 표본 {SAMPLES}건 (가장 최근 모집공고일)", ""]
    lines += _table(
        ["공고명", "모집공고일", "MST", "시행일"],
        [
            (s["house_nm"], s["rcrit_pblanc_de"], s["mst"], s["effective_date"])
            for s in run["samples"]
        ],
    )
    lines += [
        "",
        "## 5. 한계",
        "",
        "- 부칙 경과조치(「이 규칙 시행 전에 입주자모집 승인을 신청한 경우에는 종전 규칙」)는"
        " 반영하지 않았다. 공고별 승인 신청일이 API에 없어 모집공고일만 쓴다.",
        "- 본문은 시행일자·공포번호만 대조했다. 조문 파싱·적재는 #79·#80이다.",
        "",
        "## 6. 다시 돌리는 법",
        "",
        "```bash",
        "uv run alembic upgrade head",
        "uv run python -m cheongyak_rag.ingest.law_versions   # 목록 수집 (호출 2회)",
        "uv run python -m cheongyak_rag.asof                   # 공고별 버전 확인 + 본문 대조",
        "```",
        "",
        "본문 파일(`data/raw/law-008243-<시행일>.json`)이 있으면 받지 않는다."
        " 다시 받으려면 그 파일을 지우고 돌린다.",
    ]
    return "\n".join(lines) + "\n"


# ── 실행 ─────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv=None, client: httpx.Client | None = None, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(description="공고별 유효 법령 버전을 확인하고 본문을 대조한다")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--run", type=Path, default=RUN_PATH, help="실행 요약 JSON 경로")
    ap.add_argument("--out", type=Path, default=OUT_PATH, help="리포트 경로")
    ap.add_argument("--versions-run", type=Path, default=VERSIONS_RUN, help="수집 실행 요약 JSON")
    args = ap.parse_args(argv)

    # 키가 비면 아래 노출 검사의 `'' in text`가 항상 참이라 매번 걸려서 검사가 의미 없어진다
    try:
        oc = _require_oc(settings.law_oc)
    except LawApiError as e:
        print(f"API 오류: {e}", file=sys.stderr)
        return 1
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx는 INFO로 URL(OC 포함)을 찍는다

    own_engine, own_client = engine is None, client is None
    engine = engine or sa.create_engine(settings.database_url)
    client = client or httpx.Client(timeout=60)
    try:
        run = gather(engine)
        if run["versions"]["rows"] == 0:
            print(
                "law_versions가 비어 있다. 수집을 먼저 돌릴 것:"
                " uv run python -m cheongyak_rag.ingest.law_versions",
                file=sys.stderr,
            )
            return 1
        run["compare"], run["calls"] = compare(run["by_version"], args.raw_dir, oc, client)
    finally:
        if own_engine:
            engine.dispose()
        if own_client:
            client.close()

    try:
        run["collection"] = json.loads(args.versions_run.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        run["collection"] = None
    run["run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    run_text = json.dumps(run, ensure_ascii=False, indent=2)
    report = render(run)
    if oc in run_text or oc in report:
        print("실행 요약 또는 리포트에 인증값이 들어 있다. 쓰지 않는다", file=sys.stderr)
        return 1
    _write(args.run, run_text)
    _write(args.out, report)

    print(report.splitlines()[0])
    print(f"API 호출 {run['calls']}회 · 썼다: {args.run} · {args.out}")
    bad = [c for c in run["compare"] if not c["ok"]]
    for c in bad:
        what = c["error"] or f"기대 {c['expected']} / 받은 값 {c['actual']}"
        print(f"본문 대조 실패: MST {c['mst']} 시행 {c['effective_date']}: {what}", file=sys.stderr)
        if c["source"] == "cache":
            print(f"  예전 본문일 수 있다. {c['file']}을 지우고 다시 돌려 볼 것", file=sys.stderr)
    if run["view_rows"] != run["notices"]:
        print(f"view 행 수 {run['view_rows']} ≠ 공고 수 {run['notices']}", file=sys.stderr)
        return 1
    if len(run["unresolved"]) > MAX_UNRESOLVED or run["decided"] == 0:
        # plan §실패 징후 1: 안 정해진 공고 4건 이상은 미완이다. 하나도 못 정했으면 비교할 것도 없다
        print(f"버전이 안 정해진 공고 {len(run['unresolved'])}건: 미완", file=sys.stderr)
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
