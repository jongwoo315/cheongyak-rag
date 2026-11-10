"""골든셋 리포트(`docs/75-golden.md`)와 jw 표본 검토 파일(`runs/75/review-sample.md`)을 쓴다 (#75).

    python -m cheongyak_rag.golden.report

입력은 `runs/75/`의 `golden.jsonl`·`notices.json`·`second.jsonl`·`disagreements.jsonl`·
`measure.json`이다.
`measure.json`은 고치기 전에 처음 잰 값(글자 대조, 따로 붙인 라벨 일치율)을 적어 둔 것이다.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

from cheongyak_rag.golden.check import PROFILE_FIELDS, VERDICTS

RUNS = Path("runs/75")
DOC = Path("docs/75-golden.md")
SAMPLE = RUNS / "review-sample.md"
SAMPLE_SEED = 75
SAMPLE_SIZE = 20
SAMPLE_MIN_INELIGIBLE = 5


def band_agreement(v_ratio: float, c_ratio: float) -> str:
    if max(v_ratio, c_ratio) > 0.15:
        return "미완"
    return "다시 잰다" if max(v_ratio, c_ratio) > 0.05 else "통과"


def band_quote(n: int) -> str:
    if n == 0:
        return "통과"
    return (
        "1~10: 구절을 고치고 다시 대조"
        if n <= 10
        else "11 이상: 옮기는 방식을 의심하고 전부 다시 대조"
    )


def band_ineligible(n: int, axes: int) -> str:
    return "통과" if n >= 30 and axes >= 4 else "프로필을 다시 짜 채운다"


def band_rule_null(null: int, total: int) -> str:
    return "통과" if total and null / total <= 0.10 else "라벨 규칙에 그 경우를 더하고 다시 붙인다"


# ── jw 표본 검토 ─────────────────────────────────────────────────────────


def pick_sample(rows: list[dict], *, seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE):
    """판정값별로 고르게 `size`개를 시드 고정 무작위로 뽑는다. [(문항, 라벨)]."""
    pools: dict[str, list] = {v: [] for v in VERDICTS}
    for r in rows:
        for lb in r["labels"]:
            pools[lb["verdict"]].append((r, lb))
    present = [v for v in VERDICTS if pools[v]]
    quota = {v: size // len(present) for v in present}
    # 나머지는 INELIGIBLE부터 한 개씩 얹는다(INELIGIBLE 5개 이상을 지키려고)
    order = sorted(present, key=lambda v: v != "INELIGIBLE")
    for v in order[: size - sum(quota.values())]:
        quota[v] += 1
    rng = random.Random(seed)
    out = []
    for v in present:
        out += rng.sample(pools[v], min(quota[v], len(pools[v])))
    return out


def _profile_text(profile: dict) -> str:
    filled = [f"{k}={profile[k]}" for k in PROFILE_FIELDS if profile.get(k) is not None]
    return ", ".join(filled) if filled else "(15칸 전부 비었다)"


def render_sample(rows: list[dict], picked) -> str:
    out = [
        "# jw 표본 검토 — 정답 라벨 20개",
        "",
        f"시드 {SAMPLE_SEED} 무작위. 판정값별로 고르게 뽑았다(없는 판정값은 제외). 항목마다 "
        "맞음/틀림과 메모를 적는다.",
        "",
    ]
    for i, (r, lb) in enumerate(picked, 1):
        out += [
            f"## {i}. {r['id']} · {r['notice_name']}",
            "",
            f"- 프로필({r['profile_kind']}): {_profile_text(r['profile'])}",
            f"- 하위 질의: {lb['query']}",
            f"- 정답 라벨: {lb['verdict']} (규칙 {lb['rule'] or '없음'})",
            f"- 이유: {lb['reason']}",
            "- 정답 근거 조문 구절:",
        ]
        out += [f"  - {k}: 「{v}」" for k, v in lb["article_quotes"].items()]
        if lb["notice_evidence"]:
            out.append("- 공고문 근거:")
            out += [f"  - {e['page']}쪽: 「{e['quote']}」" for e in lb["notice_evidence"]]
        else:
            out.append("- 공고문 근거: 없음")
        out += ["- 맞음/틀림:", "- 메모:", ""]
    return "\n".join(out)


# ── 리포트 ───────────────────────────────────────────────────────────────

AXIS_ORDER = (
    "homeless",
    "account",
    "residence",
    "income_asset",
    "rewin",
    "householder",
    "special_type",
)


def _table(head: list[str], body: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return out + [""]


def _pct(x: float) -> str:
    return f"{x:.1%}"


def render_report(rows, notices, measure, *, disagreements, second_rows) -> str:
    labels = [lb for r in rows for lb in r["labels"]]
    verdicts = Counter(lb["verdict"] for lb in labels)
    inel = [lb for lb in labels if lb["verdict"] == "INELIGIBLE"]
    inel_axes = sorted({lb["axis"] for lb in inel})
    null_rules = [(r["id"], lb) for r in rows for lb in r["labels"] if lb["rule"] is None]
    q = measure["quote_mismatch"]
    ag = measure.get("agreement_first")
    ag2 = measure.get("agreement_second")
    n_notices = len({r["house_manage_no"] for r in rows})
    ag_band = band_agreement(ag["verdict_diff_ratio"], ag["citation_diff_ratio"]) if ag else "-"
    ag_text = (
        f"따로 붙인 라벨과 판정값 불일치 {_pct(ag['verdict_diff_ratio'])}·조 불일치 "
        f"{_pct(ag['citation_diff_ratio'])}({ag_band})"
        if ag
        else "따로 붙인 라벨 일치율은 아직 재지 않았다"
    )
    out = [
        f"골든셋은 공고 {n_notices}건 {len(rows)}문항에 정답 라벨 {len(labels)}개를 붙였고, "
        f"글자 대조에서 어긋난 구절은 처음 {q['first']}개·고친 뒤 {q['after_fix']}개이며 "
        f"{ag_text}.",
        "",
        "## 공고 20건",
        "",
    ]
    by_no = Counter(r["house_manage_no"] for r in rows)
    body = []
    for n in notices:
        body.append([
            n["house_manage_no"], n["name"], n.get("area") or "", n["as_of"], len(n["axes"]),
            ", ".join(n["types"]) or "없음", ", ".join(n.get("flags", [])) or "없음",
            n.get("pages", ""), "고정" if n.get("fixed") else "",
            by_no.get(n["house_manage_no"], 0),
        ])  # fmt: skip
    out += _table(
        [
            "관리번호",
            "공고명",
            "지역",
            "모집공고일",
            "켜진 축",
            "특별공급 유형",
            "DB 규제 표시",
            "쪽수",
            "고른 방식",
            "문항",
        ],
        body,
    )
    out += ["## 프로필 종류별 문항 수", ""]
    kinds = Counter(r["profile_kind"] for r in rows)
    out += _table(
        ["프로필 종류", "문항 수"], [[k, kinds.get(k, 0)] for k in ("full", "partial", "empty")]
    )
    out += ["## 축별·판정값별 라벨 수", ""]
    grid = Counter((lb["axis"], lb["verdict"]) for lb in labels)
    body = [
        [a, *(grid.get((a, v), 0) for v in VERDICTS), sum(grid.get((a, v), 0) for v in VERDICTS)]
        for a in AXIS_ORDER
    ]
    body.append(["합계", *(verdicts.get(v, 0) for v in VERDICTS), len(labels)])
    out += _table(["축", *VERDICTS, "합계"], body)
    zero = [v for v in VERDICTS if verdicts.get(v, 0) == 0]
    if zero:
        out += [f"{'·'.join(zero)}은 라벨이 0개다. 억지로 만들지 않았다.", ""]
    out += [
        "## 글자 대조",
        "",
        f"- 처음 값: 어긋난 구절 {q['first']}개 ({band_quote(q['first'])})",
        f"- 고친 뒤 값: 어긋난 구절 {q['after_fix']}개",
        "- 대상: 정답 근거 조문 구절(MST 286965 `chunks` 본문), 공고문 근거 구절(PDF 그 쪽 글자), "
        "공고문 사실 구절. 공백만 합쳐 비교했고 존재하지 않는 조 라벨도 센다.",
        "",
        "## 따로 붙인 라벨과의 일치",
        "",
    ]
    if ag:
        out += _table(
            ["측정", "라벨", "판정값 불일치", "비율", "조 불일치", "비율", "구간"],
            [[
                "처음", ag["labels"], ag["verdict_diff"], _pct(ag["verdict_diff_ratio"]),
                ag["citation_diff"], _pct(ag["citation_diff_ratio"]),
                band_agreement(ag["verdict_diff_ratio"], ag["citation_diff_ratio"]),
            ]] + ([[
                "두 번째", ag2["labels"], ag2["verdict_diff"], _pct(ag2["verdict_diff_ratio"]),
                ag2["citation_diff"], _pct(ag2["citation_diff_ratio"]),
                band_agreement(ag2["verdict_diff_ratio"], ag2["citation_diff_ratio"]),
            ]] if ag2 else []),
        )  # fmt: skip
        out += ["축마다 나눈 값(처음):", ""]
        out += _table(
            ["축", "라벨", "판정값 불일치", "조 불일치"],
            [
                [a, v["labels"], v["verdict_diff"], v["citation_diff"]]
                for a, v in sorted(ag["by_axis"].items())
            ],
        )
    out += [f"어긋난 라벨 {len(disagreements)}개의 처리:", ""]
    if disagreements:
        out += _table(
            ["문항", "축", "첫 라벨", "따로 붙인 라벨", "맞은 쪽", "고쳤나", "이유"],
            [[
                d["id"], d["axis"], f"{d['first_verdict']} {d['first_citations']}",
                f"{d['second_verdict']} {d['second_citations']}", d["decision"],
                "고침" if d["fixed"] else "안 고침", d["reason"],
            ] for d in disagreements],
        )  # fmt: skip
    else:
        out += ["어긋난 라벨이 없다.", ""]
    out += [
        "한계: 두 쪽 다 Claude라 같은 잘못을 같이 할 수 있다. "
        "일치율이 높아도 맞았다는 증거는 아니다. "
        "사람이 원문으로 확인하는 자리는 게이트의 jw 표본 검토(`runs/75/review-sample.md`)다.",
        "",
        "## 공고문·DB 규제 표시 어긋남",
        "",
        "판정 대상이 아니다. 공고 수와 칸만 적는다(baseline 없음 — 첫 측정).",
        "",
    ]
    mism = [(n, m) for n in notices for m in n.get("db_mismatch", [])]
    silent = [(n, m) for n in notices for m in n.get("db_silent", [])]
    n_mism = len({n["house_manage_no"] for n, _ in mism})
    out += [f"- 공고문과 DB가 다르게 적은 칸: 공고 {n_mism}건 · {len(mism)}칸", ""]
    out += _table(
        ["관리번호", "공고명", "칸", "공고문", "DB", "쪽"],
        [
            [n["house_manage_no"], n["name"], m["칸"], m["공고문"], m["db"], m["page"]]
            for n, m in mism
        ],
    )
    n_silent = len({n["house_manage_no"] for n, _ in silent})
    out += [f"- 공고문에 언급이 없는 칸(DB는 참): 공고 {n_silent}건 · {len(silent)}칸", ""]
    out += _table(
        ["관리번호", "공고명", "칸", "DB"],
        [[n["house_manage_no"], n["name"], m["칸"], m["db"]] for n, m in silent],
    )
    out += ["## 규칙으로 안 정해진 라벨", ""]
    if null_rules:
        out += _table(
            ["문항", "축", "판정값", "이유"],
            [[i, lb["axis"], lb["verdict"], lb["rule_note"]] for i, lb in null_rules],
        )
    else:
        out += ["`rule`이 null인 라벨이 없다.", ""]
    ok_ratio = len(null_rules) / len(labels) if labels else 0
    out += [
        "## 실패 징후별 측정값과 구간",
        "",
        *_table(
            ["징후", "측정값", "구간"],
            [
                [
                    1,
                    ag_text,
                    band_agreement(ag["verdict_diff_ratio"], ag["citation_diff_ratio"])
                    if ag
                    else "-",
                ],
                [
                    2,
                    f"어긋난 구절 처음 {q['first']}개·고친 뒤 {q['after_fix']}개",
                    band_quote(q["first"]),
                ],
                [
                    3,
                    f"INELIGIBLE {len(inel)}개 · {len(inel_axes)}개 축 {inel_axes}",
                    band_ineligible(len(inel), len(inel_axes)),
                ],
                [
                    4,
                    f"rule null {len(null_rules)}개 ({_pct(ok_ratio)})",
                    band_rule_null(len(null_rules), len(labels)),
                ],
                [5, f"공고문과 DB가 다른 칸 {len(mism)}칸", "적기만 한다"],
                [6, " · ".join(f"{v} {verdicts.get(v, 0)}" for v in VERDICTS), "적기만 한다"],
            ],
        ),
    ]
    return "\n".join(out)


def _load(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> int:
    rows = _load(RUNS / "golden.jsonl")
    notices = json.loads((RUNS / "notices.json").read_text(encoding="utf-8"))["notices"]
    measure = json.loads((RUNS / "measure.json").read_text(encoding="utf-8"))
    second = _load(RUNS / "second.jsonl") if (RUNS / "second.jsonl").exists() else []
    dis_path = RUNS / "disagreements.jsonl"
    disagreements = _load(dis_path) if dis_path.exists() else []
    DOC.write_text(
        render_report(rows, notices, measure, disagreements=disagreements, second_rows=second)
        + "\n",
        encoding="utf-8",
    )
    SAMPLE.write_text(render_sample(rows, pick_sample(rows)) + "\n", encoding="utf-8")
    print(f"{DOC} · {SAMPLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
