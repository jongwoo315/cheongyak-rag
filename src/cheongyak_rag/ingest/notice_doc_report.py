"""공고문 수집 결과를 `docs/72-notice-doc.md`로 쓴다 (#72).

수집 실행이 남긴 `runs/72/last_run.json`·`run1.json`, 목록 `data/raw/notices/manifest.jsonl`,
DB `notices`(공고 이름)를 읽는다. 청약홈을 부르지 않는다.
구간 문구는 plan §실패 징후의 문장 그대로다.
"""

import argparse
import json
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings
from cheongyak_rag.ingest.notice_doc import NOTICE_DIR, RESULTS

RUN_PATH = Path("runs/72/last_run.json")
RUN1_PATH = Path("runs/72/run1.json")
NOTES_PATH = Path("runs/72/notes.md")
MANIFEST_PATH = NOTICE_DIR / "manifest.jsonl"
OUT_PATH = Path("docs/72-notice-doc.md")

# 착수 때(2026-11-09) 실측한 링크 없는 공고 — LH 공공분양·신혼희망타운 10건
LH_NO_LINK = (
    "2026000409",
    "2026000414",
    "2026000416",
    "2026000531",
    "2026820006",
    "2026820008",
    "2026820009",
    "2026820010",
    "2026820011",
    "2026820012",
)
EXPECTED_WITH_LINK = 74
MEANING = {
    "pdf": "공고문을 받았고 PDF로 열린다",
    "hwp": "받은 파일이 HWP·HWPX라 격리했다",
    "other": "받은 파일이 PDF·HWP가 아니라 격리했다",
    "no_link": "상세 페이지에 공고문 링크가 없다(지금은 LH 10건)",
    "error": "받기가 실패했거나(HTTP·시간 초과·크기 초과), PDF라는데 안 열린다",
}
_SEVERITY = {"no_link": -1, "pdf": 0, "hwp": 1, "other": 2, "error": 3}


# ── 구간 ─────────────────────────────────────────────────────────────────


def error_band(n: int) -> str:
    if n == 0:
        return "0 → 통과"
    if n <= 3:
        return (
            "1~3 → 오류 공고마다 URL·HTTP 상태·문구를 리포트에 적고, 그 공고만 한 번 더 받는다."
            " 두 번째에 받아지면 두 값을 다 적는다(일시 오류). 그래도 실패하면 원인을 적고 끝낸다"
        )
    return (
        "4 이상 → 미완. 원인을 고치고 다시 잰다."
        " 고칠 수 없는 원인(사이트 차단 등)이면 그 사실과 값을 리포트·PR 본문 맨 위에 적는다"
    )


def no_link_band(outside: int) -> str:
    if outside == 0:
        return "0 → 통과"
    if outside <= 3:
        return "1~3 → 리포트에 적는다"
    return "4 이상 → 링크 찾는 코드를 고치고 다시 잰다"


# ── 집계 ─────────────────────────────────────────────────────────────────


def _key(r: dict) -> str:
    return f"{r['house_manage_no']}/{r['pblanc_no']}"


def notice_results(rows: list[dict]) -> dict[str, str]:
    """목록 줄에서 공고마다 결과 하나를 구한다. 가장 나쁜 줄을 따르고, 링크 없음뿐이면 `no_link`."""
    out: dict[str, str] = {}
    for r in rows:
        k = _key(r)
        if k not in out or _SEVERITY[r["result"]] > _SEVERITY[out[k]]:
            out[k] = r["result"]
    return out


def _count(results: dict[str, str]) -> dict[str, int]:
    return {v: sum(1 for x in results.values() if x == v) for v in RESULTS}


def _cell(v) -> str:
    return "—" if v is None else str(v).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[tuple]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _bullets(items: list[str]) -> list[str]:
    return [f"- {i}" for i in items] or ["- 없다"]


def _pct(a: int, b: int) -> str:
    return "—" if b == 0 else f"{a / b * 100:.1f}%"


def _who(d: dict, r: dict) -> str:
    k = _key(r)
    return f"`{k}` {d['names'].get(k, '(DB에 이름 없음)')}"


# ── 출력 ─────────────────────────────────────────────────────────────────


def render(d: dict) -> str:
    run, run1, rows = d["run"], d["run1"], d["rows"]
    res = run["results"]
    quarantine = res["hwp"] + res["other"]
    outside = [k for k in run["no_link_notices"] if k.split("/")[0] not in LH_NO_LINK]
    zero_text = [r for r in rows if r["result"] == "pdf" and r["text_chars"] == 0]
    mismatch = [r for r in rows if r.get("ext_mismatch")]
    link_diff = run["with_link"] - EXPECTED_WITH_LINK

    new_ok = run["new_downloads"] == 0
    same_results = run["results"] == run1["results"]
    if new_ok and same_results:
        rerun_line = "새 다운로드 0건이고 결과별 공고 수가 첫 실행과 같다."
    else:
        bad = []
        if not new_ok:
            bad.append(f"새 다운로드가 0이 아니다({run['new_downloads']}건)")
        if not same_results:
            bad.append("결과별 공고 수가 첫 실행과 다르다")
        rerun_line = " · ".join(bad) + "."

    lines = [
        f"공고문 링크가 있는 공고 {run['with_link']}건 중 오류는 {run['errors']}건이다"
        f"(PDF {res['pdf']}건 · 격리 {quarantine}건[HWP {res['hwp']}·그 밖 {res['other']}]"
        f" · 링크 없음 {res['no_link']}건).",
        "",
        "# #72 공고문 수집 결과",
        "",
        f"실행 {run['started_at']} ~ {run['ended_at']} · 공고 {run['notices']}건"
        f" · 걸린 시간 {run['elapsed_sec']}초",
        "",
        "## 1. 지표",
        "",
    ]
    if link_diff:
        link_cell = (
            f"착수 때 실측 {EXPECTED_WITH_LINK}건과 차이 {link_diff:+d}건."
            " 이유는 아래 메모에 적는다"
        )
    else:
        link_cell = f"착수 때 실측 {EXPECTED_WITH_LINK}건과 같다"
    lines += _table(
        ["지표", "측정값", "해당 구간 (plan 문구)"],
        [
            (
                "1. jw 기준 — 공고문을 오류 없이 받았나",
                f"링크 있는 공고 {run['with_link']}건 중 error {run['errors']}건."
                f" 링크 있는 공고 수는 {link_cell}",
                error_band(run["errors"]),
            ),
            (
                "2. 링크를 못 찾은 것이 사이트 구조가 바뀐 탓인가",
                f"LH 10건 밖 no_link {len(outside)}건",
                no_link_band(len(outside)),
            ),
            (
                "3. 텍스트 없는 PDF(스캔본 의심)",
                f"{len(zero_text)}건 (baseline 없음 — 첫 측정)",
                "오류가 아니다. 건수와 공고 번호만 적는다",
            ),
            (
                "4. HWP 비율",
                f"hwp {res['hwp']}건 · other {res['other']}건"
                f" (링크 있는 공고 {run['with_link']}건 중 {_pct(quarantine, run['with_link'])},"
                " baseline 없음 — 첫 측정)",
                "오류가 아니다. 건수만 적는다",
            ),
        ],
    )

    lines += ["", "## 2. 결과 5개", ""]
    lines += _table(
        ["값", "뜻", "공고 수"],
        [(f"`{v}`", MEANING[v], res[v]) for v in RESULTS],
    )

    lines += ["", "## 3. 목록", "", "### 오류 공고", ""]
    errs = [r for r in rows if r["result"] == "error"]
    lines += _bullets(
        [f"{_who(d, r)} — {r['url'] or '상세 페이지'} — {_cell(r['error'])}" for r in errs]
    )
    lines += ["", "### 격리 공고 (HWP·그 밖)", ""]
    lines += _bullets(
        [
            f"{_who(d, r)} — {r['result']} · 헤더 파일 이름 {_cell(r['header_filename'])}"
            f" · 앞 바이트 판별 {r['magic_ext']} · {r['bytes']}바이트"
            for r in rows
            if r["result"] in ("hwp", "other")
        ]
    )
    lines += ["", "### 링크 없음 공고", ""]
    lines.append(
        f"LH 10건 밖 링크 없음: {len(outside)}건"
        + (" — " + ", ".join(f"`{k}`" for k in outside) if outside else "")
    )
    lines.append("")
    lines += _bullets(
        [f"{_who(d, r)} — {_cell(r['note'])}" for r in rows if r["result"] == "no_link"]
    )
    lines += ["", "### 텍스트 없는 PDF", ""]
    lines += _bullets([f"{_who(d, r)} — {r['pages']}쪽" for r in zero_text])
    lines += ["", "### 확장자 어긋남 (헤더 파일 이름 ≠ 앞 바이트)", ""]
    lines += _bullets(
        [
            f"{_who(d, r)} — 헤더 {_cell(r['header_filename'])}({_cell(r['header_ext'])})"
            f" ≠ 앞 바이트 {r['magic_ext']}"
            for r in mismatch
        ]
    )

    lines += ["", "## 4. 재실행 결과", ""]
    lines += _table(
        ["", "첫 실행", "두 번째 실행"],
        [
            ("시작 시각", run1["started_at"], run["started_at"]),
            ("새 다운로드", run1["new_downloads"], run["new_downloads"]),
            ("받은 바이트", run1["downloaded_bytes"], run["downloaded_bytes"]),
            ("걸린 시간(초)", run1["elapsed_sec"], run["elapsed_sec"]),
            *[(f"공고 수 `{v}`", run1["results"][v], run["results"][v]) for v in RESULTS],
        ],
    )
    lines += ["", rerun_line]
    if d.get("notes"):
        lines += ["", "## 5. 메모", "", d["notes"].strip()]
    return "\n".join(lines) + "\n"


# ── 실행 ─────────────────────────────────────────────────────────────────


def _names(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        return {
            f"{hm}/{pb}": nm
            for hm, pb, nm in conn.execute(
                sa.text("SELECT house_manage_no, pblanc_no, house_nm FROM notices")
            )
        }


def main(argv=None, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(description="공고문 수집 결과 리포트를 쓴다")
    ap.add_argument("--run", type=Path, default=RUN_PATH)
    ap.add_argument("--run1", type=Path, default=RUN1_PATH)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--notes", type=Path, default=NOTES_PATH)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)

    run = json.loads(args.run.read_text(encoding="utf-8"))
    run1 = json.loads(args.run1.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 실행이 실패한 뒤에는 last_run.json이 이전 실행의 것이다.
    # 목록과 안 맞는데 쓰면 지난 결과가 지금 것처럼 나온다
    derived = _count(notice_results(rows))
    if derived != run["results"] or sum(derived.values()) != run["notices"]:
        print(
            f"실행 요약이 목록과 맞지 않는다: 요약 {run['results']} ≠ 목록 {derived}."
            " 수집을 다시 돌릴 것",
            file=sys.stderr,
        )
        return 1
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        names = _names(engine)
    finally:
        if own:
            engine.dispose()
    notes = args.notes.read_text(encoding="utf-8") if args.notes.exists() else None
    text = render({"run": run, "run1": run1, "rows": rows, "names": names, "notes": notes})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"썼다: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
