# 주택청약 RAG

주택청약 공고별 **자격 요건을 요건 단위로 판정**하고 근거 조문을 인용하는 RAG 서비스.

설계 문서: [`docs/plans/0727-design-cheongyak-rag.md`](docs/plans/0727-design-cheongyak-rag.md)

## 판단 기록

구현은 AI 에이전트가 했다. 각 티켓의 통과 기준은 착수 전에 사람이 한 줄로 먼저 썼고,
PR마다 그 기준과 결과를 나란히 놓고 사람이 판정했다. 2026-10-01부터 기록한다.

티켓 1개 · 자동 기준 통과 1 · 착수 전 기준으로 반려 0 · 유보 0

기준과 결과가 갈린 티켓은 아직 없다. 전체 기록: [`docs/decisions.md`](docs/decisions.md)

## 로컬 실행

```bash
uv sync
cp .env.example .env          # 키 채우기
docker compose up -d          # Postgres + pgvector (호스트 5433)
uv run alembic upgrade head
uv run uvicorn cheongyak_rag.main:app --reload
```

`http://127.0.0.1:8000/health` 가 아래를 반환하면 정상:

```json
{ "status": "ok", "db": "ok", "pgvector": "ok" }
```

`pgvector: "missing"` 이면 마이그레이션이 안 돈 것.

## 검증

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 데이터 수집

```bash
uv run python -m cheongyak_rag.ingest.faq   # 국토부 주택청약 FAQ(2024-05) → data/processed/faq-20240529.jsonl
```

PDF는 `data/raw/faq-20240529.pdf`에 캐시된다. 실행 끝에 섹션 대조 리포트가 나온다.

## 메모

- **DB 포트는 5433.** 호스트에 이미 Postgres 가 5432 를 점유 중이라 컨테이너를 5433 으로 매핑했다.
- Alembic 은 `alembic.ini` 대신 `.env` 의 `DATABASE_URL` 을 단일 출처로 쓴다 (`alembic/env.py` 에서 주입).
