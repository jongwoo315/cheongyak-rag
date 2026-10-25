# 주택청약 RAG

주택청약 공고별 **자격 요건을 요건 단위로 판정**하고 근거 조문을 인용하는 RAG 서비스.

설계 문서: [`docs/plans/0727-design-cheongyak-rag.md`](docs/plans/0727-design-cheongyak-rag.md)

## 판단 기록

구현은 AI 에이전트가 했다. 각 티켓의 통과 기준은 착수 전에 사람이 한 줄로 먼저 썼고,
PR마다 그 기준과 결과를 나란히 놓고 사람이 판정했다. 2026-10-01부터 기록한다.

티켓 7개 · 자동 기준 통과 4 · 착수 전 기준으로 반려 2 · 유보 2

기준과 결과가 갈린 티켓:

| 티켓 | 착수 전 기준 | 자동 기준 | 판정 | 이유 |
| --- | --- | --- | --- | --- |
| #69 법령 수집 | api키가 정상적으로 작동한다, 규칙 조문을 제대로 파싱한다 | 6/6 통과, 조문 텍스트 누락·중복 0 | 반려 | 현행 규칙에 없는 조를 인용하거나 개정 날짜 이후 조를 인용한 게 전체 커버가 안된다. 조 기준을 좀 더 완화하는 식의 변경이 필요해보인다 |
| #69 재판정 | api키가 정상적으로 작동한다, 규칙 조문을 제대로 파싱한다 | 6/6 통과, FAQ 인용 182쌍 중 커버 142 | 유보 | 조문은 모두 파싱했고 실패징후 없음, faq거 커버하지 못한 40쌍은 추후 티켓에서 처리 (후속 #135) |
| #131 dense vs hybrid 검색 | dense, hybrid 비교가 잘 이루어지고 이해가 된다 | 7/7 통과, 점검 run BM25 19/20 · dense 17/20 (기준 20 · 18) | 유보 | recall값이 각 유의미하게 차이가 있다(신뢰구간 값도 포함). 실패 징후로 나타난 것은 추후 티켓으로 처리한다 (후속 #138) |
| #138 놓친 검색 다시 보기 | 티켓131에서 놓친 검색을 개선된 청킹으로 찾을 수 있다 | 5/6 통과(6번은 DB 미기동으로 test_health 실패), 놓친 20문항 중 찾음 4~8 · 맞힌 103문항 중 놓침 7~18 | 반려 | 검색이 전혀 개선되지 않음 |

전체 기록: [`docs/decisions.md`](docs/decisions.md)

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

```bash
uv run python -m cheongyak_rag.ingest.law   # 법제처 「주택공급에 관한 규칙」 현행 → data/processed/law-008243-<시행일>.jsonl
```

`.env`의 `LAW_OC`(법제처 OPEN API 인증값)가 필요하다. 비어 있으면 exit 1로 멈춘다. 본문은 `data/raw/`에 캐시되고 검색은 매번 한다. 실행 끝에 원본 JSON 대조 리포트(누락·중복, 조문·항·호·목 개수)가 나오고, 대조에 걸리면 이전 JSONL을 덮어쓰지 않는다. FAQ JSONL이 있으면 FAQ 인용과 현행 법령 대조도 같이 나온다.

## 메모

- **DB 포트는 5433.** 호스트에 이미 Postgres 가 5432 를 점유 중이라 컨테이너를 5433 으로 매핑했다.
- Alembic 은 `alembic.ini` 대신 `.env` 의 `DATABASE_URL` 을 단일 출처로 쓴다 (`alembic/env.py` 에서 주입).
