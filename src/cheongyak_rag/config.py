from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI — 임베딩 + 답 생성 + 판정 LLM
    openai_api_key: str = ""
    openai_embed_model: str = "text-embedding-3-small"
    openai_gen_model: str = "gpt-5.4-mini"
    openai_judge_model: str = "gpt-5.6-sol"

    # Postgres (pgvector)
    database_url: str = "postgresql+psycopg://cheongyak:cheongyak@localhost:5433/cheongyak"

    # 공공 API
    law_oc: str = ""
    data_go_kr_key: str = ""

    # trace — 프로필 해시(HMAC) 비밀 키. 비어 있으면 판정 CLI가 흐름 전에 멈춘다
    trace_hash_key: str = ""

    # 배포 (#85) — 임베딩·생성·판정 캐시 위치. 서버리스는 /tmp만 쓸 수 있다
    cache_dir: Path = REPO / "data" / "cache"
    # 하루 판정 한도. 한국 날짜(Asia/Seoul) 기준이고 404·422는 세지 않는다
    verdict_daily_limit: int = 50
    # 판정 잠금을 기다리는 시간(초). 넘으면 503. 빈 캐시 판정 최대 19.5초(첫 쌍, Kiwi 로드 포함)의
    # 3배다. 앞 판정 둘 뒤까지 기다리고, 기다린 뒤 자기 판정을 해도 함수 제한(300초) 안이다
    verdict_lock_timeout_s: float = 60.0

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Neon·Vercel이 주는 `postgres://`·`postgresql://`를 psycopg 드라이버 꼴로 바꾼다."""
        for old in ("postgres://", "postgresql://"):
            if v.startswith(old):
                return "postgresql+psycopg://" + v[len(old) :]
        return v


settings = Settings()
