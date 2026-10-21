import json
import random

import pytest

from cheongyak_rag.generate import report as rp


def _row(qid, kind="golden", *, abstain=False, cites=("제2조",), gold=("제2조",), **kw):
    base = {
        "qid": qid,
        "set": kind,
        "question": f"질문 {qid}",
        "abstain": abstain,
        "forced_abstain": False,
        "answer": f"답 {qid}",
        "citations": list(cites),
        "invalid_citations": [],
        "context_labels": ["제2조", "제3조", "Q1"],
        "input_tokens": 1000,
        "output_tokens": 100,
        "usd": 0.001,
        "gold": list(gold) if kind == "golden" else [],
        "retrieval_hit": True if kind == "golden" else None,
        "self_faq_in_context": False,
        "error": None,
    }
    return base | kw


def _run(**kw):
    base = {
        "calls": 133, "retries": 0, "cache_hits": 0, "failures": 0, "forced_abstain": 0,
        "input_tokens": 133_000, "output_tokens": 13_300, "usd": 0.5, "usd_new": 0.5,
        "latency_p50": 3.0, "latency_p95": 8.0, "stopped": False, "stopped_at": None,
        "stop_reason": None,
    }  # fmt: skip
    return base | kw


def _cfg(first=None, second=None):
    cfg = {
        "model": "gpt-5.4-mini", "k": 5, "faq_k": 3, "questions": 133, "budget_usd": 6,
        "first_run": first or _run(),
    }  # fmt: skip
    return cfg | ({"second_run": second} if second else {})


def _rows(n_golden=20, n_ood=10, **kw):
    g = [_row(f"faq-{i}", **kw) for i in range(1, n_golden + 1)]
    o = [_row(f"ood-{i}", "ood", abstain=True, cites=()) for i in range(1, n_ood + 1)]
    return g + o


@pytest.mark.parametrize(
    ("fn", "value", "zone"),
    [
        (rp.zone_failures, 0, "통과"), (rp.zone_failures, 2, "목록"), (rp.zone_failures, 4, "미완"),
        (rp.zone_outside, 0.02, "정상"), (rp.zone_outside, 0.03, "목록"),
        (rp.zone_outside, 0.06, "프롬프트 결함"),
        (rp.zone_golden_abstain, 0.10, "정상"), (rp.zone_golden_abstain, 0.2, "검색 hit@5"),
        (rp.zone_golden_abstain, 0.26, "실패"),
        (rp.zone_ood, 10, "정상"), (rp.zone_ood, 9, "정상"), (rp.zone_ood, 8, "답한 문항"),
        (rp.zone_ood, 6, "실패"),
        (rp.zone_precision, 0.6, "정상"), (rp.zone_precision, 0.5, "틀린 인용 목록"),
        (rp.zone_precision, 0.29, "인용 결함 의심"),
        (rp.zone_calls, 140, "정상"), (rp.zone_calls, 150, "재시도 원인"),
        (rp.zone_calls, 171, "재시도 루프 결함"),
        (rp.zone_usd, 3.0, "정상"), (rp.zone_usd, 4.0, "질문당 토큰"), (rp.zone_usd, 6.0, "멈춘다"),
        (rp.zone_tokens, 8000, "정상"), (rp.zone_tokens, 9000, "긴 문맥"),
        (rp.zone_tokens, 15001, "문맥 구성 결함"),
        (rp.zone_second_calls, 0, "정상"), (rp.zone_second_calls, 1, "캐시 결함"),
        (rp.zone_latency, 15.0, "정상"), (rp.zone_latency, 20.0, "기록"),
        (rp.zone_latency, 31.0, "원인"),
        (rp.zone_leak, 0, "정상"), (rp.zone_leak, 1, "버그"),
    ],
)  # fmt: skip
def test_zones_follow_plan_boundaries(fn, value, zone):
    assert zone in fn(value)


def test_precision_counts_only_answered_rows_with_law_citation():
    rows = [
        _row("faq-1", cites=("제2조", "제3조"), gold=("제2조",)),  # 0.5
        _row("faq-2", cites=("제2조",), gold=("제2조",)),  # 1.0
        _row("faq-3", cites=("Q1",), gold=("제2조",)),  # 조 인용 없음 → 뺀다
        _row("faq-4", abstain=True, cites=()),  # 답 안 함 → 뺀다
        _row("faq-5", cites=("제3조",), gold=("제2조",), retrieval_hit=False),  # 0.0
    ]
    p = rp.precision(rows)
    assert p["value"] == pytest.approx(0.5) and p["n"] == 3 and p["excluded_faq_only"] == 1
    hit_only = rp.precision(rows, hit_only=True)
    assert hit_only["value"] == pytest.approx(0.75) and hit_only["n"] == 2
    assert [r["qid"] for r in p["zero"]] == ["faq-5"]


def test_metrics_exclude_errors_from_abstain():
    rows = _rows(n_golden=10)
    rows[0] = _row("faq-1", abstain=True, cites=(), error="JSON 파싱 실패")
    rows[1] = _row("faq-2", abstain=True, cites=(), forced_abstain=True)
    m = rp.metrics(rows, _cfg())
    assert m["failures"] == 1 and m["forced"] == 1 and m["signal1"] == 2
    assert m["golden_abstain"] == 1 and m["golden_n"] == 10
    assert m["ood_abstain"] == 10


def test_outside_ratio_uses_all_citations():
    rows = _rows(n_golden=2)
    rows[0]["invalid_citations"] = ["제99조"]
    m = rp.metrics(rows, _cfg())
    assert m["outside_ratio"] == pytest.approx(1 / 3)  # 유효 2 + 무효 1


FAQ_ROWS = [
    {"q_no": i, "question": f"FAQ 질문 {i}", "answer": f"FAQ 공식 답 {i}"} for i in range(1, 30)
]


def _render(rows=None, cfg=None):
    rows = rows or _rows()
    law_text = lambda label: f"{label}(제목)\n" + "가" * 400  # noqa: E731
    return rp.render(rows, cfg or _cfg(), law_text, {r["q_no"]: r for r in FAQ_ROWS})


def test_first_line_is_one_conclusion_sentence():
    first = _render().splitlines()[0]
    for part in ["생성 실패", "golden abstain", "범위 밖 abstain", "인용 정밀도", "$"]:
        assert part in first
    assert first.endswith(".") and "\n" not in first


def test_sample_is_seed_zero_ten_with_side_by_side_material():
    rows = _rows(n_golden=20)
    text = _render(rows)
    golden = [r for r in rows if r["set"] == "golden"]
    expect = random.Random(0).sample(golden, 10)
    section = text.split("## 2.")[1].split("## 3.")[0]
    assert section.count("### ") == 10
    for r in expect:
        assert r["qid"] in section
    one = expect[0]
    n = int(one["qid"].split("-")[1])
    for needle in [one["question"], one["answer"], f"FAQ 공식 답 {n}", "정답 조", "검색 hit"]:
        assert needle in section
    assert "가" * 300 in section and "가" * 301 not in section  # 인용 조 원문은 앞 300자


def test_abstain_list_and_ood_sections():
    rows = _rows(n_golden=5)
    rows[0] = _row("faq-1", abstain=True, cites=(), answer="문맥에 없다", forced_abstain=True)
    text = _render(rows)
    s3 = text.split("## 3.")[1].split("## 4.")[0]
    assert "faq-1" in s3 and "문맥에 없다" in s3 and "faq-2" not in s3
    s4 = text.split("## 4.")[1].split("## 5.")[0]
    assert "ood-1" in s4 and "ood-10" in s4


def test_outside_and_wrong_citation_lists():
    rows = _rows(n_golden=5)
    rows[0]["invalid_citations"] = ["제99조"]
    rows[1] = _row("faq-2", cites=("제3조",), gold=("제2조",))
    s5 = _render(rows).split("## 5.")[1].split("## 6.")[0]
    assert "faq-1" in s5 and "제99조" in s5 and "faq-2" in s5


def test_metrics_table_has_all_eight_signals_with_zone_text():
    s1 = _render().split("## 1.")[1].split("## 2.")[0]
    for n in ["1", "2", "3", "4", "5", "6a", "6b", "6c", "6d", "7", "8"]:
        assert f"| {n} " in s1
    assert "정상" in s1


def test_second_run_row_says_not_yet_when_no_rerun():
    assert "두 번째 실행 아직 없음" in _render()
    rerun = _cfg(second=_run(calls=0, cache_hits=133))
    assert "0회" in _render(cfg=rerun).split("## 6.")[1]
    broken = _cfg(second=_run(calls=1, cache_hits=132))
    assert "캐시 결함" in _render(cfg=broken)


def test_main_writes_docs_file(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rows = _rows()
    (out / "answers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    (out / "config.json").write_text(json.dumps(_cfg()), encoding="utf-8")
    law = [
        {
            "label": "제2조",
            "title": "정의",
            "deleted": False,
            "text": "제2조(정의) 본문",
            "paragraphs": [],
        }
    ]
    docs = tmp_path / "docs" / "139-answer.md"
    assert rp.main([], out_dir=out, docs_path=docs, law_rows=law, faq_rows=FAQ_ROWS) == 0
    assert docs.read_text(encoding="utf-8").startswith("생성 실패")


def test_faq_citation_renders_question_in_sample():
    rows = _rows(n_golden=2)
    rows[0] = _row("faq-1", cites=("Q1", "제2조"))
    rows[1] = _row("faq-2", cites=("Q2",))
    section = _render(rows).split("## 2.")[1].split("## 3.")[0]
    assert "FAQ Q1 · FAQ 질문 1" in section and "FAQ Q2 · FAQ 질문 2" in section
