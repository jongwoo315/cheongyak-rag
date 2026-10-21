import json
from pathlib import Path

import pytest

from cheongyak_rag.generate import answer as ans
from cheongyak_rag.generate import evaluate as ev
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_query import FAQ, LAW

OOD_REAL = Path(__file__).resolve().parents[1] / "runs" / "139" / "ood.jsonl"

GOLDEN = [
    {"qid": "faq-1", "q_no": 1, "question": "무주택세대구성원이란?", "gold": ["제2조"]},
    {"qid": "faq-2", "q_no": 2, "question": "청약 자격은?", "gold": ["제3조"]},
]
OOD = [{"qid": "ood-1", "question": "자동차 보험료를 줄이는 방법은?"}]


def _reply(abstain=False, cites=("제2조",)):
    body = {"abstain": abstain, "answer": "답 [제2조]", "citations": list(cites)}
    return json.dumps(body, ensure_ascii=False)


def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


@pytest.fixture
def env(tmp_path):
    (tmp_path / "selected.json").write_text(json.dumps({"candidate": "item"}), encoding="utf-8")
    _write(tmp_path / "golden.jsonl", GOLDEN)
    _write(tmp_path / "ood.jsonl", OOD)
    return tmp_path


def _main(env, client, *extra, sleep=lambda s: None):
    return ev.main(
        list(extra),
        client=client,
        embedder=FakeEmbedder(),
        law_rows=LAW,
        faq_rows=FAQ,
        golden_path=env / "golden.jsonl",
        ood_path=env / "ood.jsonl",
        out_dir=env / "out",
        runs73=env,
        cache_path=env / "gen.jsonl",
        sleep=sleep,
    )


def _rows(env, name="answers.jsonl"):
    lines = (env / "out" / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines]


def _config(env):
    return json.loads((env / "out" / "config.json").read_text(encoding="utf-8"))


def test_real_ood_file_has_ten_questions():
    rows = [json.loads(x) for x in OOD_REAL.read_text(encoding="utf-8").splitlines()]
    assert [r["qid"] for r in rows] == [f"ood-{i}" for i in range(1, 11)]
    assert rows[0]["question"] == "자동차 보험료를 줄이는 방법은?"
    assert rows[9]["question"] == "전월세 신고제의 신고 기한은?"


def test_rows_in_fixed_order_with_extra_fields(env):
    client = FakeChat([_reply()])
    assert _main(env, client) == 0
    rows = _rows(env)
    assert [r["qid"] for r in rows] == ["faq-1", "faq-2", "ood-1"]
    assert [r["set"] for r in rows] == ["golden", "golden", "ood"]
    assert rows[0]["gold"] == ["제2조"] and rows[2]["gold"] == []
    assert rows[0]["retrieval_hit"] is True  # 조가 3개뿐이라 상위 5에 다 들어간다
    assert rows[2]["retrieval_hit"] is None
    assert rows[0]["question"] == "무주택세대구성원이란?"
    for r in rows:
        assert "latency_s" not in r and "cached" not in r  # 실행마다 달라지는 값
        assert {"abstain", "forced_abstain", "citations", "usd", "error"} <= set(r)


def test_same_question_faq_is_excluded_from_context(env):
    client = FakeChat([_reply()])
    _main(env, client)
    rows = _rows(env)
    assert rows[0]["self_faq_in_context"] is False
    assert "Q1" not in rows[0]["context_labels"]
    assert "[Q1]" not in client.calls[0]["messages"][1]["content"]


def test_self_faq_detection_flags_leak(env):
    # 질문 글자가 FAQ 질문과 달라 제외가 안 걸리면 누수로 센다
    golden = [{"qid": "faq-1", "q_no": 1, "question": "무주택세대구성원이란? ", "gold": ["제2조"]}]
    _write(env / "golden.jsonl", golden)
    _main(env, FakeChat([_reply()]))
    (row, *_) = _rows(env)
    assert "Q1" in row["context_labels"] and row["self_faq_in_context"] is True


def test_summary_counts_and_config(env):
    client = FakeChat([_reply()], prompt_tokens=2000, completion_tokens=500)
    _main(env, client)
    run = _config(env)["first_run"]
    assert (run["calls"], run["retries"], run["cache_hits"]) == (3, 0, 0)
    assert (run["input_tokens"], run["output_tokens"]) == (6000, 1500)
    assert run["usd"] == pytest.approx(3 * (2000 * 0.75e-6 + 500 * 4.5e-6))
    assert run["stopped"] is False
    cfg = _config(env)
    assert (cfg["model"], cfg["k"], cfg["faq_k"], cfg["questions"]) == ("gpt-5.4-mini", 5, 3, 3)
    assert cfg["budget_usd"] == 6


def test_budget_stops_the_run(env, capsys):
    client = FakeChat([_reply()], prompt_tokens=100_000, completion_tokens=1000)  # 질문당 ≈$0.08
    assert _main(env, client, "--budget-usd", "0.1") == 2
    assert len(client.calls) == 2  # 둘째 답에서 0.1을 넘어 멈춘다
    assert len(_rows(env, "answers.partial.jsonl")) == 2
    run = json.loads((env / "out" / "config.partial.json").read_text("utf-8"))["stopped_run"]
    assert run["stopped"] is True and run["stopped_at"] == "faq-2"
    assert "예산" in capsys.readouterr().err


def test_second_run_makes_no_call_and_is_byte_identical(env):
    _main(env, FakeChat([_reply()]))
    first = (env / "out" / "answers.jsonl").read_bytes()
    client = FakeChat([_reply(abstain=True, cites=())])
    assert _main(env, client) == 0
    assert client.calls == []
    assert (env / "out" / "answers.jsonl").read_bytes() == first
    cfg = _config(env)
    assert cfg["first_run"]["calls"] == 3  # 호출한 실행의 값을 지우지 않는다
    assert (cfg["second_run"]["calls"], cfg["second_run"]["cache_hits"]) == (0, 3)


def test_second_run_with_calls_is_not_hidden(env):
    _main(env, FakeChat([_reply()]))
    (env / "gen.jsonl").unlink()  # 캐시가 안 맞는 결함을 흉내 낸다. 답은 같다
    _main(env, FakeChat([_reply()]))
    cfg = _config(env)
    assert cfg["first_run"]["calls"] == 3 and cfg["second_run"]["calls"] == 3


def test_changed_answers_replace_first_run(env):
    _main(env, FakeChat([_reply()]))
    (env / "gen.jsonl").unlink()
    _main(
        env, FakeChat([_reply().replace("답 [제2조]", "다른 답 [제2조]")])
    )  # 프롬프트를 고쳐 다시 잰 경우
    cfg = _config(env)
    assert cfg["first_run"]["calls"] == 3 and "second_run" not in cfg


def test_stopped_run_does_not_overwrite_complete_result(env):
    _main(env, FakeChat([_reply()], prompt_tokens=100_000, completion_tokens=1000))
    good = (env / "out" / "answers.jsonl").read_bytes()
    (env / "gen.jsonl").unlink()
    assert _main(env, FakeChat([_reply()], prompt_tokens=100_000), "--budget-usd", "0.1") == 2
    assert (env / "out" / "answers.jsonl").read_bytes() == good
    assert len(_rows(env, "answers.partial.jsonl")) == 2
    assert _config(env)["first_run"]["stopped"] is False


def test_consecutive_errors_stop_the_run(env):
    many = [{"qid": f"ood-{i}", "question": f"질문 {i}"} for i in range(1, 9)]
    _write(env / "ood.jsonl", many)
    client = FakeChat([RuntimeError("503")])
    assert _main(env, client) == 3
    assert len(client.calls) == ev.MAX_CONSECUTIVE_ERRORS
    part = json.loads((env / "out" / "config.partial.json").read_text(encoding="utf-8"))
    assert "연속" in part["stopped_run"]["stop_reason"]


def test_429_exhaustion_is_recorded_per_question(env):
    class Rate(Exception):
        status_code = 429

    client = FakeChat([Rate(), Rate(), Rate(), Rate(), Rate(), Rate(), _reply()])
    assert _main(env, client) == 0
    rows = _rows(env)
    assert rows[0]["error"] and "Rate" in rows[0]["error"]  # 6번 시도 뒤 첫 질문만 실패
    assert rows[1]["error"] is None
    run = _config(env)["first_run"]
    assert run["retries"] == 5 and run["failures"] == 1


def test_failure_counts_are_in_config(env):
    client = FakeChat([_reply(), "{깨짐", _reply(cites=("제99조",))])
    _main(env, client)
    run = _config(env)["first_run"]
    assert run["failures"] == 1 and run["forced_abstain"] == 1


class _Err(Exception):
    def __init__(self, status, code=None):
        super().__init__(f"{status} {code}")
        self.status_code, self.code = status, code


def test_retry_429_with_exponential_wait():
    sleeps = []
    inner = FakeChat([_Err(429), _Err(429), _reply()])
    client = ev.RetryingClient(inner, sleep=sleeps.append)
    resp = client.chat.completions.create(model="m")
    assert resp.choices[0].message.content == _reply()
    assert (client.calls, client.retries, sleeps) == (3, 2, [2.0, 4.0])


def test_retry_gives_up_after_five():
    sleeps = []
    client = ev.RetryingClient(FakeChat([_Err(429)]), sleep=sleeps.append)
    with pytest.raises(_Err):
        client.chat.completions.create(model="m")
    assert (client.calls, client.retries) == (6, 5) and sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]


@pytest.mark.parametrize("err", [_Err(401), _Err(403), _Err(429, "insufficient_quota")])
def test_hard_errors_stop_without_retry(err):
    client = ev.RetryingClient(FakeChat([err]), sleep=lambda s: None)
    with pytest.raises(ans.HardApiError):
        client.chat.completions.create(model="m")
    assert (client.calls, client.retries) == (1, 0)


def test_hard_error_stops_run_and_keeps_partial_rows(env, capsys):
    client = FakeChat([_reply(), _Err(401)])
    assert _main(env, client) == 3
    assert len(_rows(env, "answers.partial.jsonl")) == 1
    part = json.loads((env / "out" / "config.partial.json").read_text("utf-8"))["stopped_run"]
    assert part["stopped"] is True and "401" in part["stop_reason"]


def test_percentile():
    assert ev.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0
    assert ev.percentile(list(map(float, range(1, 101))), 95) == 95.0
    assert ev.percentile([], 95) == 0.0


def test_attempt_latency_excludes_backoff_sleep():
    inner = FakeChat([_Err(429), _reply()])
    client = ev.RetryingClient(inner, sleep=lambda s: None)
    client.chat.completions.create(model="m")
    assert 0 <= client.last_attempt_s < 1
