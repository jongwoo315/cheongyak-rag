from pydantic_settings import BaseSettings, SettingsConfigDict


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

    log_level: str = "INFO"


settings = Settings()
