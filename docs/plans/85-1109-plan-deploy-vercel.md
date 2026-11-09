# #85 배포 — Vercel + Neon 구현 계획

> **For Claude:** This plan is executed via /ralph-loop:ralph-loop in a detached orch session.
> You are ALREADY in the worktree, checked out on the feature branch. Do NOT switch branches,
> create another worktree, or use AskUserQuestion / any interactive prompt — the session is
> headless and cannot receive input, so always take the autonomous (recommended) default and
> keep working. Do NOT use superpowers:executing-plans or subagent-driven-development.
> Emit `<promise>RALPH_DONE</promise>` ONLY when every Done-criteria item and every Pre-PR check
> is genuinely true AND the PR has been created — never to escape the loop.
> Never write the promise tag in any other message, not even to say you will not emit it —
> the loop's stop hook can read an earlier message, so a mention ends the loop.
> RALPH_DONE means the work is finished, NOT that the result passed. If an honest measurement
> lands in a below-pass band of the plan (re-measure or 미완), and the plan step for that band has
> been carried out, write the band and the measured value verbatim in the report and at the top of
> the PR body, then emit RALPH_DONE. Judging the result is jw's call at the gate, not yours.
> Do not keep iterating to push a number over a threshold the plan's tasks no longer cover.
> Before emitting it, stop every background shell you started (TaskStop tool). A shell left
> running keeps the session in `bg` state, and orch never marks the step done.
> On a HARD, retry-proof API error (OpenAI insufficient_quota, 401/403, exhausted billing), STOP —
> do NOT emit RALPH_DONE, do NOT create a PR, do NOT spin retrying. It surfaces via the orch
> completion notification; a human fixes billing. (Transient TPM 429 is different — pace and retry.)
> A TRANSIENT error that stops being transient counts as HARD. If 429/529 keeps surfacing AND you
> have produced no commit and no file change for 20 minutes, STOP the same way. Waiting and
> spinning are indistinguishable in a headless loop — nobody is watching the screen, and the loop
> re-submits the prompt after every failed turn, so a server-side outage burns the whole iteration

**Tier:** C · **Notion:** #85 · **설계:** `docs/plans/85-1109-design-deploy-vercel.md` · **바꾸는 stub:** 「배포(#85)」

## jw 기준

vercel neon으로 배포가 성공하고, 배포된 사이트에서 주택청약 검색 및 조건 확인을 할 수 있다

## 이 루프의 범위

- **실제 배포는 이 루프가 하지 않는다.** Vercel·Neon 계정이 없고, 계정 만들기·로그인·비밀 값 입력은 사람이 한다. `vercel` CLI를 설치·실행하지 않는다. Neon에 접속하지 않는다
- 이 루프는 배포에 필요한 코드를 만들고, 배포 사이트를 잴 측정 코드를 로컬 서버에 미리 돌려 본다(리허설)
- jw 기준은 PR 뒤 main 세션이 실제 배포 사이트에서 잰다(설계 §배포 사이트에서 jw 기준을 재는 법). 그 결과는 이 루프의 완료 조건이 아니다

## 통과 기준

1. 캐시 위치를 설정 `cache_dir`(환경 변수 `CACHE_DIR`)로 바꿀 수 있다. 기본값은 지금 경로(`<repo>/data/cache`). 임베딩·생성·판정 캐시 셋이 모두 이 값을 따른다. 값이 바뀌면 그 디렉터리에 쓰고 `data/cache`는 건드리지 않는다
2. 설정이 `DATABASE_URL`의 `postgres://`·`postgresql://`를 `postgresql+psycopg://`로 바꿔 읽는다. 쿼리 문자열(`sslmode=require` 등)은 그대로 둔다. 이미 `postgresql+psycopg://`면 그대로
3. 하루 판정 한도
   - alembic `0006`이 테이블 하나를 만든다: 한국 날짜(`date`, PK) · 판정 수(`int`)
   - 설정 `verdict_daily_limit`(환경 변수 `VERDICT_DAILY_LIMIT`, 기본 50)
   - 판정 API는 404(없는 공고)·422(모순된 프로필) 검사 **뒤**, `run_traced` **전**에 그날 행을 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`으로 1 올린다. 올린 값이 한도를 넘으면 429와 「오늘 판정 한도(N건)를 다 썼다. 내일 다시 시도해 달라」를 낸다. 404·422는 세지 않는다
   - 한국 날짜는 `Asia/Seoul` 기준 오늘이다
4. `_LOCK`을 `acquire(timeout=...)`로 잡는다. 설정 `verdict_lock_timeout_s`(환경 변수 `VERDICT_LOCK_TIMEOUT_S`). 못 잡으면 503 「다른 판정이 진행 중이다. 잠시 뒤 다시 시도해 달라」. 기본값은 Task 1에서 잰 캐시 없는 판정 시간을 보고 정해 리포트에 근거를 적는다(240초를 넘지 않는다)
5. `web/app/api/verdict/[houseManageNo]/route.ts`
   - FastAPI 호출에 `AbortSignal.timeout(...)`. 값은 환경 변수 `VERDICT_TIMEOUT_MS`(기본 280000 — Vercel 함수 제한 300초 안쪽). `web/.env.example`에 적는다
   - 시간 초과면 504와 「판정이 너무 오래 걸려 끊었다. 잠시 뒤 다시 시도해 달라」, 연결 실패는 지금처럼 502. 두 경우 모두 `console.error`로 원인(오류 이름·메시지)을 남긴다
6. `web/components/VerdictForm.tsx`: 응답이 200이어도 본문이 JSON으로 안 읽히면 결과 대신 오류 문구를 보여 준다(지금은 렌더 중 예외)
7. Vercel 설정
   - 루트 `app.py`: `src`를 `sys.path` 앞에 넣고 `from cheongyak_rag.main import app`. Vercel이 루트 `app.py`의 `app`을 자동으로 찾는다
   - 루트 `vercel.json`: `regions: ["sin1"]`, `functions."app.py"`에 `maxDuration: 300`과 `excludeFiles`(`{web/**,tests/**,docs/**,runs/**,data/**,alembic/**}`)
   - `web/vercel.json`: `regions: ["sin1"]`
   - 루트 `.python-version`이 없으면 `3.12`로 만든다. 있으면 그대로
   - 루트 `.vercelignore`: `data/`, `runs/`, `docs/`, `tests/`, `web/`, `.venv/`. `web/.vercelignore`: `node_modules/`, `.next/`, `e2e/`
   - 로컬에서 `uv run python -c "import app; print(app.app.title)"`가 repo 루트에서 성공한다
8. Neon 적재 스크립트 `src/cheongyak_rag/deploy_load.py` (`python -m cheongyak_rag.deploy_load --target-url <URL>`)
   - 대상 URL의 DB 이름이 로컬 원본(`settings.database_url`의 DB)과 같은 호스트·이름이면 거부하고 끝낸다(원본 덮어쓰기 방지)
   - ① 대상에 `alembic upgrade head`(대상 URL로) ② 로컬 컨테이너에서 `docker exec cheongyak-db pg_dump --data-only`로 옮길 테이블만 뽑아 ③ `docker exec -i cheongyak-db psql <대상 URL>`로 넣는다 ④ 테이블마다 행 수를 원본·대상에서 세어 표로 찍고 하나라도 다르면 0이 아닌 코드로 끝낸다
   - 옮길 테이블은 `traces`·하루 판정 한도 테이블·`alembic_version`을 뺀 전부다. 목록을 코드에 고정하지 말고 원본 `information_schema`에서 읽어 뺀다
   - 대상에 이미 행이 있으면 거부한다(두 번 넣어 행이 불어나는 것 방지). `--target-url`은 출력에 그대로 찍지 않는다(호스트만 찍는다)
   - 테스트: 같은 컨테이너에 임시 DB(`cheongyak_test_load_<pid>`)를 만들어 대상으로 쓰고, 행 수가 원본과 같은지 확인한 뒤 지운다. 원본 DB에는 읽기만 한다
9. 배포 측정 모드
   - `web/e2e/measure.spec.ts`: 측정 디렉터리(`MEASURE_RUN_DIR`, 기본 `runs/84`)·대기 시간(`MEASURE_WAIT_MS`, 기본 120000)·스크린샷 디렉터리(`MEASURE_SHOT_DIR`, 기본 `docs/84-web`)를 환경 변수로 받는다. 기본값이면 #84와 똑같이 동작한다
   - `web_report.py`: `before`/`after`에 `--run-dir`와 `--deploy`를 더한다. `--deploy`면 H·T(캐시 줄 수·`traces` 행 수)를 세지 않고, 대신 `--api-url`로 api `/health`를 불러 A를 적고, G2 대신 G2'(설계 정의 — 경로 키 집합·체크리스트 항목 수만 비교)를 계산하고 판정값이 #81과 같은 쌍 수를 같이 적는다. 리포트는 `--report`(기본 `docs/84-web.md`) 경로에 쓴다
   - 배포 측정 명령 한 벌을 `docs/85-deploy.md` §배포 사이트 측정에 그대로 적는다(main 세션이 PR 뒤 복사해 쓴다)
10. `docs/85-deploy.md`: 배포 절차(설계 §단계별 담당 순서대로 — jw 단계와 main 단계를 나눠 명령까지), 넣을 환경 변수 표(이름 · 어느 프로젝트 · 비밀 여부 · 값 예시. 비밀 값 자체는 적지 않는다), 로컬 리허설 결과(아래 실패 징후 1·2). README에 `### 배포` 절(3~6줄, `docs/85-deploy.md` 링크)
11. `.env.example`에 `CACHE_DIR`·`VERDICT_DAILY_LIMIT`·`VERDICT_LOCK_TIMEOUT_S`를 주석과 함께 더한다. 실제 `.env`는 고치지 않는다
12. `uv run pytest -q`·`uv run ruff check`·`uv run ruff format --check`·`cd web && npm run build` 통과

## 실패 징후

### 1. jw 기준 리허설 — 로컬 서버에서 돌린 배포 측정

이 티켓 코드로 로컬 FastAPI(8171)·Next.js(3184)를 띄우고, **배포 측정 모드**(`--deploy`, `--api-url http://127.0.0.1:8171`, `MEASURE_WAIT_MS=240000`, `MEASURE_RUN_DIR=runs/85/rehearsal`)로 18쌍을 잰다. 캐시는 기본 위치(`data/cache`)라 #84와 같은 답을 읽는다.

- A(api `/health` ok) · F · L · G1 · G2' 와, 같이 적는 값(판정값이 #81과 같은 쌍 수)
- 통과: A ok · F 0 · L 84 · G1 0 · G2' 0 · 판정값이 #81과 같은 쌍 18
- 다시 잰다: 없음 — 캐시를 읽어 실행마다 같다
- 미완: 그 밖. 측정 코드나 이번 변경이 #84 동작을 바꾼 것이다. 원인을 리포트에 적는다

### 2. 캐시 없는 판정 시간 — 시간 제한 값의 근거

`CACHE_DIR`을 빈 임시 디렉터리(`/tmp/cheongyak-85-cold-<pid>`)로 두고 FastAPI를 다시 띄운 뒤, 같은 측정을 공고 1건 × 프로필 3종 = 3쌍만 돌린다(`runs/85/cold`). LLM을 실제로 부른다(3쌍 × 약 $0.05). 끝나면 그 임시 디렉터리를 지운다. `data/cache`는 그대로여야 한다(줄 수를 측정 전후로 적는다).

- 쌍마다 걸린 시간 · 첫 쌍(Kiwi 로드·BM25 만들기 포함) 시간
- 통과: 3쌍 모두 결과가 뜨고 가장 긴 쌍이 200초 이하
- 다시 잰다: 200초 초과 240초 이하. 한 번 더 재서 두 값을 적는다
- 미완: 결과가 안 뜬 쌍이 있거나 240초 초과. Vercel 함수 제한(300초) 안에 못 끝날 수 있다는 뜻이다. 시간 제한 값을 늘려 맞추지 말고 리포트에 적는다
- 이 값으로 통과 기준 4의 `verdict_lock_timeout_s` 기본값을 정한다

### 3. 하루 판정 한도가 막는 시점

테스트로 잰다(실제 LLM 없음). 한도 2로 두고 판정 요청 3번 → 앞 2번은 흐름을 타고 3번째는 429이며 `run_traced`가 불리지 않는다. 없는 공고·모순된 프로필 요청은 카운터를 올리지 않는다.

- 통과: 위 테스트가 있고 통과
- 미완: 그 밖

## 범위 밖

- 실제 배포, Vercel·Neon 계정, 비밀 값 입력, `vercel` CLI — PR 뒤 jw와 main 세션
- 직접 산 도메인, IP별 요청 제한, 로그인, GitHub 연동 자동 배포
- 판정 흐름(`retrieval/`·`generate/`·`trace.py`) 로직 변경. 캐시 경로를 설정에서 읽게 바꾸는 것만 한다
- `docs/concepts.md` 개념 표 — 새 목록 개념이 없다

## Task

1. **캐시 위치 설정 + DB 주소 읽기** — 통과 기준 1·2. 테스트 먼저(설정 단위 테스트, 임시 `CACHE_DIR`에 캐시가 쓰이는지). 그 다음 실패 징후 2를 잰다(빈 캐시 3쌍) — 이 값이 Task 3의 기본값 근거다
2. **하루 판정 한도** — 통과 기준 3, 실패 징후 3. alembic `0006`, 테스트 DB에서 upgrade → downgrade → upgrade 테스트
   - 로컬 실제 DB에도 `alembic upgrade head`로 이 테이블을 만든다(Pre-PR 서버 기동에 필요). 다른 테이블은 안 바뀐다
3. **잠금 대기 제한 + 화면 쪽 시간 제한·JSON 아닌 본문** — 통과 기준 4·5·6. 파이썬 테스트로 잠금 503, 웹은 `npm run build`
4. **Vercel 설정 파일** — 통과 기준 7
5. **Neon 적재 스크립트** — 통과 기준 8
6. **배포 측정 모드 + 리허설** — 통과 기준 9, 실패 징후 1. 리허설 결과를 `docs/85-deploy.md`에 쓴다
7. **문서** — 통과 기준 10·11. 그 다음 Pre-PR, PR

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`라 위 정규식에 안 걸린다. `config.py` 새 칸(`cache_dir`·`verdict_daily_limit`·`verdict_lock_timeout_s`)과 `web/`의 `process.env.VERDICT_TIMEOUT_MS`·`MEASURE_*`를 적는다. `.env.example`·`web/.env.example`과 대조한다
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS).
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8171 &)`, 그리고 `cd web && npm run build && (API_BASE_URL=http://127.0.0.1:8171 timeout 60 npm run start -- -p 3184 &) ; sleep 10; curl -sf http://127.0.0.1:8171/health && curl -sf http://127.0.0.1:3184/ -o /dev/null && curl -sf http://127.0.0.1:3184/notices/2026000103 -o /dev/null && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171' ; pkill -f 'next start'`
>    - 추가: repo 루트에서 `uv run python -c "import app; print(app.app.title)"`
> 3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `cd web && npm run build`
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- `data/cache`의 캐시 파일을 지우거나 다시 쓰지 않는다. 판정 캐시는 append만 된다. 실패 징후 2는 반드시 빈 임시 `CACHE_DIR`로 잰다
- 실제 DB의 `chunks`·`notices`·`notice_models`·`law_versions`·`notice_law_versions`를 쓰거나 지우지 않는다. `traces`에는 판정 API를 통해서만 쓴다. 실제 DB에 하는 스키마 변경은 `alembic upgrade head`로 하루 판정 한도 테이블을 더하는 것 하나뿐이다
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다
- Node는 `/opt/homebrew/bin/node`. 패키지 관리자는 `npm`. 새 npm 패키지를 넣지 않는다
- 다른 세션이 3000·8000 포트를 쓸 수 있다. 측정·Pre-PR은 8171·3184를 쓰고, 띄운 프로세스는 끝나면 끈다
- 인터넷의 Vercel·Neon에 접속하지 않는다. `vercel`·`neonctl`을 설치하지 않는다

## Done criteria

- 통과 기준 1~12가 전부 참이고, 실패 징후 1~3의 측정값과 구간이 `docs/85-deploy.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `docs/concepts.md` `## 용어` 표에 main 세션이 이미 넣은 「하루 판정 한도」 행을 쓴다. 루프는 용어 행을 더하지 않는다. 개념 표는 고치지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. `git push -u origin feat/85-deploy-vercel`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#85] feature: Vercel + Neon 배포 준비 — 서버리스 대응과 적재·측정 스크립트`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 「배포 사이트 측정은 PR 뒤 main 세션이 한다. 아래는 로컬 리허설 값」 + 실패 징후 1·2의 값과 구간. 그 아래 Summary / Changes / Notes(새 환경 변수 표, 배포 절차 링크 `docs/85-deploy.md`, 사람이 할 단계 목록)
- PR을 만든 뒤 Notion #85 페이지(`3aa41e61-65c0-8116-8ea8-f95c9501d39a`)의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-8116-8ea8-f95c9501d39a -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
