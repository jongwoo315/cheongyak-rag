import json

import pytest

from cheongyak_rag.generate import answer as ans
from cheongyak_rag.retrieval.chunk import Chunk
from tests.fakes import FakeChat, FakeEmbedder
from tests.test_retrieval_query import FAQ, LAW

MODEL = "gpt-5.4-mini"


def _result():
    return {
        "law": [
            Chunk(
                "law:제2조",
                "제2조",
                "제2조",
                "제2조(정의)\n공급이란 분양하는 것이다.",
                "law",
                {"title": "정의"},
            ),
            Chunk(
                "law:제3조",
                "제3조",
                "제3조",
                "제3조(자격)\n나이와 소득으로 정한다.",
                "law",
                {"title": "자격"},
            ),
        ],
        "faq": [
            Chunk("faq:1", "Q1", "Q1", "무주택세대구성원이란?\n세대원 전원이 무주택인 세대", "faq")
        ],
    }


def _reply(**kw):
    body = {"abstain": False, "answer": "공급은 분양이다 [제2조].", "citations": ["제2조"]}
    return json.dumps(body | kw, ensure_ascii=False)


def _gen(client, cache=None, result=None):
    return ans.generate("공급이란?", result or _result(), client, MODEL, cache)


def test_normal_answer_and_request_shape():
    client = FakeChat([_reply()], prompt_tokens=2000, completion_tokens=500)
    a = _gen(client)
    assert (a.abstain, a.forced_abstain, a.error) == (False, False, None)
    assert a.citations == ["제2조"] and a.invalid_citations == []
    assert a.context_labels == ["제2조", "제3조", "Q1"]
    assert (a.input_tokens, a.output_tokens, a.cached) == (2000, 500, False)
    assert a.usd == pytest.approx(2000 * 0.75e-6 + 500 * 4.5e-6)
    (kw,) = client.calls
    assert kw["model"] == MODEL and kw["max_completion_tokens"] == 1500
    assert "temperature" not in kw
    fmt = kw["response_format"]["json_schema"]
    assert kw["response_format"]["type"] == "json_schema" and fmt["strict"] is True
    assert set(fmt["schema"]["properties"]) == {"abstain", "answer", "citations"}


def test_messages_carry_labels_and_text():
    system, user = ans.build_messages("공급이란?", _result())
    assert system["role"] == "system" and user["role"] == "user"
    assert "abstain" in system["content"] and "[제34조]" in system["content"]
    assert "공급이란?" in user["content"]
    assert "[제2조] 제2조(정의)\n공급이란 분양하는 것이다." in user["content"]
    assert "[Q1] 무주택세대구성원이란?\n세대원 전원이 무주택인 세대" in user["content"]


def test_out_of_context_citation_is_split_off():
    a = _gen(FakeChat([_reply(citations=["제2조", "제99조", "[Q1]"])]))
    assert a.citations == ["제2조", "Q1"]  # 대괄호는 떼고 센다
    assert a.invalid_citations == ["제99조"]
    assert a.abstain is False


def test_no_valid_citation_forces_abstain():
    a = _gen(FakeChat([_reply(citations=["제99조"])]))
    assert (a.abstain, a.forced_abstain) == (True, True)
    assert a.invalid_citations == ["제99조"]


def test_empty_citations_forces_abstain():
    a = _gen(FakeChat([_reply(citations=[])]))
    assert (a.abstain, a.forced_abstain) == (True, True)


def test_model_abstain_is_not_forced():
    a = _gen(FakeChat([_reply(abstain=True, answer="문맥에 없다.", citations=[])]))
    assert (a.abstain, a.forced_abstain, a.error) == (True, False, None)
    assert a.answer == "문맥에 없다."


@pytest.mark.parametrize("content", ["{깨짐", None, "[]", json.dumps({"abstain": "예"})])
def test_bad_response_is_recorded_as_error(content):
    a = _gen(FakeChat([content]))
    assert a.error and a.abstain is True and a.answer == ""
    assert a.input_tokens == 1000  # 호출은 했으니 토큰은 센다


def test_api_exception_is_recorded_and_hard_error_propagates():
    a = _gen(FakeChat([RuntimeError("boom")]))
    assert "boom" in a.error and a.input_tokens == 0
    with pytest.raises(ans.HardApiError):
        _gen(FakeChat([ans.HardApiError("insufficient_quota")]))


def test_cache_hit_makes_no_call(tmp_path):
    path = tmp_path / "gen.jsonl"
    first = _gen(FakeChat([_reply()]), ans.GenCache(path))
    client = FakeChat([_reply(answer="다른 답")])
    second = _gen(client, ans.GenCache(path))  # 파일에서 다시 읽는다
    assert client.calls == [] and second.cached is True and first.cached is False
    assert second.answer == first.answer and second.usd == first.usd
    assert second.latency_s == first.latency_s  # 저장된 첫 호출 지연


def test_cache_key_changes_with_context(tmp_path):
    cache = ans.GenCache(tmp_path / "gen.jsonl")
    client = FakeChat([_reply()])
    _gen(client, cache)
    other = _result() | {"faq": []}
    _gen(client, cache, other)
    assert len(client.calls) == 2


def test_cache_skips_broken_line(tmp_path):
    path = tmp_path / "gen.jsonl"
    _gen(FakeChat([_reply()]), ans.GenCache(path))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"key": "끊긴')
    cache = ans.GenCache(path)  # 깨진 줄을 지우고 읽는다
    client = FakeChat([_reply()])
    assert _gen(client, cache).cached is True and client.calls == []
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def _cli(tmp_path, client, argv=("공급이란?", "--faq-k", "4")):
    (tmp_path / "selected.json").write_text(json.dumps({"candidate": "item"}), encoding="utf-8")
    return ans.main(
        list(argv),
        runs_dir=tmp_path,
        embedder=FakeEmbedder(),
        client=client,
        cache_path=tmp_path / "gen.jsonl",
        law_rows=LAW,
        faq_rows=FAQ,
    )


def test_cli_prints_answer_citation_text_and_tokens(tmp_path, capsys):
    reply = _reply(answer="공급은 분양이다 [제1조] [Q1].", citations=["제1조", "Q1"])
    client = FakeChat([reply], prompt_tokens=1234, completion_tokens=56)
    assert _cli(tmp_path, client) == 0
    out = capsys.readouterr().out
    assert "abstain: 아니오" in out and "공급은 분양이다" in out
    assert "[제1조] 제1조(목적)" in out and "주택 공급 목적을 정한다." in out  # 인용한 조 원문
    assert "Q1 · 무주택세대구성원이란?" in out  # 인용한 FAQ
    assert "검색 상위" in out
    assert "입력 1,234" in out and "출력 56" in out and "$" in out
    assert client.calls[0]["messages"][1]["content"].count("[Q") >= 1


def test_cli_does_not_exclude_same_question(tmp_path):
    client = FakeChat([_reply(citations=["Q1"])])
    _cli(tmp_path, client, argv=("무주택세대구성원이란?",))  # FAQ 1번과 같은 질문
    assert "[Q1]" in client.calls[0]["messages"][1]["content"]


def test_cli_prints_error_and_exits_nonzero(tmp_path, capsys):
    assert _cli(tmp_path, FakeChat(["{깨짐"])) == 1
    assert "생성 실패" in capsys.readouterr().out
