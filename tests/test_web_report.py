from cheongyak_rag import web_report as wr


def _exp():
    return {
        "taken_at": "t",
        "notices": [
            {"house_manage_no": "A", "house_nm": "가단지", "n_models": 2},
            {"house_manage_no": "B", "house_nm": "나단지", "n_models": 0},
        ],
        "pairs": [
            {
                "notice": "A",
                "profile": "full",
                "expected": {
                    "verdict": None,
                    "routes": [["general", None], ["신혼부부", "INELIGIBLE"]],
                    "n_checklist": 3,
                },
            }
        ],
        "before": {"max_trace_id": 10, "verdict_cache_lines": 5, "embed_cache_lines": 7},
    }


def _page(h, status=200, title="가단지 청약", rows=2):
    return {"house_manage_no": h, "status": status, "title": title, "rows": rows}


def _screen(verdict="판정 없음", routes=None, n=3):
    routes = routes or [["신혼부부", "INELIGIBLE"], ["general", "판정 없음"]]
    return {"verdict": verdict, "routes": routes, "n_checklist": n}


def _raw(pages=None, attempts=None, links=2):
    return {
        "pages": pages or [_page("A"), _page("B", title="나단지", rows=0)],
        "links": links,
        "pairs": [
            {
                "notice": "A",
                "profile": "full",
                "attempts": attempts or [{"shown": True, "seconds": 3.0, "screen": _screen()}],
            }
        ],
    }


def _after(h=0, new=1):
    return {
        "verdict_cache_lines": 5 + h,
        "embed_cache_lines": 7,
        "new_traces": new,
        "new_trace_rows": [["A", "ok"]] * new,
    }


def test_everything_matching_is_pass_and_null_verdict_reads_as_no_verdict():
    r = wr.judge(_exp(), _raw(), _after())
    assert (r["s1"]["band"], r["s2"]["band"], r["s3"]["band"]) == ("통과",) * 3
    assert r["s2"]["G1"] == r["s2"]["G2"] == 0


def test_page_failures_are_counted_with_reasons():
    pages = [_page("A", status=500), _page("B", title="엉뚱", rows=1)]
    r = wr.judge(_exp(), _raw(pages=pages), _after())["s1"]
    assert r["F"] == 2 and r["band"] == "미완"
    assert "HTTP 500" in r["failed"][0]["why"][0]


def test_link_count_other_than_the_notice_count_is_incomplete():
    assert wr.judge(_exp(), _raw(links=1), _after())["s1"]["band"] == "미완"


def test_different_screen_value_is_g2_and_incomplete():
    bad = {"shown": True, "seconds": 1.0, "screen": _screen(verdict="ELIGIBLE")}
    r = wr.judge(_exp(), _raw(attempts=[bad]), _after())["s2"]
    assert r["G2"] == 1 and r["band"] == "미완"


def test_checklist_count_or_route_set_difference_is_g2():
    for screen in (_screen(n=4), _screen(routes=[["general", "판정 없음"]])):
        att = [{"shown": True, "seconds": 1.0, "screen": screen}]
        assert wr.judge(_exp(), _raw(attempts=att), _after())["s2"]["G2"] == 1


def test_timeout_then_good_retry_is_retake_band_and_expects_one_more_trace():
    att = [
        {"shown": False, "seconds": 120.0, "screen": None},
        {"shown": True, "seconds": 5.0, "screen": _screen()},
    ]
    r = wr.judge(_exp(), _raw(attempts=att), _after(new=2))
    assert r["s2"]["band"] == "다시 잰다" and r["s2"]["G1"] == 1 and r["s2"]["G1_after_retry"] == 0
    assert r["s3"]["T_expected"] == 2 and r["s3"]["band"] == "통과"


def test_timeout_again_after_retry_is_incomplete():
    att = [{"shown": False, "seconds": 120.0, "screen": None}] * 2
    assert wr.judge(_exp(), _raw(attempts=att), _after(new=2))["s2"]["band"] == "미완"


def test_new_cache_lines_or_wrong_trace_count_is_incomplete_for_s3():
    assert wr.judge(_exp(), _raw(), _after(h=1))["s3"]["band"] == "미완"
    assert wr.judge(_exp(), _raw(), _after(new=0))["s3"]["band"] == "미완"


def test_render_puts_the_three_symptoms_on_top():
    exp = _exp()
    text = wr.render(exp, wr.judge(exp, _raw(), _after()))
    top = text.split("## 1.")[0]
    assert "징후 1" in top and "징후 2" in top and "징후 3" in top
