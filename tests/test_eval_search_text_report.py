"""#138 리포트 — runs/76과 runs/138 줄에서 실패 징후 1~4를 센다."""

import json

import pytest

from cheongyak_rag.eval import search_text_report as st
from cheongyak_rag.eval.report import METRIC_NAMES
from cheongyak_rag.retrieval import axes

Q_INSTT = axes.Q_SPECIAL.format(type="기관추천")


def line(
    id_="g01",
    axis="homeless",
    query=None,
    cites=("제53조",),
    top5=("제53조",),
    gold="NEED_INFO",
    sys="NEED_INFO",
):
    return {
        "id": id_,
        "notice_name": f"공고 {id_}",
        "axis": axis,
        "query": query or f"{axis} 질의",
        "gold_verdict": gold,
        "gold_citations": list(cites),
        "law_top5": list(top5),
        "sys_verdict": sys,
        "sys_citations": [],
        "matched": True,
    }


def acct(id_, top5, cites=("제28조",)):
    return line(id_, "account", axes.Q_ACCOUNT, cites, top5)


def instt(id_, top5, cites=("제36조",)):
    return line(id_, "special_type", Q_INSTT, cites, top5)


def test_jw_counts_only_lines_with_a_law_gold_citation():
    rows = [
        acct("g01", ["제28조", "제9조"]),
        acct("g02", ["제9조"]),
        acct("g03", ["제9조"], cites=("Q12",)),  # 조문 정답 없음 → 분모에서 뺀다
        instt("g01", ["제36조"]),
        line("g01", "special_type", axes.Q_SPECIAL.format(type="신혼부부"), ("제41조",), ["제9조"]),
    ]
    j = st.jw(rows)
    assert (j["account"]["hit"], j["account"]["den"]) == (1, 2)
    assert (j["instt"]["hit"], j["instt"]["den"]) == (1, 1)
    assert [r["id"] for r in j["account"]["missed"]] == ["g02"]


@pytest.mark.parametrize(
    ("acc", "ins", "band"),
    [
        ((50, 50), (42, 42), "통과"),
        ((49, 50), (42, 42), "다시 잰다"),
        ((26, 50), (22, 42), "다시 잰다"),
        ((25, 50), (42, 42), "미완"),  # 절반 이하
        ((50, 50), (21, 42), "미완"),
        ((0, 50), (0, 42), "미완"),
        ((0, 0), (0, 0), "미완"),  # 잴 것이 없으면 통과가 아니다
    ],
)
def test_band_jw(acc, ins, band):
    j = {
        "account": {"hit": acc[0], "den": acc[1]},
        "instt": {"hit": ins[0], "den": ins[1]},
    }
    assert st.band_jw(j) == band


def test_leak_compares_law_top5_outside_the_two_groups():
    base = [
        acct("g01", ["제9조"]),
        instt("g01", ["제49조"]),
        line("g01", "homeless", top5=["제53조", "제46조"]),
        line("g01", "residence", top5=["제4조"]),
    ]
    now = [
        acct("g01", ["제28조"]),  # 바뀌는 것이 맞다
        instt("g01", ["제36조"]),
        line("g01", "homeless", top5=["제53조", "제46조"]),
        line("g01", "residence", top5=["제34조"]),  # 샜다
    ]
    got = st.leak(base, now)
    assert [(d["axis"], d["base"], d["now"]) for d in got] == [("residence", ["제4조"], ["제34조"])]


def test_leak_counts_a_missing_line_and_an_order_change():
    base = [
        line("g01", "homeless", top5=["제53조", "제46조"]),
        line("g01", "rewin", top5=["제54조"]),
    ]
    now = [line("g01", "homeless", top5=["제46조", "제53조"])]  # 순서만 바뀌어도 글자가 다르다
    assert len(st.leak(base, now)) == 2


@pytest.mark.parametrize(
    ("n", "band"), [(0, "정상"), (1, "다시 잰다"), (5, "다시 잰다"), (6, "미완")]
)
def test_band_leak(n, band):
    assert st.band_leak(n) == band


def test_house_mismatch_pairs():
    rows = [
        acct("g01", [], ("제28조",)),  # 01 + 제28조 → 맞다
        acct("g02", [], ("제27조",)),  # 03 + 제27조 → 맞다
        acct("g03", [], ("제28조",)),  # 03 + 제28조 → 어긋남
        acct("g04", [], ("제27조",)),  # 01 + 제27조 → 어긋남
        instt("g01", [], ("제36조",)),  # 01 + 제36조 → 맞다
        instt("g02", [], ("제35조",)),  # 03 + 제35조 → 맞다
        instt("g03", [], ("제36조",)),  # 03 + 제36조 → 어긋남
        acct("g05", [], ("제28조",)),  # 주택 구분 없음 → 어긋남에 안 든다
    ]
    house = {"g01": "01", "g02": "03", "g03": "03", "g04": "01"}
    bad = st.house_mismatch(rows, house)
    assert sorted((b["id"], b["axis"]) for b in bad) == [
        ("g03", "account"),
        ("g03", "special_type"),
        ("g04", "account"),
    ]


@pytest.mark.parametrize(
    ("n", "band"), [(0, "정상"), (1, "다시 잰다"), (3, "다시 잰다"), (4, "미완")]
)
def test_band_house(n, band):
    assert st.band_house(n) == band


@pytest.mark.parametrize(
    ("n", "band"), [(2, "정상"), (0, "정상"), (3, "다시 잰다"), (5, "다시 잰다"), (6, "미완")]
)
def test_band_fatal(n, band):
    assert st.band_fatal(n) == band


def test_fatal_lists_ineligible_gold_with_eligible_system():
    rows = [
        line("g01", gold="INELIGIBLE", sys="ELIGIBLE"),
        line("g02", gold="INELIGIBLE", sys="INELIGIBLE"),
        line("g03", gold="ELIGIBLE", sys="ELIGIBLE"),
    ]
    bad, den = st.fatal(rows)
    assert [r["id"] for r in bad] == ["g01"] and den == 2


class FakeResult:
    def __init__(self, id_, hits):
        self.id, self.hits = id_, hits


class FakeHits:
    def __init__(self, query, labels):
        self.query = query
        self.law = [type("C", (), {"label": x}) for x in labels]


def test_search_only_lines_join_golden_labels_with_search_hits():
    gold = {
        "id": "g01",
        "labels": [
            {"axis": "account", "query": axes.Q_ACCOUNT, "citations": ["제28조"]},
            {"axis": "rewin", "query": axes.Q_REWIN, "citations": ["제54조"]},
            {"axis": "residence", "query": "없는 질의", "citations": ["제4조"]},
        ],
    }
    results = [
        FakeResult("account", [FakeHits(axes.Q_ACCOUNT, ["제28조", "제9조"])]),
        FakeResult("rewin", [FakeHits(axes.Q_REWIN, ["제54조"])]),
    ]
    got = st.search_only_lines(gold, results)
    assert [(r["axis"], r["law_top5"], r["matched"]) for r in got] == [
        ("account", ["제28조", "제9조"], True),
        ("rewin", ["제54조"], True),
        ("residence", [], False),
    ]
    assert got[0]["gold_citations"] == ["제28조"] and got[0]["id"] == "g01"


def _runs(tmp_path, base_rows, now_rows):
    for name, rows, usd in (("base", base_rows, 0.0), ("now", now_rows, 0.5)):
        d = tmp_path / name
        d.mkdir()
        (d / "run.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )
        m = {"value": 0.5, "num": 1, "den": 2}
        metrics = {k: m for k, _, _ in METRIC_NAMES}
        metrics["judgment_accuracy"] = {"total": m, "axes": {}}  # 실제 metrics.json 꼴
        (d / "metrics.json").write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "usd": usd,
                    "stop": None,
                    "counts": {"unmatched_system_queries": 3},
                }
            )
        )
    return tmp_path / "base", tmp_path / "now"


def test_render_has_every_section(tmp_path):
    base_rows = [acct("g01", ["제9조"]), instt("g01", ["제49조"]), line("g01", "homeless")]
    now_rows = [acct("g01", ["제28조"]), instt("g01", ["제36조"]), line("g01", "homeless")]
    base, now = _runs(tmp_path, base_rows, now_rows)
    md = st.render(base_rows, now_rows, {"g01": "01"}, st.read_metrics(base), st.read_metrics(now))
    for head in ("## jw 기준", "## 실패 징후 2", "## 실패 징후 3", "## 실패 징후 4", "## 지표 7개"):
        assert head in md
    assert "정답 근거 조문과 그 본문을 보고 썼다" in md
    assert "구간: **통과**" in md and "1/1" in md


def test_render_lists_miss_leak_mismatch_and_fatal_rows(tmp_path):
    base_rows = [
        acct("g01", ["제9조"]),
        instt("g01", ["제49조"]),
        line("g01", "homeless", top5=["제53조"], gold="INELIGIBLE", sys="NEED_INFO"),
    ]
    fatal_row = line("g01", "homeless", top5=["제46조"], gold="INELIGIBLE", sys="ELIGIBLE")
    fatal_row["sys_citations"] = ["제53조", "Q12"]  # 조문이 아닌 인용은 표에서 뺀다
    now_rows = [
        acct("g01", ["제9조"]),  # 못 들었다. 03인데 정답 근거 조문이 제28조 → 어긋남
        instt("g01", ["제35조"], cites=("제35조",)),  # 03 + 제35조 → 맞다
        fatal_row,  # law_top5가 바뀌었다 → 샜다. 치명오답이다
    ]
    base, now = _runs(tmp_path, base_rows, now_rows)
    md = st.render(base_rows, now_rows, {"g01": "03"}, st.read_metrics(base), st.read_metrics(now))
    assert "구간: **미완**" in md and "0/1" in md  # 청약통장 0/1은 절반 이하
    assert "청약통장에서 못 든 하위 질의 1개" in md
    assert "`law_top5`가 #76과 글자까지 다른 것: **1개** → 구간 **다시 잰다**" in md
    assert "어긋난 하위 질의: **1개** → 구간 **다시 잰다**" in md
    assert "**1/1**, #76은 0/1 → 구간 **정상**" in md
    assert "| 제53조 |" in md and "Q12" not in md  # 치명오답 표의 인용 조문
    assert "#76 3, 이번 3" in md and "비용 $0.5000" in md
