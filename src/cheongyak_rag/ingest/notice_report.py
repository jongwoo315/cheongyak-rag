"""공고 수집 결과를 `docs/71-notice-ingest.md`로 쓴다 (#71).

수집 실행이 남긴 `runs/71/last_run.json`, 저장된 swagger 사본, DB를 읽는다. API를 부르지 않는다.
구간 문구는 plan §실패 징후의 문장 그대로다.
"""

import argparse
import json
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings
from cheongyak_rag.ingest import notice

RUN_PATH = Path("runs/71/last_run.json")
SWAGGER_PATH = Path("runs/71/swagger.json")
NOTES_PATH = Path("runs/71/notes.md")
OUT_PATH = Path("docs/71-notice-ingest.md")
SPEC_MODELS = {
    "notices": "getAPTLttotPblancDetail_model",
    "models": "getAPTLttotPblancMdl_model",
}
SAMPLES = 5


# ── 수집 ─────────────────────────────────────────────────────────────────


def spec_diff(swagger: dict, run: dict) -> dict:
    out = {}
    for name, model in SPEC_MODELS.items():
        spec = set(swagger["definitions"][model]["properties"])
        got = set(run["response_keys"][name])
        out[name] = {
            "response_not_in_spec": sorted(got - spec),
            "spec_not_in_response": sorted(spec - got),
            "response_count": len(got),
            "spec_count": len(spec),
        }
    return out


def gather(engine: Engine, run: dict, swagger: dict) -> dict:
    q = lambda conn, sql: conn.execute(sa.text(sql)).all()  # noqa: E731
    with engine.connect() as conn:
        n_rows, lo, hi = q(
            conn, "SELECT count(*), min(rcrit_pblanc_de), max(rcrit_pblanc_de) FROM notices"
        )[0]
        tables = {
            "notices": {
                "rows": n_rows,
                "min": lo,
                "max": hi,
                "by_year": q(
                    conn,
                    "SELECT extract(year FROM rcrit_pblanc_de)::int, count(*) FROM notices"
                    " GROUP BY 1 ORDER BY 1",
                ),
                "by_area": q(
                    conn,
                    "SELECT coalesce(subscrpt_area_nm, '(빈 값)'), count(*) FROM notices"
                    " GROUP BY 1 ORDER BY 2 DESC, 1",
                ),
                "by_kind": q(
                    conn,
                    "SELECT coalesce(raw->>'HOUSE_DTL_SECD_NM', '(빈 값)'), count(*) FROM notices"
                    " GROUP BY 1 ORDER BY 2 DESC, 1",
                ),
            },
            "models": {"rows": q(conn, "SELECT count(*) FROM notice_models")[0][0]},
        }
        samples = []
        for r in q(
            conn,
            "SELECT house_manage_no, pblanc_no, house_nm, subscrpt_area_nm, rcrit_pblanc_de,"
            " rcept_bgnde, rcept_endde, tot_suply_hshldco FROM notices"
            f" ORDER BY rcrit_pblanc_de DESC, house_manage_no DESC LIMIT {SAMPLES}",
        ):
            models = conn.execute(
                sa.text(
                    "SELECT model_no, house_ty, suply_ar, suply_hshldco, spsply_hshldco,"
                    " lttot_top_amount FROM notice_models"
                    " WHERE house_manage_no = :h AND pblanc_no = :p ORDER BY model_no"
                ),
                {"h": r[0], "p": r[1]},
            ).all()
            samples.append({"notice": tuple(r), "models": [tuple(m) for m in models]})
    return {"run": run, "tables": tables, "samples": samples, "spec": spec_diff(swagger, run)}


# ── 구간 ─────────────────────────────────────────────────────────────────


def _rerun(run: dict) -> tuple[str, bool | None]:
    """재실행 비교 문장과 통과 기준 4를 만족했는지(비교할 이전 실행이 없으면 None)."""
    prev = run.get("previous")
    if not prev:
        return "이전 실행이 없어 비교할 수 없다", None
    n, m = run["notices"], run["models"]
    same = (
        prev["notices_rows_after"] == n["rows_after"]
        and prev["models_rows_after"] == m["rows_after"]
        and prev["notices_pk_digest"] == n["pk_digest"]
        and prev["models_pk_digest"] == m["pk_digest"]
    )
    new = n["inserted"] + m["inserted"]
    ok = same and new == 0
    state = "그대로" if same else "달라졌다"
    return f"행 수와 PK 집합이 {state}, 새로 들어간 행은 {new}건", ok


def _load_band(run: dict) -> tuple[str, int, int]:
    # 빠진 PK와 남는 PK를 둘 다 센다
    n_gap = abs(run["notices"]["match_count"] - run["notices"]["in_table"]) + len(
        run["notices"]["extra"]
    )
    m_gap = abs(run["models"]["match_count"] - run["models"]["in_table"]) + len(
        run["models"]["extra"]
    )
    if n_gap == 0 and m_gap == 0:
        band = "두 테이블 모두 0 → 통과"
    elif n_gap <= 3 and m_gap <= 20:
        band = (
            "1~3건(`notices`) 또는 1~20건(`notice_models`) 차이"
            " → 빠진·남는 PK 목록과 원인을 리포트에 적는다"
        )
    else:
        band = "그보다 크면 미완. 페이지 넘김이나 upsert를 고치고 다시 잰다"
    if _rerun(run)[1] is False:
        band += ". 통과 기준 4가 깨졌다 → 미완"
    return band, n_gap, m_gap


def _raw_ratio(run: dict) -> float:
    total = run["notices"]["received"] + run["models"]["received"]
    same = run["notices"]["raw_same"] + run["models"]["raw_same"]
    return 100.0 if total == 0 else same / total * 100


def _raw_band(pct: float) -> str:
    if pct == 100:
        return "100% 통과"
    return "99~100% 다른 행 목록" if pct >= 99 else "< 99% 저장 결함"


def _convert_band(n: int) -> str:
    if n == 0:
        return "0 통과"
    return "1~10 값 목록을 리포트에" if n <= 10 else "> 10 변환 규칙 결함"


def _no_models_band(n: int) -> str:
    if n == 0:
        return "0 정상"
    if n <= 3:
        return "1~3건 공고번호 목록과 그 공고를 API로 다시 조회한 결과를 리포트에"
    return "> 3건 원인을 찾는다(조건 파라미터가 틀렸는지)"


def _calls_band(total: int, notices: int) -> str:
    if total <= notices + 10:
        return "≤ 공고 수 + 10 정상"
    if total <= notices * 2:
        return "그보다 크고 공고 수 × 2 이하 재시도 원인을 리포트에"
    return "공고 수 × 2 초과 페이지 넘김·재시도 결함"


# ── 출력 ─────────────────────────────────────────────────────────────────


def _cell(v) -> str:
    return "—" if v is None else str(v).replace("|", "\\|")


def _table(header: list[str], rows: list[tuple]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _bullets(items: list[str]) -> list[str]:
    return [f"- {i}" for i in items] or ["- 없다"]


def _pct(a: int, b: int) -> str:
    return "—" if b == 0 else f"{a / b * 100:.1f}%"


def render(d: dict) -> str:
    run, n, m = d["run"], d["run"]["notices"], d["run"]["models"]
    rerun_text, rerun_ok = _rerun(run)
    load_band, n_gap, m_gap = _load_band(run)
    pct = _raw_ratio(run)
    failed, no_models = run["convert"]["failed"], run["no_models"]
    c = run["calls"]
    spec_n, spec_m = d["spec"]["notices"], d["spec"]["models"]
    spec_total = sum(
        len(s[k])
        for s in (spec_n, spec_m)
        for k in ("response_not_in_spec", "spec_not_in_response")
    )

    rerun_line = (
        "같은 명령을 다시 돌려 본 결과는 없다"
        if rerun_ok is None
        else f"같은 명령을 다시 돌린 결과 {rerun_text}이다"
    )
    lines = [
        f"공고 {n['in_table']}/{n['match_count']}건과 주택형 {m['in_table']}/{m['match_count']}건이"
        f" 테이블에 있다(적재율 {_pct(n['in_table'], n['match_count'])}·"
        f"{_pct(m['in_table'], m['match_count'])}). {rerun_line}."
        f" 주택형 없는 공고는 {len(no_models)}건이다.",
        "",
        "# #71 공고 구조화 수집 결과",
        "",
        f"실행 {run['run_at']} · 모집공고일 {run['since']} 이후({run.get('months', 3)}개월) ·"
        f" 걸린 시간 {run['elapsed_sec']}초",
        "",
        "## 1. 지표",
        "",
    ]
    rows = [
        (
            "1. 적재율 (matchCount − 테이블에 있는 수)",
            f"`notices` {n['match_count']} − {n['in_table']} = {n_gap}건 ·"
            f" `notice_models` {m['match_count']} − {m['in_table']} = {m_gap}건"
            f" · 재실행: {rerun_text}",
            load_band,
        ),
        (
            "2. 필드 보존 (raw 키 집합 = 응답 키 집합)",
            f"{pct:.1f}% (공고 {n['raw_same']}/{n['received']}"
            f" · 주택형 {m['raw_same']}/{m['received']})",
            _raw_band(pct),
        ),
        (
            "3. 타입 변환 실패",
            f"{len(failed)}건 (원문이 빈 값인 것 {run['convert']['empty']}건은 따로 센다)",
            _convert_band(len(failed)),
        ),
        ("4. 주택형 없는 공고", f"{len(no_models)}건", _no_models_band(len(no_models))),
        (
            "5. 명세 차이",
            f"{spec_total}건 (공고: 응답에만 {len(spec_n['response_not_in_spec'])}·명세에만"
            f" {len(spec_n['spec_not_in_response'])} / 주택형: 응답에만"
            f" {len(spec_m['response_not_in_spec'])}·명세에만"
            f" {len(spec_m['spec_not_in_response'])})",
            "판정 구간 없음 — 기록만",
        ),
        (
            "6. 호출",
            f"{c['total']}회 (상세 {c['detail']} · 주택형 {c['models']} · 재조회 {c['recheck']}),"
            f" 재시도 {c['retries']}회, 공고 {n['received']}건",
            _calls_band(c["total"], n["received"]),
        ),
        (
            "7. 키 노출",
            # 1회라도 있으면 main이 리포트를 쓰지 않고 멈춘다. 여기까지 왔으면 0이다
            "실행 요약 JSON 0회 · 이 리포트 0회(쓰기 전에 검사한다)",
            "테스트에서 가짜 키 문자열이 출력·예외·리포트에 0회 나타나야 한다. 1회라도 나오면 버그",
        ),
    ]
    lines += _table(["지표", "측정값", "해당 구간 (plan 문구)"], rows)

    t, tn = d["tables"], d["tables"]["notices"]
    lines += [
        "",
        "## 2. 테이블 요약",
        "",
        f"- `notices` {tn['rows']}행 · `notice_models` {t['models']['rows']}행",
        f"- 모집공고일: 최소 {tn['min']} · 최대 {tn['max']}",
        "",
        "**연도별 공고 수**",
        "",
        *_table(["연도", "공고 수"], tn["by_year"]),
        "",
        "**공급지역별 공고 수**",
        "",
        *_table(["공급지역", "공고 수"], tn["by_area"]),
        "",
        "**주택구분별 공고 수**",
        "",
        *_table(["주택구분", "공고 수"], tn["by_kind"]),
        "",
        f"## 3. 표본 {SAMPLES}건 (가장 최근 모집공고일)",
        "",
    ]
    for s in d["samples"]:
        hm, pb, name, area, de, bgn, end, tot = s["notice"]
        lines += [
            f"**{name}** — `{hm}/{pb}` · {area} · 모집공고일 {de} · 접수 {bgn} ~ {end} · {tot}세대",
            "",
        ]
        if s["models"]:
            lines += _table(
                ["번호", "주택형", "공급면적", "일반공급", "특별공급", "분양최고금액(만원)"],
                s["models"],
            )
        else:
            lines.append("주택형 행이 없다")
        lines.append("")

    lines += ["## 4. 목록", "", "### 주택형 없는 공고", ""]
    lines += _bullets(
        [
            f"`{e['pk']}` — 다시 조회한 matchCount: {_cell(e['recheck_match_count'])}"
            for e in no_models
        ]
    )
    lines += ["", "### 타입 변환 실패", ""]
    lines += _bullets(
        [f"`{f['table']}` `{f['pk']}` {f['column']}: 「{f['value']}」" for f in failed]
    )
    lines += ["", "### 적재 차이 (빠진 PK · 남는 PK)", ""]
    lines += _bullets(
        [f"`notices` 빠진 PK `{k}`" for k in n["missing"]]
        + [f"`notices` 남는 PK `{k}`" for k in n["extra"]]
        + [f"`notice_models` 빠진 PK `{k}`" for k in m["missing"]]
        + [f"`notice_models` 남는 PK `{k}`" for k in m["extra"]]
    )
    lines += ["", "### raw 키 집합이 응답과 다른 행", ""]
    lines += _bullets(
        [f"`notices` `{k}`" for k in n["raw_diff"]]
        + [f"`notice_models` `{k}`" for k in m["raw_diff"]]
    )
    lines += ["", "### 명세 차이 (키 이름)", ""]
    for label, s in (("공고", spec_n), ("주택형", spec_m)):
        lines.append(
            f"- {label}: 응답 키 {s['response_count']}개 · swagger {s['spec_count']}개."
            f" 응답에만 있는 키: {', '.join(s['response_not_in_spec']) or '없다'}."
            f" swagger에만 있는 키: {', '.join(s['spec_not_in_response']) or '없다'}"
        )
    lines += ["", "### 재실행 비교", ""]
    prev = run.get("previous")
    if prev:
        lines += _table(
            ["", "이전 실행", "마지막 실행"],
            [
                ("실행 시각", prev["run_at"], run["run_at"]),
                ("`notices` 행 수", prev["notices_rows_after"], n["rows_after"]),
                ("`notice_models` 행 수", prev["models_rows_after"], m["rows_after"]),
                ("`notices` PK 집합 해시", prev["notices_pk_digest"][:12], n["pk_digest"][:12]),
                (
                    "`notice_models` PK 집합 해시",
                    prev["models_pk_digest"][:12],
                    m["pk_digest"][:12],
                ),
                ("`notices` 넣은 행", prev["notices_inserted"], n["inserted"]),
                ("`notice_models` 넣은 행", prev["models_inserted"], m["inserted"]),
            ],
        )
        lines.append("")
        lines.append("PK 집합 해시는 테이블 전체 PK를 정렬해 이어 붙인 문자열의 SHA-1 앞 12자리다.")
    else:
        lines.append("- 이전 실행이 없다")
    if d.get("notes"):
        lines += ["", "## 5. 메모", "", d["notes"].strip()]
    return "\n".join(lines) + "\n"


def main(argv=None, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(description="공고 수집 결과 리포트를 쓴다")
    ap.add_argument("--run", type=Path, default=RUN_PATH)
    ap.add_argument("--swagger", type=Path, default=SWAGGER_PATH)
    ap.add_argument("--notes", type=Path, default=NOTES_PATH)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)

    run_text = args.run.read_text(encoding="utf-8")
    secrets = notice._secrets(settings.data_go_kr_key) if settings.data_go_kr_key.strip() else []
    if any(s in run_text for s in secrets):
        print("실행 요약 JSON에 서비스 키가 들어 있다. 리포트를 쓰지 않는다", file=sys.stderr)
        return 1
    run = json.loads(run_text)
    swagger = json.loads(args.swagger.read_text(encoding="utf-8"))
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        data = gather(engine, run, swagger)
    finally:
        if own:
            engine.dispose()
    if args.notes.exists():
        data["notes"] = args.notes.read_text(encoding="utf-8")
    text = render(data)
    if any(s in text for s in secrets):
        print("리포트 본문에 서비스 키가 들어 있다. 쓰지 않는다", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"썼다: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
