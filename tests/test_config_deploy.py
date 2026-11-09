"""배포용 설정 (#85): 캐시 위치와 DB 주소 읽기."""

from pathlib import Path

import pytest

from cheongyak_rag.config import Settings, settings
from cheongyak_rag.generate import answer, verdict
from cheongyak_rag.generate.answer import GenCache
from cheongyak_rag.retrieval import embed
from tests.test_retrieval_embed import FakeClient

REPO = Path(__file__).resolve().parents[1]


def test_cache_dir_default_is_the_current_path():
    assert Settings(_env_file=None).cache_dir == REPO / "data" / "cache"


def test_cache_dir_reads_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    assert Settings(_env_file=None).cache_dir == tmp_path


def test_all_three_caches_follow_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cache_dir", tmp_path)
    assert embed.cache_path_for("m") == tmp_path / "embed-m.jsonl"
    assert answer.cache_path_for("m") == tmp_path / "gen-m.jsonl"
    assert verdict.cache_path_for("m") == tmp_path / "verdict-m.jsonl"


def test_writes_land_in_cache_dir_and_leave_data_cache_alone(monkeypatch, tmp_path):
    real = REPO / "data" / "cache"
    before = {p.name: p.stat().st_size for p in real.glob("*")} if real.exists() else {}
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "새 디렉터리")  # 없는 디렉터리도 만든다
    Embedder = embed.Embedder("em", client=FakeClient())
    Embedder.embed(["가"])
    GenCache(answer.cache_path_for("gm")).put("k", {"content": "x"})
    GenCache(verdict.cache_path_for("vm")).put("k", {"content": "x"})
    names = sorted(p.name for p in (tmp_path / "새 디렉터리").iterdir())
    assert names == ["embed-em.jsonl", "gen-gm.jsonl", "verdict-vm.jsonl"]
    after = {p.name: p.stat().st_size for p in real.glob("*")} if real.exists() else {}
    assert after == before


@pytest.mark.parametrize(
    ("given", "want"),
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        (
            "postgresql://u:p@h/db?sslmode=require&channel_binding=require",
            "postgresql+psycopg://u:p@h/db?sslmode=require&channel_binding=require",
        ),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_database_url_is_rewritten_for_psycopg(given, want):
    assert Settings(_env_file=None, database_url=given).database_url == want


def test_database_url_env_var_is_rewritten_too(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db?sslmode=require")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"
