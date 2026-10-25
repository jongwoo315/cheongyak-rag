# #71 공고 구조화 수집(L4) — 구현 계획

> **For Claude:** This plan is executed via /ralph-loop:ralph-loop in a detached orch session.
> You are ALREADY in the worktree, checked out on the feature branch. Do NOT switch branches,
> create another worktree, or use AskUserQuestion / any interactive prompt — the session is
> headless and cannot receive input, so always take the autonomous (recommended) default and
> keep working. Do NOT use superpowers:executing-plans or subagent-driven-development.
> Emit `<promise>RALPH_DONE</promise>` ONLY when every Done-criteria item and every Pre-PR check
> is genuinely true AND the PR has been created — never to escape the loop.
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

**Tier:** C · **Notion:** #71 · **설계:** `docs/plans/71-1022-design-notice-ingest.md` (먼저 읽을 것 — 착수 때 실측한 사실이 거기 있다)

## RESUME (2026-10-25)

- 이전 실행은 2026-10-23 00:29에 멈췄다. 원인 둘이다: odcloud가 00:01부터 약 28분간 빈 응답(`totalCount 0`)을 줬고, 그 턴 끝에
  다른 플러그인(ralph-wiggum)의 Stop 훅이 ralph 상태 파일을 지워 루프가 다시 시작되지 않았다. 우리 코드 문제가 아니다
- 2026-10-25 main 세션 확인: API 정상. `cond[RCRIT_PBLANC_DE::GTE]=2026-07-25` → `matchCount` 84
- 이미 있는 산출물 — 덮어쓰지 말고 테스트로 확인한다: Task 1 `0c7ed27` · Task 2 `c1e09ca` · Task 3 `3bdba59` · Task 4 `6baeb8c` ·
  Task 5-5 `58d49fa` · matchCount 0 방어 `9ec1432`. 실제 DB `cheongyak`은 0002까지 올라가 있고 두 테이블은 비어 있다.
  `runs/71/last_run.json`은 실패한 실행의 것이라 다시 쓴다
- 남은 것: Task 5의 1~4(수집 2회 · PK 집합 비교 · 리포트), `sc:reflect`, `superpowers:requesting-code-review`, Pre-PR 다시 실행,
  커밋, PR, Notion `PR` 칸
- 파일이 있다고 통과 기준을 채운 것이 아니다. 테스트와 실제 실행 결과로 확인한다
- **턴을 끝낼 때 마지막 메시지에 반드시 글자로 된 요약을 남긴다.** 마지막 메시지에 글자가 없으면 ralph-wiggum 훅이 상태 파일을 지운다

## jw 기준

청약홈 공고들을 sql 테이블에 성공적으로 적재한다

## 통과 기준

1. `uv run alembic upgrade head`가 `notices`·`notice_models` 테이블을 만든다(마이그레이션 `0002`). `alembic downgrade 0001` 뒤
   다시 `upgrade head`가 된다
2. `uv run python -m cheongyak_rag.ingest.notice [--months 3]`가 **모집공고일이 실행일 기준 최근 3개월인** APT 공고를
   `notices`에, 그 공고들의 주택형을 `notice_models`에 upsert하고, 호출 수 · 받은 행 수 · `matchCount` · 넣은/고친 행 수를
   출력하고 exit 0. 기간 경계는 실행일에서 달력 기준 3개월 전 같은 날(그 달에 그날이 없으면 말일)이다
3. `uv run python -m cheongyak_rag.ingest.notice_report`가 `docs/71-notice-ingest.md`를 쓴다. 첫 줄은 결론 한 문장
   (두 테이블 적재율, 재실행 결과, 주택형 없는 공고 수)
4. 같은 날 같은 수집 명령 두 번째 실행 뒤 두 테이블의 행 수와 PK 집합이 그대로이고 새로 들어간 행이 0이다
5. 서비스 키는 로그·예외 메시지·리포트·커밋 어디에도 나오지 않는다(테스트로 확인)
6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 공고가 테이블에 다 들어갔나.** 테이블별로 「이번 실행이 받은 PK 중 테이블에 있는 수」와 「같은 실행의 API
   `matchCount`」의 차이. `notices`는 날짜 조건을 건 상세 요청의 `matchCount`, `notice_models`는 공고별 주택형 요청의
   `matchCount` 합이다. **`totalCount`는 필터와 무관하게 전체 건수(2,909)가 나오므로 쓰지 않는다**:
   - 두 테이블 모두 0 → 통과
   - 1~3건(`notices`) 또는 1~20건(`notice_models`) 차이 → 빠진·남는 PK 목록과 원인을 리포트에 적는다
   - 그보다 크면 미완. 페이지 넘김이나 upsert를 고치고 다시 잰다
   - 그리고 통과 기준 4(재실행 뒤 행 수·PK 집합 그대로)가 깨지면 이 징후는 미완이다
   - 착수 때 실측(2026-10-22, 경계 2026-07-22): 공고 `matchCount` 81
2. **필드 보존.** `raw`의 키 집합이 그 행의 API 응답 키 집합과 같은 비율: 100% 통과 / 99~100% 다른 행 목록 / < 99% 저장 결함
3. **타입 변환 실패** (원문에 값이 있는데 타입 열이 NULL이 된 것): 0 통과 / 1~10 값 목록을 리포트에 / > 10 변환 규칙 결함
4. **주택형 없는 공고** (이번 실행이 받은 공고 중 주택형 행이 0개인 것): 0 정상 / 1~3건 공고번호 목록과 그 공고를 API로 다시
   조회한 결과를 리포트에 / > 3건 원인을 찾는다(조건 파라미터가 틀렸는지)
5. **명세 차이.** 응답 키 중 swagger(`https://infuser.odcloud.kr/api/stages/37000/api-docs`)에 없는 것과 그 반대: 개수와 이름을
   리포트에 적는다. 판정 구간 없음 — 기록만. 착수 때 실측: 상세는 응답 키와 swagger 모델이 49개로 같고, 주택형별은 둘 다 17개
6. **호출.** 한 번의 수집에서 API 호출 수(재시도 포함): ≤ 공고 수 + 10 정상(상세 1 + 공고별 주택형 1씩, 실측 기준 약 82) /
   그보다 크고 공고 수 × 2 이하 재시도 원인을 리포트에 / 공고 수 × 2 초과 페이지 넘김·재시도 결함. 두 번째 실행도 같은 범위여야
   한다(캐시 없음 — 매번 받는다). 요청 사이 0.1초 간격을 둔다
7. **키 노출.** 테스트에서 가짜 키 문자열이 출력·예외·리포트에 0회 나타나야 한다. 1회라도 나오면 버그

## 이번에 안 하는 것

설계 §이번에 안 하는 것을 그대로 따른다. 특히 APT 외 operation 6개, 공고문 PDF(#72), 주기 갱신, 임베딩은 하지 않는다.
`retrieval/`·`generate/` 파일은 건드리지 않는다.

## 작업 환경

- `.venv`는 이 워크트리 자체 것이다(이미 `uv sync` 했다)
- `.env`는 메인 repo 것의 심볼릭 링크다. `DATA_GO_KR_KEY`가 거기 있다(`export DATA_GO_KR_KEY=...` 줄 — python-dotenv가 읽는다).
  **Encoding 키라 `%`가 들어 있다.** 비어 있거나 401이 나면 HARD 오류로 멈춘다
- `data`는 메인 repo `data/`의 심볼릭 링크다. 이번 티켓은 `data/`에 쓰지 않는다. 지우지도, `git add`에 넣지도 말 것
- Postgres(`cheongyak-db`, 포트 5433)는 메인 repo에서 떠 있다. 워크트리에서 `docker compose up`하지 않는다.
  실제 적재 대상은 `.env`의 `DATABASE_URL`(DB `cheongyak`)이다. 이 DB에 `alembic upgrade head`를 돌리는 것은 이 티켓의 목적이다
- 새 의존성 넣지 않는다(`httpx`·`sqlalchemy`·`psycopg`·`alembic`이 이미 있다)
- **base 브랜치(main)를 작업 브랜치에 merge·rebase하지 않는다**
- `git add -A`·`git add .` 대신 파일을 지정해 add한다

## Tasks

Task 하나 = 커밋 하나. 각 Task는 테스트 먼저(TDD). HTTP는 `httpx.MockTransport`로 가짜를 쓴다(`tests/test_law_fetch.py` 방식).

### Task 1 — 테스트 DB

- `tests/conftest.py`에 `pg_test_url` fixture: `settings.database_url`의 DB 이름을 `cheongyak_test`로 **바꾼** URL
  (`sqlalchemy.engine.make_url(...).set(database="cheongyak_test")` — 문자열에 `_test`를 덧붙이지 않는다)
- 세션 시작 때 `cheongyak` DB 연결로 `cheongyak_test`가 없으면 `CREATE DATABASE`(autocommit), 그 URL로 `alembic upgrade head`,
  테스트마다 두 테이블 `TRUNCATE`. Postgres가 안 떠 있으면 `pytest.fail`(조용히 skip 금지)
- 테스트: fixture URL의 DB 이름이 `cheongyak_test`이고 실제 적재 DB와 다르다

### Task 2 — 마이그레이션 `0002`

- `alembic/versions/0002_notices.py`
- `notices`: PK `(house_manage_no text, pblanc_no text)`, `house_nm text not null`, `house_secd text`, `house_dtl_secd text`,
  `rent_secd text`, `subscrpt_area_code text`, `subscrpt_area_nm text`, `hssply_adres text`, `tot_suply_hshldco integer`,
  `rcrit_pblanc_de date`, `rcept_bgnde date`, `rcept_endde date`, `przwner_presnatn_de date`, `mvn_prearnge_ym text`,
  `speclt_rdn_earth_at boolean`, `mdat_trget_area_secd boolean`, `parcprc_uls_at boolean`, `public_house_earth_at boolean`,
  `pblanc_url text`, `raw jsonb not null`, `fetched_at timestamptz not null default now()`.
  인덱스: `rcrit_pblanc_de`, `subscrpt_area_nm`
- `notice_models`: PK `(house_manage_no, pblanc_no, model_no)`, `house_ty text`, `suply_ar numeric`, `suply_hshldco integer`,
  `spsply_hshldco integer`, `lttot_top_amount integer`(만원), `raw jsonb not null`, `fetched_at timestamptz not null default now()`.
  FK `(house_manage_no, pblanc_no) → notices ON DELETE CASCADE` (설계 §2)
- Y/N 열: `Y`→true, `N`→false, 그 밖의 값·빈 값→NULL. 날짜: `YYYY-MM-DD`만 받고 빈 값→NULL
- 테스트: upgrade 뒤 두 테이블 존재, downgrade `0001` 뒤 없음, 다시 upgrade

### Task 3 — 수집 (`ingest/notice.py`)

- `fetch_all(op, client, key, cond) -> tuple[list[dict], int, int]` — `perPage=1000`, 첫 응답의 **`matchCount`**로 페이지 수를
  정한다. 돌려주는 값: 행 · `matchCount` · 호출 수. `cond`는 `{"cond[RCRIT_PBLANC_DE::GTE]": "2026-07-22"}` 꼴.
  키는 `urllib.parse.unquote(key)`로 한 번 풀어 `params={"serviceKey": ...}`로 보낸다
- 순서: 상세(`getAPTLttotPblancDetail`)를 날짜 조건으로 받는다 → 공고마다 주택형(`getAPTLttotPblancMdl`)을
  `cond[HOUSE_MANAGE_NO::EQ]`·`cond[PBLANC_NO::EQ]`로 받는다 → 공고 upsert → 주택형 upsert (FK 때문에 이 순서)
- `since(today, months=3) -> date` — 달력 기준 N개월 전 같은 날, 그날이 없으면 말일. 표준 라이브러리만 쓴다
- 재시도: 429·5xx·연결 오류는 지수 대기(1·2·4·8초) 최대 4회. 401·403은 즉시 `NoticeApiError`(재시도 안 함).
  **예외 메시지와 로그에 키나 키가 든 URL을 넣지 않는다** — `law.py`의 `_snippet`처럼 가린다
- `to_notice_row(raw) / to_model_row(raw)` — 타입 변환. 실패하면 그 열만 NULL, 실패 수를 센다
- `upsert(engine, table, rows) -> tuple[int, int]` — `insert().on_conflict_do_update`, 넣은 수와 고친 수(`xmax = 0` 트릭이나 실행 전후
  PK 대조 중 단순한 쪽)
- CLI `main(argv)`: 두 operation을 받아 각 테이블에 넣고 통과 기준 2의 숫자를 출력. 실행 요약을 `runs/71/last_run.json`에 쓴다
  (호출 수 · matchCount · 받은 수 · 기간 경계 · 넣은/고친 수 · 변환 실패 · 시각). 키는 넣지 않는다
- `settings.data_go_kr_key`가 비면 exit 1과 함께 「DATA_GO_KR_KEY가 비어 있다」
- 테스트: 페이지 넘김(matchCount 2,500 → 3번 호출, totalCount는 무시) · 날짜 조건 파라미터가 요청에 실림 ·
  `since`(10-31 → 07-31, 05-31 → 02-28/29) · 공고별 주택형 조건 · 키 unquote · 429 재시도 · 401 즉시 실패 · 키가 예외 문자열에 없음 ·
  변환(빈 날짜·Y/N·형식이 다른 값) · upsert 두 번에 행 수 그대로 (테스트 DB)

### Task 4 — 리포트 (`ingest/notice_report.py`)

- DB와 `runs/71/last_run.json`, 저장된 swagger 사본을 읽어 `docs/71-notice-ingest.md`를 쓴다. swagger는 이 Task에서
  `https://infuser.odcloud.kr/api/stages/37000/api-docs`를 받아 `runs/71/swagger.json`으로 커밋한다(키 불필요)
- §1 지표 표 — 실패 징후 1~7의 측정값과 해당 구간을 나란히, 구간 문구는 plan 문장 그대로
- §2 테이블 요약 — 행 수, 모집공고일 최소·최대, 연도별 공고 수, 공급지역별 공고 수, 주택구분별 수
- §3 표본 5건 — 최근 공고 5건의 주요 열과 주택형 행
- §4 주택형 없는 공고 · 타입 변환 실패 · 명세 차이 목록
- 테스트: 가짜 데이터로 render 결과에 각 절과 구간 문구가 나온다

### Task 5 — 실제 실행

1. `uv run alembic upgrade head` (실제 DB `cheongyak`)
2. `uv run python -m cheongyak_rag.ingest.notice` 첫 실행 → 행 수 기록
3. 같은 명령 두 번째 실행 → 새로 들어간 행 0, 행 수 그대로. 두 실행 사이 PK 집합을 SQL로 비교해 리포트에 적는다
4. `uv run python -m cheongyak_rag.ingest.notice_report`
5. `docs/plans/0727-design-cheongyak-rag.md` §3 공고 표에서 「한국부동산원_APT분양정보 15061149」를
   「한국부동산원_청약홈 분양정보 조회 서비스 15098547」로 고치고 「카탈로그 ID 미검증」 문장을 「2026-10-22 확인」으로 바꾼다
   (그 외 문장은 건드리지 않는다)

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.ingest.notice` exit 0
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
   - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check`

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).

내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만 **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.

커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## Done criteria

- 통과 기준 1~6이 전부 참이고 실패 징후 1~7의 측정값이 리포트에 있다 (실패 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 push하고 PR을 만든다. base는 `main`
- PR 제목: `[#71] ingest: 청약홈 APT 공고·주택형을 notices 테이블에 적재`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 테이블별 행 수와
  matchCount, 재실행 결과). 그 아래 Summary / Changes / 실패 징후 1~7 측정값 표 / 수집 CLI 출력 / Notes
- PR을 만든 뒤 Notion #71 페이지(`3aa41e61-65c0-81df-8e73-fb75c317134b`)의 `PR` 프로퍼티에 PR URL을 넣는다
  (`NOTION_API_KEY`, `PATCH /v1/pages/{id}`, `Notion-Version: 2026-03-11`). `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
