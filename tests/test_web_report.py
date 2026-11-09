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


def test_pages_that_were_not_measured_are_incomplete_not_pass():
    r = wr.judge(_exp(), _raw(pages=[_page("A")]), _after())["s1"]
    assert r["F"] == 0 and r["pages_missing"] == ["B"] and r["band"] == "미완"


def test_pairs_that_were_not_measured_are_incomplete_not_pass():
    raw = _raw()
    raw["pairs"] = []
    r = wr.judge(_exp(), raw, _after(new=0))["s2"]
    assert r["pairs_missing"] == ["A×full"] and r["band"] == "미완"


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


# ── 배포 측정 모드 (#85) ─────────────────────────────────────────────────


def _health(ok=True):
    body = {"status": "ok", "db": "ok", "pgvector": "ok" if ok else "missing"}
    return {"status_code": 200, "body": body}


def test_health_is_ok_only_with_200_and_db_and_pgvector_ok():
    assert wr.health_ok(_health())
    assert not wr.health_ok(_health(ok=False))
    assert not wr.health_ok({"status_code": 500, "body": {}})
    assert not wr.health_ok({"error": "ConnectError"})


def test_deploy_g2_ignores_verdict_but_counts_route_keys_and_checklist_size():
    other_verdict = {"shown": True, "seconds": 1.0, "screen": _screen(verdict="ELIGIBLE")}
    r = wr.judge(_exp(), _raw(attempts=[other_verdict]), None, deploy=True, health=_health())
    assert r["s2"]["G2"] == 0 and r["s2"]["band"] == "통과"
    assert r["s2"]["verdict_same"] == 0 and r["s2"]["n_compared"] == 1


def test_deploy_g2_catches_a_different_route_key_set_or_checklist_size():
    for screen in (_screen(n=4), _screen(routes=[["general", "판정 없음"]])):
        att = [{"shown": True, "seconds": 1.0, "screen": screen}]
        r = wr.judge(_exp(), _raw(attempts=att), None, deploy=True, health=_health())
        assert r["s2"]["G2"] == 1 and r["s2"]["band"] == "미완"


def test_deploy_counts_pairs_with_the_same_verdict_as_81():
    r = wr.judge(_exp(), _raw(), None, deploy=True, health=_health())
    assert r["s2"]["verdict_same"] == 1 and r["s2"]["G2"] == 0


def test_deploy_replaces_h_and_t_with_a():
    r = wr.judge(_exp(), _raw(), None, deploy=True, health=_health())
    assert "H" not in r["s3"] and "T" not in r["s3"]
    assert r["s3"]["A"] == "ok" and r["s3"]["band"] == "통과"
    bad = wr.judge(_exp(), _raw(), None, deploy=True, health=_health(ok=False))
    assert bad["s3"]["A"] == "not ok" and bad["s3"]["band"] == "미완"


def test_deploy_render_shows_a_and_g2_prime_and_not_h_t():
    exp = _exp()
    text = wr.render(exp, wr.judge(exp, _raw(), None, deploy=True, health=_health()), deploy=True)
    top = text.split("## 1.")[0]
    assert "A" in top and "G2'" in top and "판정값이 #81과 같은 쌍" in top
    assert "새 trace 행 T" not in text and "새 LLM 호출 H" not in text


def test_only_notice_keeps_the_notice_list_and_trims_the_pairs():
    exp = _exp()
    exp["pairs"].append({**exp["pairs"][0], "notice": "B"})
    got = wr.only_notice(exp, "A")
    assert [p["notice"] for p in got["pairs"]] == ["A"] and got["notices"] == exp["notices"]
    assert len(exp["pairs"]) == 2  # 원본은 그대로


def test_only_notice_unknown_notice_raises():
    import pytest

    with pytest.raises(SystemExit):
        wr.only_notice(_exp(), "없음")


def test_parse_args_defaults_are_the_84_paths():
    a = wr.parse_args(["after"])
    assert a.cmd == "after" and not a.deploy
    assert a.run_dir == wr.REPO / "runs" / "84" and a.report == wr.REPO / "docs" / "84-web.md"


def test_parse_args_relative_paths_resolve_against_the_repo():
    a = wr.parse_args(
        [
            "after",
            "--run-dir",
            "runs/85/x",
            "--report",
            "runs/85/x/r.md",
            "--deploy",
            "--api-url",
            "u",
        ]
    )
    assert a.run_dir == wr.REPO / "runs/85/x" and a.report == wr.REPO / "runs/85/x/r.md"
    assert a.deploy and a.api_url == "u"


def test_parse_args_deploy_without_api_url_on_after_is_an_error():
    import pytest

    with pytest.raises(SystemExit):
        wr.parse_args(["after", "--deploy"])
