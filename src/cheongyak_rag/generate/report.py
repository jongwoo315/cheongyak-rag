"""답 생성 리포트 (#139).

    python -m cheongyak_rag.generate.report

`runs/139/answers.jsonl` + `config.json`을 읽어 `docs/139-answer.md`를 쓴다. 첫 줄은 결론 한 문장.
구간 문구는 plan §실패 징후의 문장 그대로다.
"""

import argparse
import json
import random
import sys
from pathlib import Path

from cheongyak_rag.generate.evaluate import OUT_DIR
from cheongyak_rag.retrieval.chunk import law_chunks, load_law_rows
from cheongyak_rag.retrieval.golden import load_faq

DOCS_PATH = Path(__file__).resolve().parents[3] / "docs" / "139-answer.md"
SHOW_CHARS = 300
SAMPLE_N = 10


# ── 구간 판정 (plan §실패 징후) ───────────────────────────────────────────


def zone_failures(n: int) -> str:
    if n == 0:
        return "0건 통과"
    return "1~3건 문항 목록과 원인을 리포트에 적는다" if n <= 3 else "4건 이상 미완"


def zone_outside(v: float) -> str:
    if v <= 0.02:
        return "≤ 2% 정상"
    return "2~5% 목록을 리포트에" if v <= 0.05 else "> 5% 프롬프트 결함으로 보고 고친다"


def zone_golden_abstain(v: float) -> str:
    if v <= 0.10:
        return "≤ 10% 정상"
    if v <= 0.25:
        return "10~25% 검색 hit@5 여부로 갈라 원인을 리포트에"
    return "> 25% 실패 — 프롬프트가 너무 보수적이다. 고치고 다시 잰다"


def zone_ood(n: int) -> str:
    if n >= 9:
        return "9~10 정상"
    return "7~8 답한 문항과 답을 리포트에" if n >= 7 else "≤ 6 실패 — 근거 없는 답을 낸다"


def zone_precision(v: float) -> str:
    if v >= 0.6:
        return "≥ 0.6 정상"
    return (
        "0.3~0.6 틀린 인용 목록을 리포트에" if v >= 0.3 else "< 0.3 인용 결함 의심, 원인을 찾는다"
    )


def zone_calls(n: int) -> str:
    if n <= 140:
        return "≤ 140 정상 (133 + 재시도)"
    return "141~170 재시도 원인을 리포트에" if n <= 170 else "> 170 재시도 루프 결함"


def zone_usd(v: float) -> str:
    if v <= 3:
        return "≤ $3 정상"
    return "$3~6 질문당 토큰을 리포트에" if v < 6 else "$6에 이르면 실행이 멈춘다"


def zone_tokens(v: float) -> str:
    if v <= 8000:
        return "≤ 8,000 정상"
    return "8,000~15,000 긴 문맥 문항 목록" if v <= 15000 else "> 15,000 문맥 구성 결함"


def zone_second_calls(n: int) -> str:
    return "0회 정상" if n == 0 else "1회라도 있으면 캐시 결함"


def zone_latency(v: float) -> str:
    if v <= 15:
        return "p95 ≤ 15초 정상"
    return "15~30초 기록" if v <= 30 else "> 30초 원인을 리포트에"


def zone_leak(n: int) -> str:
    return "0 정상" if n == 0 else "1개 이상이면 버그"


# ── 지표 ────────────────────────────────────────────────────────────────


def _answered(r: dict) -> bool:
    return not r["abstain"] and not r["error"]


def precision(rows: list[dict], *, hit_only: bool = False) -> dict:
    """답한 golden 문항의 인용 조 중 정답 조 비율의 평균. 조 인용이 없는(FAQ만 인용) 문항은 뺀다."""
    vals, zero, faq_only = [], [], 0
    for r in rows:
        if r["set"] != "golden" or not _answered(r) or (hit_only and not r["retrieval_hit"]):
            continue
        laws = [c for c in r["citations"] if c.startswith("제")]
        if not laws:
            faq_only += 1
            continue
        p = sum(c in r["gold"] for c in laws) / len(laws)
        vals.append(p)
        if p == 0:
            zero.append(r)
    value = sum(vals) / len(vals) if vals else 0.0
    return {"value": value, "n": len(vals), "excluded_faq_only": faq_only, "zero": zero}


def metrics(rows: list[dict], cfg: dict) -> dict:
    golden = [r for r in rows if r["set"] == "golden"]
    ood = [r for r in rows if r["set"] == "ood"]
    failures = [r for r in rows if r["error"]]
    forced = [r for r in rows if r["forced_abstain"]]
    n_valid = sum(len(r["citations"]) for r in rows)
    n_invalid = sum(len(r["invalid_citations"]) for r in rows)
    g_abstain = [r for r in golden if r["abstain"] and not r["error"]]
    run = cfg["first_run"]
    earlier = cfg.get("earlier_runs", [])
    return {
        "failures": len(failures),
        "failure_rows": failures,
        "forced": len(forced),
        "forced_rows": forced,
        "signal1": len(failures) + len(forced),
        "outside_ratio": n_invalid / (n_valid + n_invalid) if n_valid + n_invalid else 0.0,
        "outside_rows": [r for r in rows if r["invalid_citations"]],
        "golden_n": len(golden),
        "golden_abstain": len(g_abstain),
        "golden_abstain_rows": g_abstain,
        "ood_abstain": sum(r["abstain"] and not r["error"] for r in ood),
        "ood_n": len(ood),
        "precision": precision(rows),
        "precision_hit": precision(rows, hit_only=True),
        "leak": sum(bool(r["self_faq_in_context"]) for r in rows),
        "calls": run["calls"] + sum(r["calls"] for r in earlier),
        "retries": run["retries"] + sum(r["retries"] for r in earlier),
        "earlier": len(earlier),
        "usd": sum(r["usd"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "avg_input": sum(r["input_tokens"] for r in rows) / len(rows) if rows else 0.0,
        "second_calls": cfg["second_run"]["calls"] if "second_run" in cfg else None,
    }


# ── 렌더 ────────────────────────────────────────────────────────────────


def _flat(text: str) -> str:
    return " ".join(text.split())


def _pct(n: int, d: int) -> str:
    return f"{n / d:.1%}" if d else "—"


def _cites(r: dict, law_text, faq_by_q: dict) -> list[str]:
    out = []
    for c in r["citations"]:
        if c.startswith("Q"):
            q = faq_by_q[int(c[1:])]["question"]
            out.append(f"- FAQ {c} · {_flat(q)}")
        else:
            head, _, body = law_text(c).partition("\n")
            out.append(f"- [{c}] {head} — {_flat(body)[:SHOW_CHARS]}")
    return out or ["- (없음)"]


def render(rows: list[dict], cfg: dict, law_text, faq_by_q: dict) -> str:
    m = metrics(rows, cfg)
    p, ph = m["precision"], m["precision_hit"]
    first = (
        f"생성 실패 {m['failures']}건 · 인용이 없어 abstain으로 바꾼 답 {m['forced']}건, "
        f"golden abstain {_pct(m['golden_abstain'], m['golden_n'])} "
        f"({m['golden_abstain']}/{m['golden_n']}), "
        f"범위 밖 abstain {m['ood_abstain']}/{m['ood_n']}, "
        f"인용 정밀도 {p['value']:.2f}, 총 ${m['usd']:.2f}."
    )
    run = cfg["first_run"]
    n2 = m["second_calls"]
    second = f"{n2}회" if n2 is not None else "두 번째 실행 아직 없음"
    table = [
        ("1", "생성 실패 + 인용 없어 abstain으로 바꾼 답",
         f"{m['failures']} + {m['forced']} = {m['signal1']}건", zone_failures(m["signal1"])),
        ("2", "문맥 밖 인용 비율", f"{m['outside_ratio']:.1%}", zone_outside(m["outside_ratio"])),
        ("3", "golden 최종 abstain 비율",
         f"{_pct(m['golden_abstain'], m['golden_n'])} ({m['golden_abstain']}/{m['golden_n']})",
         zone_golden_abstain(m["golden_abstain"] / m["golden_n"] if m["golden_n"] else 0)),
        ("4", "범위 밖 abstain", f"{m['ood_abstain']}/{m['ood_n']}", zone_ood(m["ood_abstain"])),
        ("5", "인용 정밀도 (baseline 없음 — 첫 측정)",
         f"{p['value']:.2f} (문항 {p['n']}, FAQ만 인용해 뺀 {p['excluded_faq_only']}); "
         f"검색 hit@5 문항만 {ph['value']:.2f} (문항 {ph['n']})", zone_precision(p["value"])),
        ("6a", "첫 실행 호출 수", f"{m['calls']} (재시도 {m['retries']})" + (
            f" · 실패 행을 이어 받기 전 {m['earlier']}회 실행 포함" if m["earlier"] else ""),
         zone_calls(m["calls"])),
        ("6b", "총 $", f"${m['usd']:.4f}", zone_usd(m["usd"])),
        ("6c", "질문당 입력 토큰 평균", f"{m['avg_input']:,.0f}", zone_tokens(m["avg_input"])),
        ("6d", "두 번째 실행 호출", second, zone_second_calls(n2) if n2 is not None else "—"),
        ("7", "지연 p95 (첫 호출, 캐시 안 탄 값)",
         f"p50 {run['latency_p50']:.1f}초 · p95 {run['latency_p95']:.1f}초",
         zone_latency(run["latency_p95"])),
        ("8", "자기 FAQ 쌍이 문맥에 들어간 문항", f"{m['leak']}", zone_leak(m["leak"])),
    ]  # fmt: skip
    out = [first, "", "# #139 답 생성 리포트", ""]
    out.append(
        f"모델 `{cfg['model']}` · 조 상위 {cfg['k']} + FAQ 상위 {cfg['faq_k']} · "
        f"질문 {cfg['questions']}개 (golden {m['golden_n']} + 범위 밖 {m['ood_n']})"
    )
    if run["stopped"]:
        out += ["", f"**실행이 멈췄다:** {run['stop_reason']}"]
    out += [
        "",
        "## 1. 지표",
        "",
        "| 징후 | 지표 | 측정값 | 해당 구간 |",
        "| --- | --- | --- | --- |",
    ]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in table]

    golden = [r for r in rows if r["set"] == "golden"]
    sample = random.Random(0).sample(golden, min(SAMPLE_N, len(golden)))
    out += ["", f"## 2. 표본 {len(sample)}문항 (golden, seed 0)", ""]
    for r in sample:
        faq_no = int(r["qid"].split("-")[1])
        flag = "예" if r["abstain"] else "아니오"
        out += [f"### {r['qid']} — {_flat(r['question'])}", ""]
        out += [f"- 생성 답 (abstain: {flag}): {_flat(r['answer']) or '(없음)'}"]
        if r["error"]:
            out += [f"- 생성 실패: {r['error']}"]
        out += ["- 인용:", *("  " + x for x in _cites(r, law_text, faq_by_q))]
        out += [f"- FAQ 공식 답 (Q{faq_no}): {_flat(faq_by_q[faq_no]['answer'])}"]
        out += [f"- 정답 조: {', '.join(r['gold'])}"]
        out += [
            f"- 검색 hit@5 (정답 조가 문맥에 있나): {'예' if r['retrieval_hit'] else '아니오'}",
            "",
        ]

    out += ["## 3. golden에서 abstain한 문항", ""]
    if m["golden_abstain_rows"]:
        out += [
            "| qid | 질문 | 모델이 쓴 이유 | 코드가 바꿈 | 검색 hit |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in m["golden_abstain_rows"]:
            out += [f"| {r['qid']} | {_flat(r['question'])} | {_flat(r['answer'])} | "
                    f"{'예' if r['forced_abstain'] else '아니오'} | "
                    f"{'예' if r['retrieval_hit'] else '아니오'} |"]  # fmt: skip
        hit = sum(bool(r["retrieval_hit"]) for r in m["golden_abstain_rows"])
        out += [
            "",
            f"검색 hit@5로 가르면: hit {hit}건 · hit 아님 {len(m['golden_abstain_rows']) - hit}건",
        ]
    else:
        out += ["없다."]
    if m["failure_rows"]:
        out += ["", "생성 실패 문항:", *(f"- {r['qid']}: {r['error']}" for r in m["failure_rows"])]

    out += ["", "## 4. 범위 밖 10문항", ""]
    for r in (r for r in rows if r["set"] == "ood"):
        verdict = "생성 실패" if r["error"] else ("abstain" if r["abstain"] else "답함")
        out += [f"- {r['qid']} {_flat(r['question'])} → **{verdict}**: {_flat(r['answer'])}"]

    out += ["", "## 5. 문맥 밖 인용과 틀린 인용", "", "문맥 밖 인용:"]
    out += [f"- {r['qid']}: {', '.join(r['invalid_citations'])}" for r in m["outside_rows"]] or [
        "- 없다"
    ]
    out += ["", "틀린 인용 (조 인용이 모두 정답 조가 아닌 문항):"]
    out += [f"- {r['qid']}: 인용 {', '.join(r['citations'])} · 정답 {', '.join(r['gold'])}"
            for r in p["zero"]] or ["- 없다"]  # fmt: skip

    out += ["", "## 6. 비용", ""]
    out += [f"- 호출 수 {m['calls']} (재시도 {m['retries']}), 캐시 적중 {run['cache_hits']}"
            " (이 실행 전에 같은 입력으로 이미 부른 질문)",
            f"- 토큰: 입력 {m['input_tokens']:,} · 출력 {m['output_tokens']:,}",
            f"- ${m['usd']:.4f} (예산 상한 ${cfg['budget_usd']})",
            f"- 지연: p50 {run['latency_p50']:.1f}초 · p95 {run['latency_p95']:.1f}초",
            f"- 두 번째 실행 호출: {second}"]  # fmt: skip
    if m["avg_input"] > 8000:
        big = [r["qid"] for r in rows if r["input_tokens"] > 8000]
        out += [f"- 입력 8,000 토큰 초과 문항: {', '.join(big)}"]
    if m["retries"]:
        out += [
            f"- 재시도 {m['retries']}회는 429(요청 한도)·5xx·연결 오류 뒤 대기하고 다시 보낸 것이다"
        ]
    return "\n".join(out) + "\n"


def main(
    argv: list[str] | None = None,
    *,
    out_dir: Path = OUT_DIR,
    docs_path: Path = DOCS_PATH,
    law_rows=None,
    faq_rows=None,
) -> int:
    argparse.ArgumentParser(prog="cheongyak_rag.generate.report").parse_args(argv)
    try:
        rows = [
            json.loads(x)
            for x in (out_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
            if x
        ]
        cfg = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        print(f"{e}. 먼저 python -m cheongyak_rag.generate.evaluate", file=sys.stderr)
        return 1
    law = {c.label: c.text for c in law_chunks(law_rows or load_law_rows(), "article")}
    faq_by_q = {r["q_no"]: r for r in (faq_rows or load_faq())}
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(render(rows, cfg, law.__getitem__, faq_by_q), encoding="utf-8")
    print(f"→ {docs_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
