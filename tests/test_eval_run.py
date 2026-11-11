"""#76 eval 실행 — 골든셋 문항을 판정에 돌려 run 줄로 쓴다. OpenAI·DB를 쓰지 않는다."""

import json

from cheongyak_rag.eval import metrics, report, run
from cheongyak_rag.generate import verdict as vd


def gold_label(axis, query, verdict, citations):
    return {"axis": axis, "query": query, "verdict": verdict, "citations": citations}


def item(id_="g01", labels=None):
    return {
        "id": id_,
        "house_manage_no": "H1",
        "pblanc_no": "P1",
        "notice_name": "테스트 공고",
        "profile": {},
        "labels": labels
        or [
            gold_label("homeless", "무주택 질의", "NEED_INFO", ["제53조"]),
            gold_label("account", "통장 질의", "INELIGIBLE", ["제28조"]),
        ],
    }


def sys_verdict(axis, query, verdict, citations=(), context=()):
    return vd.Verdict(
        axis, axis, query, verdict=verdict, citations=list(citations), context_labels=list(context)
    )


def fake_judge(verdicts):
    return lambda row: ([], verdicts)


def test_one_item_goes_to_report(tmp_path):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps(item(), ensure_ascii=False) + "\n", encoding="utf-8")
    verdicts = [
        sys_verdict("homeless", "무주택 질의", "NEED_INFO", ["제53조"], ["제53조", "Q1"]),
        sys_verdict("account", "통장 질의", "ELIGIBLE", ["제28조"], ["제28조"]),
    ]
    out = tmp_path / "out"
    code = run.main(
        ["--limit", "1", "--out-dir", str(out)], judge_fn=fake_judge(verdicts), golden=golden
    )
    assert code == 0
    lines = [json.loads(x) for x in (out / "run.jsonl").read_text("utf-8").splitlines()]
    assert [(x["axis"], x["sys_verdict"]) for x in lines] == [
        ("homeless", "NEED_INFO"),
        ("account", "ELIGIBLE"),
    ]
    m = json.loads((out / "metrics.json").read_text("utf-8"))
    acc = m["metrics"]["judgment_accuracy"]["total"]
    assert (acc["num"], acc["den"]) == (1, 2)
    md = tmp_path / "eval.md"
    assert report.main(["--run-dir", str(out), "--out", str(md)]) == 0
    assert "판정 정확도" in md.read_text("utf-8")


def test_accuracy_counts_wrong_and_axes():
    rows = [
        {"axis": "a", "gold_verdict": "NEED_INFO", "sys_verdict": "NEED_INFO", "error": None},
        {"axis": "a", "gold_verdict": "INELIGIBLE", "sys_verdict": "ELIGIBLE", "error": None},
        {"axis": "b", "gold_verdict": "ELIGIBLE", "sys_verdict": None, "error": "boom"},
    ]
    acc = metrics.judgment_accuracy(rows)
    assert (acc["total"]["num"], acc["total"]["den"]) == (1, 3)
    assert (acc["axes"]["a"]["num"], acc["axes"]["a"]["den"]) == (1, 2)
    assert (acc["axes"]["b"]["num"], acc["axes"]["b"]["den"]) == (0, 1)
