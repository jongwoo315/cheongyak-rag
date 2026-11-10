import copy
import dataclasses

from cheongyak_rag.golden import check
from cheongyak_rag.profile import Profile

FIELDS = [f.name for f in dataclasses.fields(Profile)]
Q_H = "무주택 질의"
Q_A = "통장 질의"
PAGES = {"N1": ["첫째 쪽 글자 하나", "둘째 쪽 글자 가입 기간"]}
ARTICLES = {"제53조": "주택소유 여부를 판단할 때", "제28조": "가입하여 1년이 지나고"}
NOTICES = {"N1": {"house_manage_no": "N1", "as_of": "2026-09-01", "facts": {}}}


def label(axis="homeless", query=Q_H, verdict="ELIGIBLE", **kw):
    base = {
        "axis": axis, "query": query, "verdict": verdict, "reason": "이유 한 문장",
        "fields": ["homeless_now"], "need": [], "citations": ["제53조"],
        "article_quotes": {"제53조": "주택소유 여부를 판단할 때"},
        "notice_evidence": [], "rule": "homeless-2", "rule_note": None,
    }  # fmt: skip
    return {**base, **kw}


def row(i=1, kind="empty", profile=None, labels=None):
    full = {f: None for f in FIELDS}
    full.update(profile or {})
    return {
        "id": f"g{i:02d}", "house_manage_no": "N1", "pblanc_no": "N1", "notice_name": "공고",
        "as_of": "2026-09-01", "profile_kind": kind, "profile": full,
        "labels": labels if labels is not None else [label(), label("account", Q_A, "NEED_INFO",
            fields=[], need=["deposit_amount"], citations=["제28조"],
            article_quotes={"제28조": "가입하여 1년이 지나고"}, rule="account-3")],
    }  # fmt: skip


def run(rows, **kw):
    return check.check_rows(
        rows,
        NOTICES,
        plan_of=lambda h, p: [("homeless", Q_H), ("account", Q_A)],
        article_of=ARTICLES.get,
        pages_of=PAGES.__getitem__,
        **kw,
    )


def problems(rows, **kw):
    return run(rows, **kw).problems


def test_valid_row_has_no_row_level_problems():
    rep = run([row()], expect_counts=None)
    assert rep.problems == []
    assert rep.quote_mismatches == 0


def test_count_rules_flag_wrong_totals():
    p = problems([row()])
    assert any("문항 50줄" in x for x in p)
    assert any("공고 20건" in x for x in p)
    assert any("프로필 종류" in x for x in p)


def test_missing_and_extra_labels_are_found():
    r = row(labels=[label(), label("rewin", "재당첨 질의", "NEED_INFO", need=["x"])])
    p = problems([r], expect_counts=None)
    assert any("라벨 없는 하위 질의" in x and Q_A in x for x in p)
    assert any("켜지지 않은 축" in x and "rewin" in x for x in p)


def test_label_field_problems():
    bad = label(verdict="MAYBE", need=["x"], citations=[], reason="")
    p = problems([row(labels=[bad, row()["labels"][1]])], expect_counts=None)
    assert any("판정값" in x for x in p)
    assert any("citations" in x for x in p)
    assert any("reason" in x for x in p)
    assert any("need" in x for x in p)


def test_need_info_requires_need_and_null_rule_requires_note():
    r = row()
    r["labels"][1]["need"] = []
    r["labels"][0]["rule"] = None
    p = problems([r], expect_counts=None)
    assert any("NEED_INFO" in x and "need" in x for x in p)
    assert any("rule_note" in x for x in p)


def test_row_fields_and_profile_kind():
    full = row(kind="full", profile={f: None for f in FIELDS})
    p = problems([full], expect_counts=None)
    assert any("꽉 찬" in x for x in p)
    part = row(kind="partial")
    assert any("일부" in x for x in problems([part], expect_counts=None))
    empty = row(kind="empty", profile={"homeless_now": True})
    assert any("빈 프로필" in x for x in problems([empty], expect_counts=None))


def test_profile_must_load():
    r = row(kind="partial", profile={"birth_date": "2000-01-01", "marriage_date": "2000-06-01"})
    assert any("프로필" in x for x in problems([r], expect_counts=None))


def test_article_quote_must_be_in_chunk_text_ignoring_whitespace():
    r = row()
    r["labels"][0]["article_quotes"]["제53조"] = "주택소유  여부를\n판단할 때"
    assert run([r], expect_counts=None).quote_mismatches == 0
    r["labels"][0]["article_quotes"]["제53조"] = "없는 구절"
    rep = run([r], expect_counts=None)
    assert rep.quote_mismatches == 1
    assert any("없는 구절" in x for x in rep.problems)


def test_unknown_article_label_counts_as_mismatch():
    r = row()
    r["labels"][0]["citations"] = ["제999조"]
    r["labels"][0]["article_quotes"] = {"제999조": "아무 구절"}
    rep = run([r], expect_counts=None)
    assert rep.quote_mismatches >= 1
    assert any("제999조" in x for x in rep.problems)


def test_notice_evidence_quote_checked_against_its_page():
    r = row()
    r["labels"][0]["notice_evidence"] = [{"page": 2, "quote": "가입 기간"}]
    assert run([r], expect_counts=None).quote_mismatches == 0
    r["labels"][0]["notice_evidence"] = [{"page": 1, "quote": "가입 기간"}]
    assert run([r], expect_counts=None).quote_mismatches == 1
    r["labels"][0]["notice_evidence"] = [{"page": 9, "quote": "가입 기간"}]
    assert run([r], expect_counts=None).quote_mismatches == 1


def test_check_notices_counts_fact_quotes():
    n = copy.deepcopy(NOTICES["N1"])
    n["pdf"] = "x.pdf"
    n["facts"] = {
        "residence": {"value": "v", "page": 1, "quote": "첫째 쪽"},
        "rewin": {"value": "v", "page": 2, "quote": "없는 말"},
        "special_types": [{"type": "신혼부부", "page": 2, "quote": "가입 기간"}],
        "regulation": {"price_cap": {"value": None, "page": None, "quote": None}},
    }
    bad = check.check_notices([n], pages_of=lambda h: PAGES["N1"])
    assert len(bad) == 1 and "없는 말" in bad[0]


def test_stats_count_ineligible_axes_and_null_rules():
    r = row(
        labels=[
            label(verdict="INELIGIBLE", rule=None, rule_note="이유"),
            label("account", Q_A, "INELIGIBLE", rule="account-1"),
        ]
    )
    st = run([r], expect_counts=None).stats
    assert st["verdicts"]["INELIGIBLE"] == 2
    assert st["ineligible_axes"] == ["account", "homeless"]
    assert st["rule_null"] == 1 and st["labels"] == 2


def test_agreement_counts_verdict_and_citation_disagreements():
    a = [row(labels=[label(), label("account", Q_A, "NEED_INFO", need=["d"], citations=["제28조"],
        article_quotes={"제28조": "x"})])]  # fmt: skip
    b = copy.deepcopy(a)
    b[0]["labels"][0]["verdict"] = "INELIGIBLE"
    b[0]["labels"][1]["citations"] = ["제10조"]
    ag = check.agreement(a, b)
    assert ag["labels"] == 2
    assert ag["verdict_diff"] == 1 and ag["citation_diff"] == 1
    assert ag["verdict_diff_ratio"] == 0.5
    assert ag["by_axis"]["homeless"]["verdict_diff"] == 1
    assert [d["axis"] for d in ag["diffs"]] == ["homeless", "account"]


def test_check_notices_flags_notice_without_facts():
    n = {"house_manage_no": "N1", "pdf": "x.pdf"}
    bad = check.check_notices([n, {**n, "facts": {}}], pages_of=lambda h: PAGES["N1"])
    assert len(bad) == 2 and all("facts" in x for x in bad)


def test_rule_must_look_like_a_rule_number():
    for bad in ("", "아무말", "homeless"):
        r = row(labels=[label(rule=bad), label("account", Q_A, "NEED_INFO", fields=[],
            need=["d"], citations=["제28조"], article_quotes={"제28조": "가입하여 1년이 지나고"})])  # fmt: skip
        assert any("rule이" in x for x in problems([r], expect_counts=None)), bad


def test_agreement_citation_diff_means_no_shared_article():
    a = [row(labels=[label(citations=["제53조", "제54조"])])]
    b = copy.deepcopy(a)
    b[0]["labels"][0]["citations"] = ["제53조"]
    assert check.agreement(a, b)["citation_diff"] == 0
    b[0]["labels"][0]["citations"] = ["제10조"]
    ag = check.agreement(a, b)
    assert ag["citation_diff"] == 1 and ag["diffs"][0]["kind"] == "citation"


def test_agreement_counts_missing_second_label_as_both_and_handles_empty():
    a = [row(labels=[label()])]
    ag = check.agreement(a, [row(labels=[])])
    assert ag["verdict_diff"] == 1 and ag["citation_diff"] == 1
    assert ag["diffs"][0]["kind"] == "both"
    assert check.agreement([], [])["verdict_diff_ratio"] == 0.0
