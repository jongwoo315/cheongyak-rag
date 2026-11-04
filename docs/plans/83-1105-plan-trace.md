# #83 trace 저장 — 구현 계획

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
>
> **턴을 끝낼 때 마지막 메시지에 반드시 글자로 된 요약을 남긴다.** 글자 없이 도구 호출로만 끝난 턴은 ralph 상태 파일이
> 지워져 루프가 멈춘다(#71에서 실제로 멈췄다).

**Tier:** C · **Notion:** #83 · **설계:** `docs/plans/83-1105-design-trace.md`(먼저 읽을 것 — 저장 모양·해시·가리기·실패 행 결정, `traces` 칸, 측정 방법) · **바탕 설계:** `docs/plans/0727-design-cheongyak-rag.md` §1(23행)·§6 · **앞 티켓:** #81 `src/cheongyak_rag/generate/aggregate.py`·`aggregate_report.py`, #80 `src/cheongyak_rag/generate/verdict.py`

**흐름:** 판정 흐름은 #81에서 B9 응답까지 이어졌다. 이 티켓이 바꾸는 stub은 trace다(#81까지 자리 없음). B9 뒤에 행 하나를 쓴다. B9b 질문 랭킹(#82)·화면(#84)은 그대로 남는다.

## jw 기준

질의 한 건이 판정 흐름을 지나간 기록을 DB 테이블에 한 행씩 쌓는다

(Claude가 trace를 설명한 문장을 jw가 그대로 기준으로 골랐다)

## 통과 기준

1. `alembic/versions/0005_traces.py`가 설계 §`traces` 칸 그대로 `traces` 테이블과 인덱스 3개를 만든다. downgrade가 테이블을 지운다
2. `src/cheongyak_rag/trace.py`(새 파일)에 `run_traced`가 있다 — `verdict.judge` → `aggregate.build_answer` → `traces` 행 쓰기. 흐름 중간 예외에도 `status='error'` 행을 쓰고 예외를 다시 올린다. 행 쓰기가 실패하면 응답은 그대로 돌려주고 실패 사실을 같이 돌려준다
3. `profile_hash`는 HMAC-SHA256(`TRACE_HASH_KEY`, `Profile.to_dict()`를 `sort_keys=True`로 직렬화한 JSON) 16진수다. 키는 `config.Settings.trace_hash_key`(환경 변수 `TRACE_HASH_KEY`)이고 `.env.example`에 빈 값으로 둔다. 키가 비어 있으면 흐름을 돌리기 전에 예외
4. 저장하는 모든 글자(`steps`·`answer`·`error`)에서 그 질의 프로필의 문자열 값이 글자 그대로 나오면 `[프로필 값]`으로 바꾼다. 응답(반환값)은 바꾸지 않는다 — 저장할 때만 가린다
5. `uv run python -m cheongyak_rag.generate.verdict <공고> --profile <json>`가 `run_traced`를 부른다. 출력은 지금과 같다. 키가 없으면 exit 2와 「`TRACE_HASH_KEY`가 없다」. 행 쓰기 실패면 응답을 출력한 뒤 stderr에 알리고 exit 1
6. `--report`가 아래 실패 징후 1~3을 재고 `docs/83-trace.md`·`runs/83/last_run.json`을 쓴다. **징후 1 또는 2가 미완이면 exit 1**
7. system 프롬프트(`SYSTEM`)·user 메시지 조립·`REQUIRED_FIELDS`·B8 규칙·B9 응답 칸을 바꾸지 않는다. 리포트의 `system_sha`가 `92f338a4`다
8. `docs/concepts.md`에 두 절을 더한다: (가) **경로** — 일반공급 경로 1개(켜진 일반 축 5개 `GENERAL_AXES`를 합친다) + 특별공급 유형별 경로(일반 축 + 소득·자산 축 + 그 유형 질의), 정의는 `src/cheongyak_rag/generate/aggregate.py`의 `aggregate`·`GENERAL_AXES`(줄 번호), 만든 티켓 #81. 전역 판정 = 일반공급 경로 판정, 신청 가능한 경로 = `ELIGIBLE`·`CONDITIONAL`인 경로. (나) **trace 상태 2개** — `ok`·`error`와 뜻, 정의 위치, 만든 티켓 #83. `## 용어` 절은 main 세션이 이미 써 두었다 — 고치지 않는다
9. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

표본(설계 §측정): #81과 같은 공고 6건(`runs/79/last_run.json`) × 프로필 3종(`runs/80/profiles/`) 18쌍 + 없는 관리번호 1건(`0000000000`) + 꽉 찬 프로필 × 더샵 분당하이스트(`2026000103`) 한 번 더 = 질의 20건. 이 20건을 `run_traced`로 돌린다. baseline 없음 — `traces`가 이번에 처음 생긴다. 다음 티켓의 기준이 된다.

### 1. jw 기준 — 질의 한 건이 한 행씩 쌓이는가

- 잴 것:
  - A. 질의 수(20)와 측정 전 `max(id)` 뒤로 새로 생긴 행 수의 차이(절댓값)
  - B. 새 행 중 그 질의와 맞지 않는 행 수. 맞는다는 것은 넷 다 참인 것이다: `house_manage_no`가 요청값과 같다 · `status`가 결과(응답이 나왔으면 `ok`, 예외면 `error`)와 같다 · `answer`가 측정 코드가 반환 응답에 따로 가리기를 해서 만든 JSON과 같다(`error` 행은 `answer`가 null) · `steps`의 하위 질의 수가 응답 체크리스트 수와 같다
- 통과: A 0 · B 0
- 다시 잰다: 없음 — 행 쓰기는 결정론적이라 1 이상이면 코드나 측정이 틀린 것이다
- 미완: A 또는 B가 1 이상
- 같이 적는 값: `status` 분포(기대값 `ok` 19 · `error` 1), 실패 행의 `error` 글자, 행당 크기(`pg_column_size(t.*)`) 중앙값·최대, 질의당 걸린 시간 중앙값

### 2. 프로필 원본을 남기지 않는가

- 잴 것:
  - C. 새 행 전체(행을 JSON으로 직렬화)에 그 질의 프로필의 문자열 값이 ISO 꼴(`2012-05-20`) 그대로 나온 행 수
  - D. 같은 날짜가 다른 꼴(`2012년 5월 20일`·`2012년 05월 20일`·`2012.05.20`·`2012/05/20`)로 나온 행 수
  - E. 해시 검사에 걸린 행 수: 같은 프로필 두 질의의 해시가 다르다 · 프로필 3종 해시가 서로 겹친다 · 해시가 키 없는 SHA-256(같은 JSON)과 같다 · 64자 16진수가 아니다
- 통과: C 0 · D 0 · E 0
- 다시 잰다: C 0 · E 0인데 D가 1 이상 — 가리기가 놓친 꼴이다. 리포트에 그 행과 꼴을 적고, 가리기가 그 꼴도 잡게 고친 뒤 한 번 다시 잰다
- 미완: C 또는 E가 1 이상, 또는 다시 잰 뒤에도 D가 1 이상
- 같이 적는 값: 가린 횟수(행마다·전체), 파생값(`\d+년\s?\d+개?월\s?\d+일` 꼴 기간) 나온 행 수 — 판정하지 않는다(설계 §이번에 안 하는 것), 착수 때 main 세션이 #81 측정에서 센 값(LLM 이유 135개 중 프로필 날짜를 그대로 적은 것 10개)

### 3. 같은 응답을 읽었나 — 호출 수

- 잴 것: 첫 실행 LLM 호출 수(캐시 제외), 같은 명령 두 번째 실행 호출 수, 18쌍의 하위 질의 최종 판정 분포가 #81 측정(`runs/81/last_run.json`)과 칸마다 같은지
- 통과: 둘 다 0 · 분포 같음
- 다시 잰다: 첫 실행 1~3. 캐시 키가 왜 달라졌는지 리포트에 적는다
- 미완: 첫 실행 4 이상 또는 분포가 다름

## 이번에 안 하는 것

설계 §이번에 안 하는 것 그대로 — 파생값 가리기, 측정 리포트가 행을 쓰게 하기, trace 화면·조회 API(#84), 행 보존 기간(#85 뒤), Langfuse, 판정 정확도·프롬프트(#75·#76·#143).

## Tasks

### Task 1 — `traces` 마이그레이션

- `alembic/versions/0005_traces.py`(down_revision `0004`). 칸·인덱스는 설계 §`traces` 칸 그대로
- `tests/conftest.py` `pg_engine`의 `TRUNCATE`에 `traces`를 더한다
- 테스트: 테스트 DB에서 upgrade 뒤 칸 이름·타입·null 가능 여부·인덱스 3개, downgrade 뒤 테이블 없음(`tests/test_chunks_migration.py` 방식)
- 커밋: `add: #83 trace 테이블 마이그레이션을 더한다`

### Task 2 — `trace.py`

- `profile_hash(profile, key) -> str`, `mask(obj, profile) -> obj`(dict·list·str를 따라 내려가며 프로필 문자열 값을 `[프로필 값]`으로), `steps(...) -> dict`(설계 §`steps`), `write(engine, row) -> int`
- `run_traced(engine, embedder, client, model, house_manage_no, profile, pblanc_no=None, cache=None, *, key) -> Traced`. `Traced`는 `notice`·`plans`·`verdicts`·`answer`·`trace_id`·`trace_error`를 갖는다. 흐름 중 예외면 `error` 행을 쓰고 다시 올린다. 행 쓰기 실패(`SQLAlchemyError`)는 `trace_error`에 담아 돌려준다
- `config.Settings.trace_hash_key: str = ""`, `.env.example`에 `TRACE_HASH_KEY=` 한 줄과 주석(프로필 해시용 비밀 키, 임의 긴 문자열)
- 테스트(테스트 DB, 가짜 판정·가짜 클라이언트, OpenAI 안 부름): 같은 프로필 같은 해시 · 칸 하나 다르면 다른 해시 · 키 다르면 다른 해시 · 키 없으면 예외 · 이유에 프로필 날짜가 든 판정 → 저장된 행에 그 날짜 없음, 반환 응답에는 그대로 · 없는 공고 → `error` 행 1개 + 예외 다시 올림 · 정상 → `ok` 행 1개, `answer`·`verdict`·`steps` 하위 질의 수 · 행 쓰기 실패를 흉내 내면 응답과 `trace_error`가 같이 돌아옴
- 커밋: `feature: #83 질의 한 건을 trace 행으로 남긴다`

### Task 3 — CLI 연결

- `verdict.main`이 `trace.run_traced`를 부른다. 키가 비어 있으면 흐름 전에 exit 2. `trace_error`가 있으면 응답을 출력한 뒤 stderr에 알리고 exit 1. 그 밖의 exit 코드와 출력은 지금 그대로
- 테스트: 키 없음 exit 2 · 정상 실행 뒤 테스트 DB에 행 1개 · 기존 CLI 테스트가 그대로 통과(필요하면 테스트에 키를 넣는다)
- 커밋: `feature: #83 판정 CLI가 trace 행을 쓴다`

### Task 4 — `--report`

- `src/cheongyak_rag/generate/trace_report.py` 또는 `trace.py`의 `--report`(쉬운 쪽). #81 측정의 표본 읽기·캐시 실행을 그대로 쓴다(`aggregate_report.measure` 참고)
- 측정 코드는 `trace.py` 함수를 import하지 않는다(`run_traced` 호출은 예외 — 재는 대상이다). 가리기 비교·해시 검사·꼴 찾기는 측정 코드가 따로 한다
- 같은 명령을 두 번 돌리면 행이 40개 쌓인다. 징후 1의 A·B는 실행마다 그 실행의 새 행으로 잰다
- 리포트 첫 줄: 징후 1·2 값을 한 문장씩
- 리포트 절: 1. 징후 1~3 표 · 2. 질의 20건과 행(관리번호·프로필·status·전역 판정·해시 앞 12자·가린 횟수·크기) · 3. 행 한 개 전문(더샵 분당하이스트 × 꽉 찬 프로필 — `steps`와 `answer`, 가린 자리가 보이게) · 4. 실패 행 전문 · 5. 파생값이 나온 행 · 6. 표본
- 징후 1 또는 2가 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 가짜 행으로 A가 1이면 exit 1, C가 1이면 exit 1, D만 1이면 「다시 잰다」 문구, 해시가 키 없는 SHA-256과 같으면 E 1
- 커밋: `feature: #83 trace 행을 재는 리포트를 더한다`

### Task 5 — 실제 DB와 캐시로 측정

- 실제 DB(5433)에 `uv run alembic upgrade head`(0004 → 0005). 다른 테이블은 건드리지 않는다
- `--report`를 실제 DB에 돌려 `docs/83-trace.md`·`runs/83/last_run.json`을 커밋한다. 같은 명령을 한 번 더 돌려 두 번째 실행 호출 수를 잰다
- 첫 실행 호출이 0이 아니면 징후 3대로 원인을 찾는다. 프롬프트를 고쳐서 맞추지 않는다
- 징후 2가 「다시 잰다」면 가리기 꼴을 넓히고 한 번 다시 잰다. 미완이 나오면 측정을 결과에 맞춰 고치지 않는다. 코드가 설계와 다른 곳만 고치고, 그래도 미완이면 리포트를 그대로 커밋하고 PR 본문에 그 사실을 쓴다
- 측정으로 쌓인 실제 DB `traces` 행은 지우지 않는다
- 커밋: `docs: #83 trace 측정 리포트`

### Task 6 — 개념 표

- 통과 기준 8. 줄 번호는 이 브랜치 최종 코드 기준
- 커밋: `docs: #83 개념 표에 경로와 trace 상태를 더한다`

### Task 7 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo는 `pydantic_settings`라 위 정규식에 안 걸린다. `config.py`의 새 칸(`trace_hash_key`)과 `.env.example` 새 줄을 같이 적는다
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.generate.verdict 2026000103 --profile runs/80/profiles/empty.json` exit 0 — 출력 맨 위에 응답이 나오고 실제 DB `traces`에 행이 1개 늘었다
> 3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check`
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).
>
> 내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만(다각도 finder + 후보별 독립 검증 CONFIRMED/PLAUSIBLE/REFUTED + failure_scenario 강제) **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.
>
> 커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433, pgvector 0.8.5)다. 워크트리에서 `docker compose up` 하지 않는다
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다 — `TRACE_HASH_KEY`는 main 세션이 dispatch 전에 넣어 두었다
- `data/cache`의 임베딩·`gen-`·`verdict-` 캐시 파일을 지우거나 다시 쓰지 않는다. `verdict-gpt-5.4-mini.jsonl`은 append만 한다(이번 측정은 읽기만 하는 것이 기대값이다)
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다(가짜 클라이언트). 테스트 키는 테스트 안에서 고정 문자열로 준다
- 실제 DB는 alembic `0004`다. 이 티켓이 `0005`로 올린다. 실제 DB의 `chunks`·`notices`·`notice_models`·`law_versions`를 쓰거나 지우지 않는다. `traces`에는 쓴다

## Done criteria

- 통과 기준 1~9가 전부 참이고 실패 징후 1~3의 측정값과 구간이 리포트에 있다. 결과가 통과 구간이 아니어도 Task 5의 처리를 했으면 끝낸다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/83-trace`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#83] feature: 질의 한 건을 trace 테이블에 한 행씩 남긴다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(징후 1의 A·B와 구간, 징후 2의 C·D·E와 구간).
  그 아래 Summary / Changes / 실패 징후 1~3 측정값 표 / 행 한 개 전문 / Notes(설계 §정한 것의 결정과 `TRACE_HASH_KEY`가 새 환경 변수라는 것)
- PR을 만든 뒤 Notion #83 페이지(`3aa41e61-65c0-81b9-9b90-cb103490719f`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81b9-9b90-cb103490719f -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
