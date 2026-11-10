import json

from cheongyak_rag.golden import report


def lb(axis, verdict, rule="r-1", quotes=None, evid=None):
    return {
        "axis": axis, "query": f"{axis} 질의", "verdict": verdict, "reason": "이유 한 문장",
        "fields": [], "need": ["x"] if verdict == "NEED_INFO" else [],
        "citations": ["제53조"], "article_quotes": {"제53조": quotes or "조문 구절"},
        "notice_evidence": evid or [], "rule": rule, "rule_note": None if rule else "이유",
    }  # fmt: skip


def rows(n=30):
    out = []
    for i in range(1, n + 1):
        v = ["INELIGIBLE", "ELIGIBLE", "NEED_INFO"][i % 3]
        out.append({
            "id": f"g{i:02d}", "house_manage_no": f"N{i % 4}", "pblanc_no": f"N{i % 4}",
            "notice_name": f"공고{i % 4}", "as_of": "2026-09-01", "profile_kind": "partial",
            "profile": {"homeless_now": i % 2 == 0, "married": None},
            "labels": [lb("homeless", v), lb("account", "NEED_INFO", rule=None)],
        })  # fmt: skip
    return out


def test_band_agreement_picks_worst_ratio():
    assert report.band_agreement(0.05, 0.0) == "통과"
    assert report.band_agreement(0.051, 0.0) == "다시 잰다"
    assert report.band_agreement(0.0, 0.15) == "다시 잰다"
    assert report.band_agreement(0.01, 0.151) == "미완"


def test_band_quote_and_ineligible_and_rule_null():
    assert report.band_quote(0) == "통과"
    assert report.band_quote(10) == "1~10: 구절을 고치고 다시 대조"
    assert report.band_quote(11).startswith("11 이상")
    assert report.band_ineligible(30, 4) == "통과"
    assert report.band_ineligible(29, 4) != "통과"
    assert report.band_ineligible(40, 3) != "통과"
    assert report.band_rule_null(10, 100) == "통과"
    assert report.band_rule_null(11, 100) != "통과"


def test_review_sample_is_seeded_balanced_and_has_enough_ineligible():
    r = rows()
    a = report.pick_sample(r, seed=75)
    b = report.pick_sample(r, seed=75)
    assert a == b and len(a) == 20
    kinds = [x[1]["verdict"] for x in a]
    assert kinds.count("INELIGIBLE") >= 5
    assert {"INELIGIBLE", "ELIGIBLE", "NEED_INFO"} == set(kinds)
    assert max(kinds.count(k) for k in set(kinds)) - min(kinds.count(k) for k in set(kinds)) <= 1
    assert report.pick_sample(r, seed=1) != a


def test_review_sample_markdown_has_blank_fields():
    r = rows()
    r[0]["labels"][0]["notice_evidence"] = [{"page": 3, "quote": "공고문 구절"}]
    md = report.render_sample(r, report.pick_sample(r, seed=75))
    assert md.count("- 맞음/틀림:") == 20 and md.count("- 메모:") == 20
    assert "정답 근거 조문 구절" in md and "공고문 근거" in md


def test_report_first_line_is_one_sentence_conclusion_and_has_sections():
    notices = [
        {"house_manage_no": f"N{i}", "name": f"공고{i}", "area": "서울", "as_of": "2026-09-01",
         "axes": ["homeless"], "types": [], "flags": [], "pages": 10, "fixed": False,
         "db_mismatch": [], "db_silent": [], "facts": {}} for i in range(4)
    ]  # fmt: skip
    measure = {
        "quote_mismatch": {"first": 3, "after_fix": 0},
        "agreement_first": {"labels": 10, "verdict_diff": 0, "citation_diff": 1,
                            "verdict_diff_ratio": 0.0, "citation_diff_ratio": 0.1, "by_axis": {}},
        "agreement_second": None,
    }  # fmt: skip
    md = report.render_report(rows(), notices, measure, disagreements=[], second_rows=[])
    first = md.splitlines()[0]
    assert first.startswith("골든셋") and first.endswith(".") and "\n" not in first
    heads = ["공고 20건", "프로필 종류별", "축별·판정값별", "글자 대조", "따로 붙인 라벨"]
    heads += ["공고문·DB", "규칙으로 안 정해진", "실패 징후"]
    for head in heads:
        assert f"## {head}" in md
    json.dumps(measure)


def test_review_sample_keeps_five_ineligible_when_all_five_verdicts_exist():
    out = []
    for i in range(50):
        v = ["ELIGIBLE", "INELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE"][i % 5]
        out.append({
            "id": f"g{i + 1:02d}", "notice_name": "공고", "profile_kind": "empty", "profile": {},
            "labels": [lb("homeless", v)],
        })  # fmt: skip
    kinds = [x[1]["verdict"] for x in report.pick_sample(out, seed=75)]
    assert len(kinds) == 20 and kinds.count("INELIGIBLE") >= 5


def test_review_sample_fills_shortfall_when_a_verdict_has_few_labels():
    r = rows()
    for row in r:
        row["labels"] = row["labels"][:1]
    pool = [x for row in r for x in row["labels"]]
    for lab in pool[:1]:
        lab["verdict"] = "CONDITIONAL"
    for lab in pool[1:3]:
        lab["verdict"] = "UNVERIFIABLE"
    a = report.pick_sample(r, seed=75)
    assert len(a) == 20
    assert len({(x[0]["id"], x[1]["axis"]) for x in a}) == 20
    assert [x[1]["verdict"] for x in a].count("INELIGIBLE") >= 5
