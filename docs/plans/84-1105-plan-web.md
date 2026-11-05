# #84 화면 — 구현 계획

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
> budget while the picker still reads `working`.

**Tier:** C · **Notion:** #84 · **설계:** `docs/plans/84-1105-design-web.md` · **바꾸는 stub:** 「화면·HTTP API(#84)」

## jw 기준

next js 서버가 잘뜬다, 유저입장에서 청약별로 질의를 하고 결과를 확인할 수 있다

## 통과 기준

1. FastAPI에 HTTP API 3개가 있다: `GET /api/notices`(84건 요약 — 관리번호·공고번호·이름·지역·모집공고일·접수 시작·끝), `GET /api/notices/{house_manage_no}`(공고 칸 + 주택형 목록, 없으면 404), `POST /api/notices/{house_manage_no}/verdict`(본문 = 프로필 JSON, 안에서 `trace.run_traced`를 불러 `dataclasses.asdict(answer)`와 `trace_id`·`trace_error`를 돌려준다)
2. 판정 API 오류: 프로필 형식 오류(`ProfileError`·알 수 없는 칸) 422 · 없는 공고(`NoticeNotFound`) 404 · `TRACE_HASH_KEY` 없음 503(흐름을 돌리기 전) · `HardApiError` 503 · 행 쓰기만 실패하면 200에 응답과 `trace_error`. 판정 엔드포인트는 동기 함수(`def`)로 두어 FastAPI 스레드풀에서 실행된다 — `run_traced`가 동기 `Engine`을 쓴다
3. `web/`에 Next.js 앱(App Router, TypeScript)이 있다. `package.json`의 `next`·`react`·`react-dom`·`@playwright/test`는 정확한 버전으로 고정하고 `package-lock.json`을 커밋한다. `web/node_modules`·`web/.next`는 `.gitignore`에 넣는다. UI 라이브러리를 넣지 않는다(CSS 한 파일)
4. Next.js 서버는 FastAPI 주소를 환경 변수 `API_BASE_URL`로 받는다(기본값 `http://127.0.0.1:8000`). `web/.env.example`에 적는다. 브라우저는 FastAPI를 직접 부르지 않는다 — 판정 요청은 Next.js 라우트 핸들러(`web/app/api/verdict/[houseManageNo]/route.ts`)가 받아 FastAPI로 넘기고, FastAPI의 상태 코드와 본문을 그대로 돌려준다
5. `/`가 공고 84건을 모집공고일 순으로 보여 주고 각 공고 페이지로 링크한다. `/notices/[houseManageNo]`는 서버에서 그린다 — JS 없이 받은 HTML에 `<title>`(공고 이름 포함)·`<meta name="description">`·공고 정보(지역·주소·공급 세대·모집공고일·접수 기간·당첨자 발표일·청약홈 링크)·주택형 표가 들어 있다. 없는 관리번호는 404 페이지
6. 공고 페이지에 프로필 입력 칸 15개(`src/cheongyak_rag/profile.py` `Profile` 칸 전부). 참·거짓 칸은 「예 / 아니오 / 모름」, 날짜는 `<input type="date">`, 수는 숫자 칸. 빈 칸과 「모름」은 보내는 JSON에서 뺀다. 칸 이름표는 한국어, 각 칸에 `name` 속성으로 `Profile` 칸 이름을 단다(측정이 이 이름으로 칸을 찾는다). 입력 값은 `sessionStorage`에 두어 다른 공고 페이지에서도 채워져 있다. 서버·`localStorage`에는 두지 않는다
7. 결과 화면: 전역 판정 · 신청 가능한 경로(없으면 「없음」) · 경로별 판정 표(일반공급 + 특별공급 유형마다 한 행) · 가점 범위(`score.total`, 빠진 입력) · 체크리스트(항목마다 축 이름·질의·판정·이유·조건·필요한 정보·`note`·검색 밖 언급·오류, 근거는 `<details>`로 접고 제목·출처·링크·원문). 판정 중에는 「판정 중」을 띄우고 버튼을 막는다. API 오류는 상태 코드별 한국어 문구로 보여 준다. 측정이 값을 읽을 수 있게 아래 `data-testid`를 단다: `verdict-global`(전역 판정 값), `route-row`(경로 행, `data-route-key`에 경로 `key`, 안에 `route-verdict`), `checklist-item`(체크리스트 항목)
8. 폭 375px에서 가로 스크롤이 생기지 않는다(측정 스크립트가 공고 페이지 1개에서 `document.documentElement.scrollWidth <= 375`를 본다)
9. `uv run pytest -q` 전부 통과(API 테스트 포함), `uv run ruff check`·`uv run ruff format --check` 통과, `cd web && npm run build` 통과(타입 검사 포함)
10. `README.md` `## 로컬 실행`에 화면 띄우는 법(FastAPI 포트·`API_BASE_URL`·`npm ci`·`npm run dev`)을 더한다

## 실패 징후

### 1. jw 기준 앞 절 — Next.js 서버가 뜬다

`next build` → `next start`(FastAPI도 같이 띄운다) 뒤, 측정 코드가 실제 DB에서 공고 84건과 공고별 `notice_models` 행 수를 따로 읽어 기대값을 만든다. 그 다음 JS 없이 HTTP로 받는다.

- F. 공고 페이지 84개 중 실패한 수. 성공 = HTTP 200 · `<title>`에 그 공고 `house_nm`이 있다 · 주택형 표 행 수가 그 공고 `notice_models` 행 수와 같다
- L. `/` HTML에 있는 공고 페이지 링크 수(기대 84)
- 통과: F 0 · L 84
- 다시 잰다: 없음 — DB 읽기라 실행마다 같다
- 미완: F 1 이상 또는 L이 84가 아니다

### 2. jw 기준 뒤 절 — 유저 입장에서 청약별로 질의하고 결과를 확인한다

실제 브라우저(Playwright Chromium)로 18쌍(공고 6건 `runs/79/last_run.json`의 공고 목록 × 프로필 3종 `runs/80/profiles/empty.json`·`partial.json`·`full.json`)을 차례로 질의한다. 쌍마다: 공고 페이지를 열고 → 입력 칸을 그 프로필 JSON 값으로 채우고(JSON에 없거나 null인 칸은 빈 칸·「모름」) → 보내고 → 결과가 뜰 때까지 기다린다(쌍마다 120초). 쌍 사이에 `sessionStorage`를 비운다. 기대값은 `runs/81/last_run.json` `cells`에서 같은 (공고, 프로필) 쌍의 `answer`다 — 이 티켓 코드와 무관한 이전 측정 파일이다.

- G1. 120초 안에 결과가 안 뜬 쌍 수
- G2. 결과가 떴는데 기대값과 다른 쌍 수. 같다 = 셋 다 같다: 화면 `verdict-global` = `answer.verdict`(null은 화면에 「판정 없음」) · 화면 경로 행의 (`data-route-key`, `route-verdict`) 집합 = `answer.general` + `answer.special`의 (key, verdict) 집합 · 화면 `checklist-item` 수 = `len(answer.checklist)`
- 통과: G1 0 · G2 0
- 다시 잰다: G2 0이고 G1 1 이상. 그 쌍만 한 번 더 질의한다. 두 번째 값을 적고 첫 값도 같이 적는다
- 미완: G2 1 이상, 또는 다시 잰 뒤에도 G1 1 이상
- 같이 적는 값: 쌍마다 걸린 시간, 다른 쌍이 있으면 화면 값과 기대값 전문

### 3. 화면이 CLI와 같은 판정 흐름을 탔나 — LLM 호출 수와 trace 행

- H. 징후 2 측정 동안 생긴 LLM 호출 수 — 판정 캐시 `data/cache/verdict-gpt-5.4-mini.jsonl`과 임베딩 캐시 `data/cache/embed-text-embedding-3-small.jsonl`의 줄 수를 측정 전후로 센 차이. 판정 캐시 키는 프롬프트 전체라, 화면 입력이 JSON 프로필과 같은 `Profile`을 만들면 0이다
- T. 징후 2 측정 동안 실제 DB `traces`에 새로 생긴 행 수(측정 전 `max(id)` 뒤). 기대 18 — 재측정한 쌍이 있으면 18 + 재측정 수
- 통과: H 0 · T가 기대값과 같다
- 다시 잰다: 없음
- 미완: H 1 이상 또는 T가 기대값과 다르다. H가 1 이상이면 어느 칸이 JSON과 다르게 보내졌는지 찾아 리포트에 적는다. 프롬프트·#81 파일·캐시를 고쳐서 맞추지 않는다

## 범위 밖

- 요청 제한·비용 상한 — #85. 이번에는 로컬에서만 띄운다 <!-- style-exempt -->
- 질문 랭킹(B9b) — #82. 응답의 `questions`는 빈 목록 그대로
- 사이트맵·JSON-LD·OG 이미지 — #85(도메인이 생긴 뒤)
- 로그인·프로필 서버 저장
- 판정 정확도·프롬프트 — #75·#76·#143·#180·#181
- 판정 흐름(`verdict`·`aggregate`·`trace`) 코드 변경 — 이 티켓은 부르기만 한다

## Task

흐름은 이미 있다(CLI). Task 3에서 브라우저 → Next.js → FastAPI → `run_traced` → 화면이 처음 끝까지 이어진다. 그 뒤 Task가 화면을 채운다.

### Task 1 — 공고 조회 API

- `src/cheongyak_rag/api.py`(새 파일, `APIRouter`)에 `GET /api/notices`·`GET /api/notices/{house_manage_no}`. `main.py`가 라우터를 붙인다. 기존 `/health`는 그대로
- 동기 `Engine`(`sa.create_engine(settings.database_url)`)을 앱에 하나 두고 의존성으로 받는다 — 테스트가 갈아 끼운다
- 날짜는 ISO 글자, 주택형은 `model_no`·`house_ty`·`suply_ar`·`suply_hshldco`·`spsply_hshldco`·`lttot_top_amount`
- 테스트(테스트 DB `pg_engine` 방식, `TestClient`): 목록 행 수와 순서 · 상세 칸 · 주택형 수 · 없는 관리번호 404
- 커밋: `feature: #84 공고 조회 API를 더한다`

### Task 2 — 판정 API

- `POST /api/notices/{house_manage_no}/verdict` — 통과 기준 1·2. 임베더·OpenAI 클라이언트·캐시는 `verdict.main`과 같은 것(`Embedder`·`RetryingClient(make_client())`·`GenCache(cache_path_for(model))`)을 앱 시작 때 만들고 의존성으로 받는다. 모델은 `settings.openai_gen_model`
- 테스트(가짜 임베더·가짜 클라이언트, OpenAI 안 부름, 테스트 키는 고정 문자열): 정상 200 + `verdict`·`general`·`checklist`·`trace_id` · 실제로 `traces` 행 1개 · 알 수 없는 칸 422 · 날짜 형식 오류 422 · 없는 공고 404 · 키 없음 503이고 `traces` 행 0 · 행 쓰기 실패 흉내 → 200 + `trace_error`
- 커밋: `feature: #84 판정 API를 더한다`

### Task 3 — Next.js 앱 처음부터 끝까지

- `web/` 만들기(통과 기준 3·4). `/` 목록, `/notices/[houseManageNo]` SSR 공고 정보, 프로필 입력 칸 15개, 라우트 핸들러, 결과는 일단 전역 판정과 체크리스트 수만
- 여기서 브라우저로 공고 하나 × `runs/80/profiles/full.json` 값을 넣어 결과가 뜨는지 손으로(Playwright 한 번) 확인한다
- 커밋: `feature: #84 Next.js 공고 목록·공고 페이지·판정 요청을 잇는다`

### Task 4 — 결과 화면

- 통과 기준 7 전부. 판정값 다섯(`ELIGIBLE`·`CONDITIONAL`·`INELIGIBLE`·`NEED_INFO`·`UNVERIFIABLE`)은 영문 값과 한국어 풀이를 같이 보여 준다(`docs/concepts.md` 판정값 표의 뜻을 쓴다)
- 커밋: `feature: #84 판정 결과 화면을 그린다`

### Task 5 — 입력 유지와 좁은 폭

- 통과 기준 6의 `sessionStorage`, 통과 기준 8
- 커밋: `feature: #84 입력 값을 탭 안에서 유지한다`

### Task 6 — 측정 스크립트

- `web/e2e/measure.spec.ts`(Playwright)와 실제 DB에서 기대값을 읽는 파이썬 도우미(`src/cheongyak_rag/web_report.py` 또는 `scripts/`) — 징후 1·2·3을 잰다. 측정 코드는 화면 코드(`web/app`)를 import하지 않는다
- 결과를 `runs/84/last_run.json`에 쓰고 `docs/84-web.md` 리포트를 만든다. 리포트 맨 위에 징후 1~3의 측정값과 구간
- 결과 화면 스크린샷 2장을 `docs/84-web/`에 저장한다: 더샵 분당하이스트(`2026000103`) × `full`, 같은 공고 × `empty`. 전체 페이지(`fullPage: true`)
- 커밋: `test: #84 화면 측정 스크립트를 더한다`

### Task 7 — 실제 DB와 캐시로 측정

- FastAPI(포트 8171, `API_BASE_URL=http://127.0.0.1:8171`)와 `next start`(포트 3184)를 백그라운드로 띄우고 측정한다. 끝나면 둘 다 끈다
- 미완·다시 잰다가 나오면 징후 절에 적힌 대로 한다. 측정을 결과에 맞춰 고치지 않는다. 화면 코드가 통과 기준과 다른 곳만 고치고 다시 잰다. 그래도 미완이면 리포트를 그대로 커밋하고 PR 본문에 쓴다
- 측정으로 쌓인 `traces` 행은 지우지 않는다
- 커밋: `docs: #84 화면 측정 리포트`

### Task 8 — README

- 통과 기준 10
- 커밋: `docs: #84 README에 화면 띄우는 법을 더한다`

### Task 9 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`라 위 정규식에 안 걸린다. `config.py` 새 칸이 있으면 같이 적는다. `web/`의 `process.env.API_BASE_URL`과 `web/.env.example`을 적는다
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8171 &)`, 그리고 `cd web && npm run build && (API_BASE_URL=http://127.0.0.1:8171 timeout 60 npm run start -- -p 3184 &) ; sleep 10; curl -sf http://127.0.0.1:8171/health && curl -sf http://127.0.0.1:3184/ -o /dev/null && curl -sf http://127.0.0.1:3184/notices/2026000103 -o /dev/null && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171' ; pkill -f 'next start'`
> 3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `cd web && npm run build`
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).
>
> 내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만(다각도 finder + 후보별 독립 검증 CONFIRMED/PLAUSIBLE/REFUTED + failure_scenario 강제) **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.
>
> 커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다(`TRACE_HASH_KEY`는 이미 있다)
- `data/cache`의 캐시 파일을 지우거나 다시 쓰지 않는다. 판정 캐시는 append만 된다(이번 측정은 읽기만 하는 것이 기대값이다)
- 실제 DB의 `chunks`·`notices`·`notice_models`·`law_versions`를 쓰거나 지우지 않는다. `traces`에는 판정 API를 통해서만 쓴다. 마이그레이션은 없다
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다
- Node는 `/opt/homebrew/bin/node`(v26). 패키지 관리자는 `npm`. Playwright 브라우저는 `npx playwright install chromium`으로 받는다
- 다른 세션이 3000·8000 포트를 쓸 수 있다. 측정·Pre-PR은 8171·3184를 쓰고, 띄운 프로세스는 끝나면 끈다

## Done criteria

- 통과 기준 1~10이 전부 참이고 실패 징후 1~3의 측정값과 구간이 `docs/84-web.md`에 있다. 결과가 통과 구간이 아니어도 Task 7의 처리를 했으면 끝낸다
- `docs/concepts.md`: 이 티켓은 새 개념을 만들지 않는다. 고치지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. `git push -u origin feat/84-web`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#84] feature: 공고별 페이지에서 프로필을 넣고 판정 결과를 본다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(징후 1의 F·L과 구간, 징후 2의 G1·G2와 구간). 그 아래 Summary / Changes / 실패 징후 1~3 측정값 표 / 스크린샷 2장(`docs/84-web/` 파일을 브랜치 기준 GitHub 링크로) / Notes(설계 §정한 것의 결정, 새 환경 변수 `API_BASE_URL`)
- PR을 만든 뒤 Notion #84 페이지(`3aa41e61-65c0-81f8-82f3-e6740d1871ae`)의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81f8-82f3-e6740d1871ae -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
