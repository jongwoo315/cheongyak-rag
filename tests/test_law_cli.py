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
