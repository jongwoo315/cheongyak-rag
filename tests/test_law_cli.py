import json
from pathlib import Path

import httpx
import pytest

from cheongyak_rag.ingest import law

FIXTURE = Path(__file__).parent / "fixtures" / "law_sample.json"
SEARCH_BODY = {
    "LawSearch": {
        "law": {
            "현행연혁코드": "현행",
            "법령일련번호": "286965",
            "법령명한글": "주택공급에 관한 규칙",
            "법령ID": "008243",
            "시행일자": "20260615",
        }
    }
}


class Fake:
    """검색·본문 호출 수를 세는 가짜 서버."""

    def __init__(self, service_body=None, search_body=None):
        self.calls = {"search": 0, "service": 0}
        self.service_body = service_body or json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.search_body = search_body or SEARCH_BODY

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            kind = "search" if "lawSearch" in request.url.path else "service"
            self.calls[kind] += 1
            return httpx.Response(
                200, json=self.search_body if kind == "search" else self.service_body
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def dirs(tmp_path):
    return {"raw_dir": tmp_path / "raw", "out_dir": tmp_path / "processed"}


def run(fake, dirs, oc="key", faq=None, **kw):
    return law.main(
        oc=oc, faq_path=faq or dirs["out_dir"] / "no-faq.jsonl", client=fake.client(), **dirs, **kw
    )


def test_success_writes_cache_and_jsonl_and_prints_report(dirs, capsys):
    fake = Fake()

    assert run(fake, dirs) == 0

    assert (dirs["raw_dir"] / "law-008243-20260615.json").exists()
    lines = (dirs["out_dir"] / "law-008243-20260615.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(ln) for ln in lines]
    assert [r["label"] for r in rows] == ["제1조", "제2조", "제3조", "제7조의2", "제29조"]
    assert {r["mst"] for r in rows} == {"286965"}
    out = capsys.readouterr().out
    assert "286965" in out and "2026-06-15" in out
    assert "누락 0" in out and "중복 0" in out


def test_second_run_searches_again_but_does_not_download_body_again(dirs, capsys):
    fake = Fake()

    run(fake, dirs)
    capsys.readouterr()
    assert run(fake, dirs) == 0

    assert fake.calls == {"search": 2, "service": 1}
    assert "캐시 사용" in capsys.readouterr().out


def test_empty_oc_exits_1_with_cause_and_calls_nothing(dirs, capsys):
    fake = Fake()

    assert run(fake, dirs, oc="") == 1

    assert fake.calls == {"search": 0, "service": 0}
    assert "LAW_OC" in capsys.readouterr().err
    assert not dirs["out_dir"].exists()


def test_api_error_body_exits_1_and_writes_nothing(dirs, capsys):
    fake = Fake(search_body={"result": "사용자 정보 검증에 실패하였습니다."})

    assert run(fake, dirs) == 1

    assert "사용자 정보 검증" in capsys.readouterr().err
    assert not dirs["out_dir"].exists()


def test_validation_failure_exits_1_and_keeps_previous_jsonl(dirs, monkeypatch, capsys):
    out = dirs["out_dir"] / "law-008243-20260615.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text("이전 파일\n", encoding="utf-8")
    real = law.parse_articles

    def lossy(law_json, mst=""):
        arts = real(law_json, mst)
        arts[2].paragraphs.pop(0)  # 제3조 ① 항을 빠뜨리는 파서
        return arts

    monkeypatch.setattr(law, "parse_articles", lossy)

    assert run(Fake(), dirs) == 1

    assert out.read_text(encoding="utf-8") == "이전 파일\n"
    captured = capsys.readouterr()
    assert "누락 1" in captured.out
    assert "제3조" in captured.out
    assert "쓰지 않았다" in captured.err


def test_missing_faq_jsonl_skips_only_that_item_with_a_hint(dirs, capsys):
    assert run(Fake(), dirs) == 0

    out = capsys.readouterr().out
    assert "python -m cheongyak_rag.ingest.faq" in out


def test_faq_cross_is_in_report_when_faq_jsonl_exists(dirs, tmp_path, capsys):
    faq = tmp_path / "faq.jsonl"
    pairs = [
        {"q_no": 1, "as_of": "2024-05-29", "cited_articles": ["제3조제1항"]},
        {"q_no": 2, "as_of": "2024-05-29", "cited_articles": ["제999조"]},
    ]
    faq.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs), encoding="utf-8")

    assert run(Fake(), dirs, faq=faq) == 0

    out = capsys.readouterr().out
    assert "FAQ 2쌍" in out
    assert "현행에 없는 조를 인용한 쌍: 1" in out
    assert "다른 법령" in out


def test_broken_faq_jsonl_does_not_block_main_output(dirs, tmp_path, capsys):
    faq = tmp_path / "faq.jsonl"
    faq.write_text('{"q_no": 1}\n\nnot json\n', encoding="utf-8")

    assert run(Fake(), dirs, faq=faq) == 0

    assert (dirs["out_dir"] / "law-008243-20260615.jsonl").exists()
    assert "FAQ" in capsys.readouterr().out


def test_connection_failure_exits_1_with_message(dirs, capsys):
    def boom(request):
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(boom))

    assert law.main(oc="key", client=client, faq_path=dirs["out_dir"] / "x", **dirs) == 1
    assert "ConnectError" in capsys.readouterr().err


def _with_promulgation(search_body):
    entry = {**search_body["LawSearch"]["law"], "공포번호": "01592"}
    return {"LawSearch": {"law": entry}}


def test_cache_with_matching_law_key_is_reused_and_stale_one_is_refetched(dirs):
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body["법령"]["법령키"] = "0082432026061501592"
    fake = Fake(service_body=body, search_body=_with_promulgation(SEARCH_BODY))

    run(fake, dirs)
    run(fake, dirs)
    assert fake.calls == {"search": 2, "service": 1}  # 법령키가 같으면 캐시

    fake.service_body = {**body, "법령": {**body["법령"], "법령키": "0082432026061501592"}}
    raw = dirs["raw_dir"] / "law-008243-20260615.json"
    stale = json.loads(raw.read_text(encoding="utf-8"))
    stale["법령"]["법령키"] = "0082432026061500001"
    raw.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    run(fake, dirs)
    assert fake.calls["service"] == 2  # 법령키가 다르면 다시 받는다


def test_refetched_stale_cache_is_reported_as_download_not_cache(dirs, capsys):
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body["법령"]["법령키"] = "0082432026061501592"
    fake = Fake(service_body=body, search_body=_with_promulgation(SEARCH_BODY))
    run(fake, dirs)
    raw = dirs["raw_dir"] / "law-008243-20260615.json"
    stale = json.loads(raw.read_text(encoding="utf-8"))
    stale["법령"]["법령키"] = "0082432026061500001"
    raw.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()

    run(fake, dirs)

    out = capsys.readouterr().out
    assert fake.calls["service"] == 2
    assert "본문: 다운로드" in out and "캐시 사용" not in out


def test_blank_lines_in_faq_jsonl_do_not_skip_the_whole_file(dirs, tmp_path, capsys):
    faq = tmp_path / "faq.jsonl"
    pair = {"q_no": 1, "as_of": "2024-05-29", "cited_articles": ["제3조제1항"]}
    faq.write_text(json.dumps(pair, ensure_ascii=False) + "\n\n", encoding="utf-8")

    assert run(Fake(), dirs, faq=faq) == 0

    assert "FAQ 1쌍" in capsys.readouterr().out


@pytest.mark.parametrize(
    "line",
    [
        '{"q_no": 1}',  # as_of·cited_articles 없음 → KeyError
        '{"q_no": 1, "as_of": "2024-05-29", "cited_articles": null}',  # TypeError
        '["x"]',  # 객체가 아닌 줄 → TypeError
        "not json",  # ValueError
    ],
)
def test_unreadable_faq_row_skips_only_that_item_and_says_why(dirs, tmp_path, capsys, line):
    faq = tmp_path / "faq.jsonl"
    faq.write_text(line + "\n", encoding="utf-8")

    assert run(Fake(), dirs, faq=faq) == 0  # 법령 출력과 exit code는 막지 않는다

    captured = capsys.readouterr()
    assert (dirs["out_dir"] / "law-008243-20260615.jsonl").exists()
    assert "읽지 못해" in captured.err
    assert "이 항목은 건너뛴다" in captured.out
    assert "FAQ JSONL이 없어" not in captured.out  # 파일은 있다. 없다고 말하면 원인이 틀린다


def test_missing_promulgation_no_warns_that_cache_version_is_unchecked(dirs, capsys):
    fake = Fake()  # SEARCH_BODY에는 공포번호가 없다
    run(fake, dirs)
    capsys.readouterr()

    assert run(fake, dirs) == 0

    assert "판본을 확인하지 못" in capsys.readouterr().err
    assert fake.calls["service"] == 1


def test_success_overwrites_previous_jsonl_with_new_content(dirs):
    out = dirs["out_dir"] / "law-008243-20260615.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text("이전 판본\n", encoding="utf-8")

    assert run(Fake(), dirs) == 0

    text = out.read_text(encoding="utf-8")
    assert "이전 판본" not in text
    assert len(text.splitlines()) == 5  # 픽스처의 조문 5개
