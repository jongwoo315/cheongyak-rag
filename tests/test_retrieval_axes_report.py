import json

import pytest

from cheongyak_rag.retrieval import axes, index_db
from cheongyak_rag.retrieval import axes_report as rep
from cheongyak_rag.retrieval.query import Index
from tests.fakes import FakeEmbedder
from tests.test_retrieval_axes import _notice, _version
from tests.test_retrieval_query import FAQ, _row
from tests.test_retrieval_query import LAW as LAW3

# 조문 k=5가 채워지려면 조문이 5개 넘게 필요하다
LAW = LAW3 + [_row(f"제{n}조", f"제목{n}", f"{n}번째 규정을 정한다.") for n in range(4, 9)]
FAQ8 = FAQ + [
    {**FAQ[0], "q_no": n, "question": f"질문 {n}번은 무엇인가요?", "answer": f"답 {n}"}
    for n in range(5, 9)
]


@pytest.mark.parametrize(
    ("kw", "want"),
    [
        (dict(errors=0, no_mst=0, list_diff=0, short=0, sample_ok=True), "통과"),
        (dict(errors=0, no_mst=0, list_diff=0, short=3, sample_ok=True), "다시 잰다"),
        (dict(errors=0, no_mst=0, list_diff=0, short=4, sample_ok=True), "미완"),
        (dict(errors=1, no_mst=0, list_diff=0, short=0, sample_ok=True), "미완"),
        (dict(errors=0, no_mst=1, list_diff=0, short=0, sample_ok=True), "미완"),
        (dict(errors=0, no_mst=0, list_diff=1, short=0, sample_ok=True), "미완"),
        (dict(errors=0, no_mst=0, list_diff=0, short=0, sample_ok=False), "미완"),
    ],
)
def test_run_zone(kw, want):
    assert rep.zone_run(**kw) == want


@pytest.mark.parametrize(
    ("fn", "x", "want"),
    [
        (rep.zone_expected, 7, "통과"),
        (rep.zone_expected, 6, "통과"),
        (rep.zone_expected, 5, "다시 잰다"),
        (rep.zone_expected, 4, "다시 잰다"),
        (rep.zone_expected, 3, "미완"),
        (rep.zone_same, 0.98, "통과"),
        (rep.zone_same, 0.97, "다시 잰다"),
        (rep.zone_same, 0.90, "다시 잰다"),
        (rep.zone_same, 0.89, "미완"),
        (rep.zone_calls, 50, "통과"),
        (rep.zone_calls, 51, "다시 잰다"),
        (rep.zone_calls, 150, "다시 잰다"),
        (rep.zone_calls, 151, "미완"),
        (rep.zone_median, 2.0, "통과"),
        (rep.zone_median, 2.01, "다시 잰다"),
        (rep.zone_median, 5.0, "다시 잰다"),
        (rep.zone_median, 5.01, "미완"),
    ],
)
def test_zones(fn, x, want):
    assert fn(x) == want


def test_off_zone():
    same = {"special_off": 5, "rewin_off": 48}
    assert rep.zone_off(same, 84) == "통과"
    assert rep.zone_off({"special_off": 4, "rewin_off": 48}, 84) == "미완"
    assert rep.zone_off({"special_off": 4, "rewin_off": 48}, 90) == "다시 잰다"


def _setup(engine):
    """공고 셋: 아무 것도 안 켜짐 · 특별공급+규제 · 특별공급만."""
    _version(engine)
    _notice(engine, 1, models=[(0, {})])
    _notice(engine, 2, models=[(4, {"MNYCH_HSHLDCO": 4})], speclt_rdn_earth_at=True)
    _notice(engine, 3, area="인천", models=[(2, {"OLD_PARNTS_SUPORT_HSHLDCO": 2})])
    emb = FakeEmbedder(dim=1536)
    index_db.load(
        engine, index_db.build_rows(emb, "286965", "article", law_rows=LAW, faq_rows=FAQ8)
    )
    return emb, Index("article", emb, law_rows=LAW, faq_rows=FAQ8)


def _main(engine, tmp_path, emb, index):
    return rep.main(
        ["--report"],
        engine=engine,
        embedder=emb,
        index=index,
        out_md=tmp_path / "r.md",
        out_json=tmp_path / "r.json",
    )


def test_independent_on_matches_plan(pg_engine):
    _setup(pg_engine)
    got = rep.independent_on(pg_engine)
    assert len(got) == 3
    for (h, p), on in got.items():
        assert on == [x.id for x in axes.plan(pg_engine, h, p) if x.on]


def test_report_writes_md_and_json_with_all_six_signs(pg_engine, tmp_path, capsys):
    emb, index = _setup(pg_engine)
    assert _main(pg_engine, tmp_path, emb, index) == 0
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    first = md.splitlines()[0]
    assert first.startswith("공고 3건 중 예외 0건, 켜진 축 목록이") and "7개 중" in first
    for n in range(1, 7):
        assert f"| {n}. " in md
    for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
        assert heading in md
    run = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert set(run["zones"]) == {"run", "expected", "memory", "calls", "time", "off"}
    assert run["notices"] == 3 and run["kinds"] == 3 and len(run["samples"]) == 3
    assert run["list_diff"] == [] and run["short"] == [] and run["errors"] == []
    assert run["memory"]["ratio"] == 1.0
    assert "구간:" in capsys.readouterr().out


def test_report_sample_lists_every_on_axis_with_full_topk(pg_engine, tmp_path):
    emb, index = _setup(pg_engine)
    _main(pg_engine, tmp_path, emb, index)
    run = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    for s in run["samples"]:
        assert [a["id"] for a in s["axes"]] == s["on"]
        for a in s["axes"]:
            for h in a["hits"]:
                assert h["query"] and sum(x.startswith("조문 상위 5개") for x in h["lines"]) == 1
                assert any(x.startswith("FAQ 상위 3개") for x in h["lines"])


def test_report_exits_1_when_axis_list_differs(pg_engine, tmp_path, monkeypatch):
    emb, index = _setup(pg_engine)
    real = rep.independent_on

    def wrong(engine):
        out = real(engine)
        key = next(iter(out))
        out[key] = out[key][1:]
        return out

    monkeypatch.setattr(rep, "independent_on", wrong)
    assert _main(pg_engine, tmp_path, emb, index) == 1
    run = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert len(run["list_diff"]) == 1 and run["zones"]["run"] == "미완"
    assert "### 켜진 축 목록이 다시 계산한 것과 다른 공고" in (tmp_path / "r.md").read_text(
        encoding="utf-8"
    )


def test_report_counts_short_results(pg_engine, tmp_path):
    _version(pg_engine)
    _notice(pg_engine, 1, models=[(0, {})])
    emb = FakeEmbedder(dim=1536)
    law3 = LAW3  # 조문 3개뿐이라 k=5를 못 채운다
    index_db.load(
        pg_engine, index_db.build_rows(emb, "286965", "article", law_rows=law3, faq_rows=FAQ8)
    )
    index = Index("article", emb, law_rows=law3, faq_rows=FAQ8)
    assert _main(pg_engine, tmp_path, emb, index) == 0  # 적게 돌아온 축 3개 → 다시 잰다
    run = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert len(run["short"]) == 3 and run["zones"]["run"] == "다시 잰다"
    assert run["short"] and all(x["cause"] == "행이 모자란다" for x in run["short"])


def test_report_without_mst_is_incomplete(pg_engine, tmp_path):
    emb, index = _setup(pg_engine)
    _version(pg_engine, mst="1", effective="2099-01-01")  # 공고마다 고른 버전이 그대로다
    _notice(pg_engine, 9, de="2000-01-01", models=[(0, {})])  # 어떤 버전도 안 맞는 공고
    assert _main(pg_engine, tmp_path, emb, index) == 1
    run = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert run["no_mst"] == ["2026000009"]


def test_report_records_previous_run_when_queries_change(pg_engine, tmp_path):
    emb, index = _setup(pg_engine)
    _main(pg_engine, tmp_path, emb, index)
    prev = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    for a in prev["axes"]:
        if a["id"] == "rewin":
            a["queries"][0]["query"] = "옛 문장"
    (tmp_path / "r.json").write_text(json.dumps(prev), encoding="utf-8")
    _main(pg_engine, tmp_path, emb, index)
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "고치기 전 문장" in md and "옛 문장" in md


def test_report_requires_the_flag():
    with pytest.raises(SystemExit):
        rep.main([])
