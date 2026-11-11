"""#76 리포트 — 지표를 harness 함수 없이 따로 다시 센다 (설계 §3.5, 통과 기준 3)."""

import ast
import inspect
import json

from cheongyak_rag.eval import metrics, report


def line(
    gold,
    sys,
    *,
    axis="homeless",
    gold_cites=("제1조",),
    top5=("제1조",),
    cites=("제1조",),
    matched=True,
    error=None,
):
    return {
        "id": "g01",
        "notice_name": "공고A",
        "axis": axis,
        "query": f"{axis} 질의",
        "gold_verdict": gold,
        "gold_citations": list(gold_cites),
        "gold_reason": "정답 이유",
        "matched": matched,
        "cause": None if matched else "질의 문장이 다르다",
        "sys_verdict": sys,
        "sys_pre_verdict": sys,
        "sys_reason": "시스템 이유",
        "sys_citations": list(cites),
        "law_top5": list(top5) if matched else [],
        "faq_top3": [],
        "error": error,
        "usd": 0.0,
        "cached": True,
    }


ROWS = [
    line("NEED_INFO", "NEED_INFO"),
    line("NEED_INFO", "UNVERIFIABLE", axis="account", top5=("제9조",), cites=("제9조", "Q3")),
    line("INELIGIBLE", "ELIGIBLE", axis="account"),
    line("INELIGIBLE", "INELIGIBLE", axis="rewin", gold_cites=("제54조", "제2조")),
    line("ELIGIBLE", "NEED_INFO", axis="rewin", cites=()),
    line("ELIGIBLE", None, error="timeout", cites=(), top5=()),
    line("NEED_INFO", None, matched=False, cites=()),
]


def flat(m):
    out = {k: (v["num"], v["den"]) for k, v in m.items() if k != "judgment_accuracy"}
    acc = m["judgment_accuracy"]
    out["acc_total"] = (acc["total"]["num"], acc["total"]["den"])
    out.update({f"acc_{a}": (v["num"], v["den"]) for a, v in acc["axes"].items()})
    return out


def test_recompute_matches_harness():
    assert flat(report.recompute(ROWS)) == flat(metrics.compute(ROWS))


def test_report_does_not_import_the_harness_metrics():
    tree = ast.parse(inspect.getsource(report))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("eval.metrics" in i or i.endswith(".metrics") for i in imported)


def test_diff_counts_metrics_that_differ():
    harness = metrics.compute(ROWS)
    assert report.differing(harness, report.recompute(ROWS)) == []
    harness["hit_at_5"]["num"] += 1
    harness["judgment_accuracy"]["axes"]["rewin"]["den"] += 1
    assert report.differing(harness, report.recompute(ROWS)) == ["hit_at_5", "judgment_accuracy"]


def test_missing_metrics_are_those_without_value_or_zero_denominator():
    rows = [line("NEED_INFO", "NEED_INFO")]  # INELIGIBLE·ELIGIBLE 정답이 없다
    mine = report.recompute(rows)
    assert report.empty_metrics(mine) == ["fatal_error_rate", "unjustified_abstain"]


def test_zones():
    assert [report.zone_search(n) for n in (0, 1, 10, 11)] == [
        "통과",
        "다시 잰다",
        "다시 잰다",
        "미완",
    ]
    assert [report.zone_criteria(n) for n in (0, 1, 2, 3)] == [
        "통과",
        "다시 잰다",
        "다시 잰다",
        "미완",
    ]
    assert [report.zone_errors(n) for n in (0, 5, 11)] == ["통과", "다시 잰다", "미완"]
    assert report.zone_cost(3.0, False) == "통과"
    assert report.zone_cost(10.5, False) == "미완" and report.zone_cost(1.0, True) == "미완"
    assert report.zone_repro(0, True) == "통과"
    assert report.zone_repro(0, False) == "다시 잰다" and report.zone_repro(2, True) == "다시 잰다"


def test_render_has_required_sections():
    harness = {
        "model": "m",
        "stop": None,
        "usd": 1.5,
        "metrics": metrics.compute(ROWS),
        "counts": {**metrics.counts(ROWS), "unmatched_system_queries": 4},
        "first_run": {"run_at": "t1", "calls": 5, "usd": 1.5, "metrics": {}, "counts": {}},
        "second_run": None,
    }
    md = report.render(
        ROWS, harness, notes={"suspicious": [{"id": "g01", "query": "q", "reason": "r"}]}
    )
    for needle in (
        "## jw 기준",
        "청약공고 질의에 대한 검색을 완료하고",
        "## 지표 7개",
        "## 축별 판정 정확도",
        "## 정답 × 시스템 판정값",
        "## 치명오답 하위 질의",
        "## 실패 징후",
        "## 지표를 읽는 법",
        "## 정답 라벨이 의심스러운 것",
    ):
        assert needle in md, needle
    assert "공고A" in md and "시스템 이유" in md and "정답 이유" in md  # 치명오답 1건의 칸


def test_main_reads_run_dir(tmp_path):
    (tmp_path / "run.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ROWS), encoding="utf-8"
    )
    harness = {
        "model": "m",
        "stop": None,
        "usd": 0,
        "metrics": metrics.compute(ROWS),
        "counts": metrics.counts(ROWS),
        "first_run": None,
        "second_run": None,
    }
    (tmp_path / "metrics.json").write_text(json.dumps(harness), encoding="utf-8")
    out = tmp_path / "eval.md"
    assert report.main(["--run-dir", str(tmp_path), "--out", str(out)]) == 0
    assert out.exists()


def _harness(**kw):
    base = {
        "model": "m",
        "stop": None,
        "usd": 1.5,
        "metrics": metrics.compute(ROWS),
        "counts": {**metrics.counts(ROWS), "unmatched_system_queries": 0},
        "first_run": None,
        "second_run": None,
    }
    return {**base, **kw}


def _cost_row(md):
    row = next(x for x in md.splitlines() if x.startswith("| 4 첫 실행 비용"))
    return row.rsplit(" | ", 1)[0]  # 구간 조건 칸은 「미완」이 늘 들어 있어 뺀다


def test_cost_zone_when_first_run_stopped_on_budget():
    h = _harness(stop=["budget", "g07: 상한"], usage_total={"usd": 10.4})
    row = _cost_row(report.render(ROWS, h))
    assert "미완" in row and "10.4000" in row and "미측정" not in row


def test_cost_zone_ignores_a_later_stop_after_a_clean_first_run():
    first = {"run_at": "t1", "calls": 5, "usd": 1.5, "metrics": {}, "counts": {}}
    h = _harness(stop=["hard", "429"], first_run=first)
    row = _cost_row(report.render(ROWS, h))
    assert "통과" in row and "미완" not in row


def test_cost_zone_is_unmeasured_before_any_complete_first_run():
    assert "미측정" in _cost_row(report.render(ROWS, _harness()))
