# #85 배포 — Vercel + Neon

jw 기준: 「vercel neon으로 배포가 성공하고, 배포된 사이트에서 주택청약 검색 및 조건 확인을 할 수 있다」

이 문서는 **배포 절차**와 **로컬 리허설 결과**다. 이 PR은 배포에 필요한 코드만 만들었다. 실제 배포와
배포 사이트 측정은 PR 뒤에 사람과 main 세션이 한다. 설계: `docs/plans/85-1109-design-deploy-vercel.md`

## 구성

```
브라우저
  │
  ▼
Vercel 프로젝트 ① web  (루트 web/, Next.js, 리전 sin1)
  │  서버에서만 API_BASE_URL로 호출
  ▼
Vercel 프로젝트 ② api  (루트 repo, FastAPI = Python 함수, 리전 sin1)
  │  DATABASE_URL (Neon 직접 연결)
  ▼
Neon Postgres 17 + pgvector  (싱가포르)
```

## 이 PR이 바꾼 것

| 바꾼 것 | 위치 | 이유 |
| --- | --- | --- |
| 캐시 위치를 `CACHE_DIR`로 바꾼다 | `src/cheongyak_rag/config.py` | 서버리스 함수는 `/tmp`만 쓸 수 있다(추정) |
| `DATABASE_URL`의 `postgres://`·`postgresql://`를 `postgresql+psycopg://`로 읽는다 | 같은 파일 | Neon·Vercel이 주는 값은 `postgresql://` 꼴이다 |
| 하루 판정 한도 | `api.py`, alembic `0006` (`verdict_daily_count`) | 주소가 공개되면 질의마다 LLM 비용이 든다 |
| 판정 잠금 대기 제한 | `api.py` | 앞 판정이 길면 뒤 질의가 함수 시간 제한까지 묶인다 |
| web→FastAPI 호출 시간 제한, JSON 아닌 본문 처리 | `web/app/api/verdict/[houseManageNo]/route.ts`, `web/components/VerdictForm.tsx` | Vercel이 300초에 끊으면 브라우저는 원인 없는 오류를 본다 |
| Vercel 설정 | `app.py`, `vercel.json`, `web/vercel.json`, `.python-version`, `.vercelignore`, `web/.vercelignore` | |
| Neon 적재 스크립트 | `src/cheongyak_rag/deploy_load.py` | |
| 배포 측정 모드 | `web/e2e/measure.spec.ts`, `src/cheongyak_rag/web_report.py` | |

- 하루 판정 한도를 넘으면 429 「오늘 판정 한도(N건)를 다 썼다. 내일 다시 시도해 달라」를 낸다. 없는 공고(404)·모순된 프로필(422)은 세지 않는다. 잠금 대기 시간 초과(503)와 판정 중 오류는 센다 — 세는 자리가 `run_traced` 앞이기 때문이다
- 한국 날짜는 `Asia/Seoul`(UTC+9, 서머타임 없음) 기준이다. 코드는 고정 오프셋을 쓴다(서버리스 이미지에 시간대 데이터가 없어도 돌게)

## 환경 변수

비밀 값 자체는 이 문서에 적지 않는다.

| 이름 | 어느 프로젝트 | 비밀 | 값 예시 |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | api | 예 | (OpenAI 대시보드의 키) |
| `DATABASE_URL` | api | 예 | `postgresql://<user>:<password>@<host>/<db>?sslmode=require` (Neon **직접 연결** 주소, pooler 아님) |
| `TRACE_HASH_KEY` | api | 예 | 임의의 긴 문자열. 비면 판정이 503이다 |
| `CACHE_DIR` | api | 아니오 | `/tmp/cheongyak-cache` |
| `VERDICT_DAILY_LIMIT` | api | 아니오 | `50` (기본 50) |
| `VERDICT_LOCK_TIMEOUT_S` | api | 아니오 | `60` (기본 60) |
| `OPENAI_EMBED_MODEL`·`OPENAI_GEN_MODEL`·`OPENAI_JUDGE_MODEL` | api | 아니오 | 기본값 그대로 두면 안 넣어도 된다 |
| `API_BASE_URL` | web | 아니오 | `https://<api 프로젝트>.vercel.app` |
| `VERDICT_TIMEOUT_MS` | web | 아니오 | `280000` (기본 280000. Vercel 함수 제한 300초 안쪽) |

- 새로 생긴 칸은 `CACHE_DIR`·`VERDICT_DAILY_LIMIT`·`VERDICT_LOCK_TIMEOUT_S`(`.env.example`)와 `VERDICT_TIMEOUT_MS`(`web/.env.example`)다. 측정용 `MEASURE_*`·`WEB_BASE_URL`은 배포 환경에 넣지 않는다(아래 §배포 사이트 측정)
- `LAW_OC`·`DATA_GO_KR_KEY`는 수집 CLI만 쓴다. 배포에는 필요 없다

## 배포 절차

### jw가 하는 단계 (계정·약관·결제·비밀 값)

1. Vercel 계정을 만든다(Hobby)
2. Vercel Marketplace에서 Neon을 붙여 Postgres를 만든다 — 리전 싱가포르, PG17. pgvector는 모든 플랜에서 쓸 수 있다
   - 직접 연결(pooler가 아닌) 주소를 복사해 둔다. 판정 흐름이 `SET LOCAL hnsw.*`를 쓰는데 pooler(PgBouncer transaction 모드)는 세션 `SET`을 지원하지 않는다
3. OpenAI 대시보드에서 사용 한도를 건다(코드 밖 안전장치)
4. 로컬 `.env`가 아니라 **셸 환경에서** 비밀 값을 준비한다 — `OPENAI_API_KEY`·`DATABASE_URL`(Neon 주소)·`TRACE_HASH_KEY`
5. Vercel 프로젝트 ② api에 위 표의 `api` 환경 변수를 넣는다. 비밀 값은 jw가 직접 입력 칸에 넣는다
6. `vercel login`

### main 세션이 하는 단계 (jw 확인 뒤)

7. Neon에 스키마와 데이터를 넣는다. 로컬 컨테이너(`cheongyak-db`)가 떠 있어야 한다
   ```bash
   uv run python -m cheongyak_rag.deploy_load --target-url "$NEON_DIRECT_URL"
   ```
   - ① 대상에 `alembic upgrade head` ② `docker exec cheongyak-db pg_dump --data-only`로 옮길 테이블만 뽑아 ③ `docker exec -i cheongyak-db psql`로 한 트랜잭션에 넣고 ④ 테이블마다 행 수를 원본·대상에서 세어 표로 찍는다. 하나라도 다르면 0이 아닌 코드로 끝난다
   - 옮기지 않는 테이블: `traces`(로컬 측정 기록)·`verdict_daily_count`·`alembic_version`. 배포 사이트는 빈 `traces`로 시작한다
   - 대상이 로컬 `cheongyak` DB와 같은 호스트·이름이면 거부한다. 대상에 이미 행이 있어도 거부한다(두 번 넣어 불어나는 것 방지). 주소는 출력에 찍지 않는다(호스트만)
8. api를 배포한다 (repo 루트)
   ```bash
   vercel link            # 프로젝트 ② api를 고른다
   vercel deploy --prod
   curl -s https://<api 주소>/health     # {"status":"ok","db":"ok","pgvector":"ok"}
   ```
9. web을 배포한다 (`web/`)
   ```bash
   cd web
   vercel link            # 프로젝트 ① web을 고른다
   vercel env add API_BASE_URL production      # 8단계의 api 주소
   vercel deploy --prod
   ```
10. 배포 사이트를 잰다(아래 §배포 사이트 측정) → 판단 로그
11. 배포 중 코드 결함이 나오면 같은 브랜치에 고치는 orch 태스크를 따로 보낸다

### 배포 때 확인할 것 (설계 열린 질문)

- Hobby에서 함수 리전 `sin1`을 고를 수 있나. 안 되면 함수 기본 리전(`iad1`)에 맞춰 Neon을 미국 동부로 만든다. 그 결정은 배포 때 jw가 하고 리포트에 적는다
- Vercel이 `src/` 아래 패키지를 어떻게 설치하나. 루트 `app.py`가 `src`를 `sys.path` 맨 앞에 넣어 어느 쪽이든 import된다
- 콜드 스타트(Kiwi 로드 + BM25 만들기)가 몇 초인가. 배포 측정의 첫 쌍 시간으로 본다

## 배포 사이트 측정

main 세션이 PR 뒤 그대로 복사해 쓴다. `<WEB>`은 web 주소, `<API>`는 api 주소다. 측정 디렉터리는 `runs/85/deploy`다.

```bash
# 1) 기대값 — 로컬 DB와 이전 측정 파일에서 만든다
uv run python -m cheongyak_rag.web_report before \
  --run-dir runs/85/deploy --report runs/85/deploy/report.md

# 2) 배포 사이트에서 공고 페이지 84개와 18쌍을 질의한다 (LLM을 실제로 부른다. 약 $0.9, 하루 판정 한도 50 안)
cd web && WEB_BASE_URL=<WEB> MEASURE_RUN_DIR=runs/85/deploy MEASURE_WAIT_MS=240000 \
  MEASURE_SHOT_DIR=runs/85/deploy/shots npx playwright test e2e/measure.spec.ts && cd ..

# 3) 계산 — 로컬 캐시·traces를 세지 않고 api /health(A)와 G2'를 쓴다
uv run python -m cheongyak_rag.web_report after --deploy --api-url <API> \
  --run-dir runs/85/deploy --report runs/85/deploy/report.md
```

- 배포 모드의 값: F(공고 페이지 84개 중 실패) · L(목록의 공고 링크 수) · A(api `/health`가 200이고 `db`·`pgvector`가 ok) · G1(240초 안에 결과가 안 뜬 쌍) · G2'(결과가 떴는데 **경로 키 집합 또는 체크리스트 항목 수**가 `runs/81` 답과 다른 쌍) · 판정값이 #81과 같은 쌍 수(구간 없음)
- 판정값을 G2'에서 뺀 이유는 아래 §리허설 징후 2의 값이 보여 준다: 캐시가 비면 LLM을 새로 불러 판정값이 바뀐다
- 하루 판정 한도가 50이라 18쌍을 두 번 측정하면 한도를 넘는다. 다시 측정하기 전에 한도를 올리거나 다음 날 한다

## 로컬 리허설 결과 (이 PR의 실패 징후)

배포 사이트가 아니라 **이 티켓 코드를 로컬 서버(FastAPI 8171 · Next.js 3184)에 띄워** 잰 값이다.

### 징후 1 — 배포 측정 모드로 18쌍

`--deploy --api-url http://127.0.0.1:8171`, `MEASURE_WAIT_MS=240000`, `MEASURE_RUN_DIR=runs/85/rehearsal`. 캐시는 기본 위치(`data/cache`)라 #84와 같은 답을 읽는다. 원본: `runs/85/rehearsal/last_run.json`·`report.md`.

| 값 | 측정 | 통과 기준 |
| --- | --- | --- |
| A. api `/health` | ok | ok |
| F. 공고 페이지 중 실패 | 0 / 84 | 0 |
| L. `/`의 공고 링크 수 | 84 | 84 |
| G1. 240초 안에 안 뜬 쌍 | 0 (다시 질의한 횟수 0) | 0 |
| G2'. 경로 키 집합·체크리스트 항목 수가 다른 쌍 | 0 | 0 |
| 판정값이 #81과 같은 쌍 | 18 / 18 | 18 |
| 구간 | **통과** | |

- 걸린 시간은 쌍마다 중앙값 1.8초, 최대 2.9초다(캐시를 읽는다)
- 측정 동안 `data/cache` 줄 수는 그대로다: 임베딩 3085 · 생성 135 · 판정 540 (측정 전과 후 같다)
- 하루 판정 한도 테이블에 2026-11-09 행이 생겼고 판정 수가 18이다(이 측정의 18쌍). 새 `traces` 행도 18개다

### 징후 2 — 캐시 없는 판정 시간 (시간 제한 값의 근거)

`CACHE_DIR`을 빈 임시 디렉터리로 두고 FastAPI를 다시 띄워, 공고 1건(더샵 분당하이스트 `2026000103`) × 프로필 3종 = 3쌍을 잰다. LLM을 실제로 불렀다. 측정 뒤 임시 디렉터리는 지웠다. 원본: `runs/85/cold/raw.json`·`last_run.json`.

| 쌍 | 걸린 시간 | 비고 |
| --- | --- | --- |
| `2026000103` × empty | 19.5초 | **첫 쌍** — Kiwi 로드·BM25 만들기 포함 |
| `2026000103` × partial | 17.5초 | |
| `2026000103` × full | 16.5초 | |

- 3쌍 모두 결과가 떴다. 가장 긴 쌍 19.5초 ≤ 200초 → **통과**
- 첫 쌍과 나머지의 차이는 약 2~3초다. 콜드 스타트(Kiwi 로드 + BM25 만들기) 비용으로 읽는다(첫 쌍이 가장 느린 것 하나로 본 값이라 추정)
- 이 측정으로 `verdict_lock_timeout_s` 기본값을 **60초**로 정했다: 빈 캐시 판정 최대 19.5초의 3배다. 앞 판정 둘이 끝나길 기다려도 되고, 기다린 뒤 자기 판정(약 20초)을 해도 Vercel 함수 제한(300초) 안이다. 한 판정이 평소보다 훨씬 오래 걸리면(LLM 지연) 뒤 질의가 503을 받는다
- 측정 전후 `data/cache` 줄 수: 임베딩 3085 → 3085 · 생성 135 → 135 · 판정 540 → 540 (그대로)
- 같이 나온 값: 판정값이 #81과 같은 쌍은 **1 / 3**이다. 나머지 2쌍(partial·full)은 캐시가 비어 LLM을 새로 불렀더니 전역 판정이 `NEED_INFO`로 나왔고 #81 답은 `UNVERIFIABLE`이다. 경로 키 집합과 체크리스트 항목 수는 3쌍 모두 같다(G2' 0). 이 값이 설계의 「배포 측정은 판정값을 비교하지 않는다」를 뒷받침한다
- 이 측정의 새 `traces` 행 3개가 로컬 DB에 남았다(판정 API를 통해 쓴 것)

### 징후 3 — 하루 판정 한도가 막는 시점

`tests/test_api_verdict.py` (실제 LLM 없음):

- `test_third_request_over_a_limit_of_two_is_429_and_never_reaches_the_flow` — 한도 2에서 3번째 질의가 429이고 `run_traced`는 2번만 불린다
- `test_404_and_422_requests_do_not_move_the_counter` — 없는 공고·모순된 프로필·알 수 없는 필드는 세지 않는다
- `test_a_new_korean_day_starts_a_new_count`, `test_today_kst_is_the_seoul_date_not_the_utc_date` — 한국 날짜가 바뀌면 새로 센다 (UTC 16:00 = 서울 다음 날 01:00)
- 구간: **통과**

## 이번에 안 하는 것

- 직접 산 도메인, IP별 제한, 로그인, GitHub 연동 자동 배포
- 캐시를 배포에 같이 싣기 — 싣으면 측정이 캐시만 읽어 실제 사용자가 타는 LLM 경로를 못 잰다
- 동시 판정 — 인스턴스 안에서는 한 번에 하나다. Vercel이 인스턴스를 늘리면 인스턴스끼리는 동시에 실행된다(잠금이 인스턴스 사이에는 안 걸린다). 캐시 파일이 인스턴스마다 따로라 문제는 없다
- 누군가 하루 판정 한도를 다 쓰면 그날은 데모가 판정을 못 한다 — 받아들인다
