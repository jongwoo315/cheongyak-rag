# #80 재시작 — 프로필 값 없이 ELIGIBLE을 내지 못하게 막는 코드 guard — 구현 계획

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
>
> **턴을 끝낼 때 마지막 메시지에 반드시 글자로 된 요약을 남긴다.** 글자 없이 도구 호출로만 끝난 턴은 ralph 상태 파일이
> 지워져 루프가 멈춘다(#71에서 실제로 멈췄다).

**Tier:** B · **Notion:** #80 · **설계:** `docs/plans/80-1030-design-eligible-guard.md`(먼저 읽을 것 — 왜 다시 하나, 축별 필요한 칸 표, 설계 결정, 측정) · **바탕 설계:** `docs/plans/80-1029-design-axis-verdict.md` · **이전 PR 리뷰:** `docs/plans/80-1030-review-axis-verdict.md`

## jw 기준

빈 프로필을 eligible로 판정하지 않고, 꽉 찬 프로필에 없는 값을 있다고 eligible로 판정하지 않는다

## 통과 기준

1. PR #12(커밋 `1c06665`)의 판정 모듈·측정 코드·테스트·프로필 3종을 가져온다. 가져온 직후 `uv run pytest -q`가 통과한다
2. `judge_one()`이 인용 guardrail 다음에 ELIGIBLE guard를 적용한다. 설계 §무엇을 바꾸나의 축별 필요한 칸 표대로, 필요한 칸 중 하나라도 `None`이면(또는 칸이 #77에 없는 축이면) `ELIGIBLE` → `NEED_INFO`, `guarded=True`, `original_verdict="ELIGIBLE"`, `need_info`에 설계 표의 문구를 넣는다. 인용은 그대로 둔다
3. guard 테스트(가짜 클라이언트):
   - `residence`·`income_asset`·`rewin`·`special_type`에서 LLM이 `ELIGIBLE` → `NEED_INFO`·`guarded`
   - `account`에서 `savings_join_date`가 없으면 `ELIGIBLE` → `NEED_INFO`, 있으면 `ELIGIBLE` 그대로
   - `homeless`(`homeless_now`)·`householder`(`is_household_head`)도 같은 두 경우
   - `INELIGIBLE`·`CONDITIONAL`·`NEED_INFO`·`UNVERIFIABLE`은 어느 축에서도 안 바뀐다
   - 인용이 기각돼 `forced`로 `UNVERIFIABLE`이 된 판정에는 guard가 다시 손대지 않는다
4. CLI 출력에 guard가 바꾼 판정이 표시된다(원래 판정과 함께). 테스트로 확인한다
5. `--report`가 아래 실패 징후 1~6을 재고 `docs/80-axis-verdict.md`·`runs/80/last_run.json`을 쓴다. **징후 1(jw 기준) 또는 징후 2가 미완이면 exit 1**
6. system 프롬프트(`SYSTEM`)와 user 메시지 조립을 바꾸지 않는다. 리포트의 `system_sha`가 PR #12와 같은 `92f338a4`다
7. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

baseline: PR #12 측정(`1c06665:runs/80/last_run.json`). 같은 표본·같은 프롬프트라 guard 전 값은 이것과 같아야 한다.

### 1. jw 기준 — 빈 프로필 ELIGIBLE과 꽉 찬 프로필에서 없는 값으로 낸 ELIGIBLE

- 잴 것(guard 후 최종 판정):
  - A. `empty.json` 프로필의 판정 중 `ELIGIBLE` 수
  - B. `full.json` 프로필에서 `residence`·`income_asset`·`rewin`·`special_type` 축 판정 중 `ELIGIBLE` 수
  - 같이 적는 값: 같은 두 칸의 guard 전(LLM 원 판정) `ELIGIBLE` 수. PR #12 값은 A 7 · B 13
- 통과: A 0 · B 0
- 다시 잰다: A·B가 0이지만 판정 없음(API 오류·파싱 실패)인 하위 질의가 `empty` 또는 `full` 쪽에 1~2개라 일부를 못 쟀다. 그 하위 질의만 다시 부른다
- 미완: A 1 이상 또는 B 1 이상, 또는 판정 없음 3개 이상

### 2. guard가 정상 판정을 지웠나

- 잴 것: `full.json` 프로필에서 `homeless`·`account`·`householder` 축 판정 중 guard가 바꾼 수. 꽉 찬 프로필은 이 세 축의 칸이 다 있다
- 통과: 0
- 다시 잰다: 없음 — guard는 축·칸 표로 정해지므로 1이면 표나 칸 읽기 코드가 틀린 것이다
- 미완: 1 이상

### 3. 판정을 내리긴 하는가

- 잴 것: `full.json`에서 `homeless`·`account` 축(공고 6건 × 2축 = 12개) 판정 중 `ELIGIBLE`·`INELIGIBLE`·`CONDITIONAL` 비율. PR #12는 10/12
- 통과: 10/12 이상
- 다시 잰다: 6~9/12. guard가 바꿨는지(징후 2)부터 본다. 프롬프트는 고치지 않는다(통과 기준 6)
- 미완: 5/12 이하

### 4. PR #12 징후 1 — 켜진 축만 판정하고, 판정값이 5개 중 하나이고, 남은 인용이 실제로 있다

- 잴 것: PR #12 plan 징후 1과 같다 — 판정 없음·5값 밖 수, 꺼진 축 호출 수, `UNVERIFIABLE`이 아닌데 인용 0개인 판정 수(guard가 바꾼 `NEED_INFO` 포함), 측정 코드가 `chunks`에서 따로 다시 조회해 없는 라벨 수
- 통과: 전부 0
- 다시 잰다: 나머지가 0이고 판정 없음이 1~2개이며 전부 일시 오류
- 미완: 그 밖

### 5. 같은 응답을 읽었나 — 호출 수와 비용

- 잴 것: 첫 실행 LLM 호출 수·비용, 같은 명령 두 번째 실행 호출 수, guard 전 값이 PR #12와 같은지(징후 1의 같이 적는 값, 프로필 × 판정값 분포)
- 통과: 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 PR #12와 칸마다 같음
- 다시 잰다: 첫 실행 호출 1~3. 캐시 키가 왜 달라졌는지 찾아 리포트에 적는다
- 미완: 첫 실행 호출 4 이상 또는 $3 초과, 또는 guard 전 분포가 PR #12와 다름(같은 응답을 읽은 게 아니다) <!-- style-exempt -->

### 6. guard가 얼마나 바꿨나

- 잴 것: 프로필 × 축별 guard가 바꾼 판정 수, `forced` 수(PR #12 0/135), 칸 없는 4개 축의 `INELIGIBLE` 수(PR #12 꽉 찬 프로필 5 — guard 대상 아님)
- 값만 적는다(구간 없음). `partial.json`에서 칸 없는 축 `ELIGIBLE`(PR #12 12개)도 guard 후 0인지 적는다

## 이번에 안 하는 것

설계 §이번에 안 하는 것 그대로 — system 프롬프트 수정(제10조·제34조 제목 포함, #143), 프로필 칸 추가(#82), `CONDITIONAL` 규칙 검증, PR #12 리뷰 defer 7·8, 바탕 설계 §이번에 안 하는 것 전부.

## Tasks

### Task 1 — PR #12 코드 가져오기

- `git checkout 1c06665 -- src/cheongyak_rag/generate/verdict.py src/cheongyak_rag/generate/verdict_report.py tests/test_generate_verdict.py tests/test_generate_verdict_report.py runs/80/profiles`
- `docs/80-axis-verdict.md`·`runs/80/last_run.json`은 가져오지 않는다 — Task 4가 새로 쓴다. 비교용 PR #12 값은 `git show 1c06665:runs/80/last_run.json`으로 읽는다
- `uv run pytest -q` 통과를 확인하고 커밋(`feature: #80 PR #12의 판정 모듈과 측정 코드를 가져온다`)

### Task 2 — ELIGIBLE guard

- `generate/verdict.py`: 축별 필요한 칸 표(`REQUIRED_FIELDS` 꼴, 칸이 #77에 없는 축은 빈 튜플이나 `None`으로 「없음」을 나타낸다)와 `need_info` 문구, guard 함수. `Verdict`에 `guarded` 칸을 더한다(`original_verdict`는 이미 있다 — `forced`와 같이 쓴다)
- `judge_one()`은 프로필 원본을 `payload`로 받는다. guard는 `payload`의 프로필 원본에서 칸 값을 읽는다(`profile.score` 결과가 아니라). `judge_one()` 시그니처를 바꿔야 하면 바꾼다
- 순서: 인용 대조 → `forced` → guard. `forced`가 된 판정은 guard가 건드리지 않는다
- 테스트: 통과 기준 3 전부

### Task 3 — CLI 표시

- `format_verdict`가 guard가 바꾼 판정에 원래 판정을 함께 적는다(`forced` 표시와 같은 방식)
- 테스트: 통과 기준 4

### Task 4 — `--report` 고치기

- `generate/verdict_report.py`의 징후를 이 plan의 1~6으로 바꾼다. 구간 경계는 이 plan 그대로
- PR #12 값(guard 전 비교용)은 `1c06665:runs/80/last_run.json`을 읽어 쓴다. git으로 읽는 대신 측정 코드가 그 파일을 읽어야 하면 `runs/80/pr12_baseline.json`으로 필요한 숫자만 뽑아 커밋한다(출처 커밋을 파일에 적는다)
- `PROMPT_NOTES`(PR #12의 프롬프트 고친 경과)는 「PR #12에서 프롬프트로 시도한 것」으로 남기고 이번 결과를 덧붙인다
- 리포트 첫 줄: 징후 1 값을 한 문장으로(「빈 프로필 ELIGIBLE 0(guard 전 N), 꽉 찬 프로필 칸 없는 4개 축 ELIGIBLE 0(guard 전 N)」 꼴)
- 리포트 절: 1. 징후 1~6 표 · 2. 판정값 분포(프로필 × 축, guard 전·후) · 3. guard가 바꾼 판정 전부(공고·프로필·축·하위 질의·LLM 이유 원문) · 4. 표본(공고 6건 × 프로필 3종 전부)
- 징후 1 또는 2가 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 가짜 클라이언트로 징후 1이 A 1이면 exit 1, 징후 2가 1이면 exit 1

### Task 5 — 실제 DB와 캐시로 측정

- `uv run python -m cheongyak_rag.generate.verdict_report --report`를 실제 DB(5433)에 돌려 리포트를 커밋한다. 같은 명령을 한 번 더 돌려 두 번째 실행 호출 수를 잰다
- 첫 실행 호출이 0이 아니면 징후 5대로 원인을 찾는다. 프롬프트를 고쳐서 맞추지 않는다

### Task 6 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: 공고 하나와 `runs/80/profiles/empty.json`으로 `uv run python -m cheongyak_rag.generate.verdict <house_manage_no> --profile runs/80/profiles/empty.json` exit 0
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
- `.env`·`data`·`.venv`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `data/cache`의 임베딩·`gen-`·`verdict-` 캐시 파일을 지우거나 다시 쓰지 않는다. `verdict-gpt-5.4-mini.jsonl`은 append만 한다(이번 측정은 읽기만 하는 것이 기대값이다)
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다(가짜 클라이언트)
- 실제 DB의 `chunks`·`notices`·`notice_models`를 쓰거나 지우지 않는다. 이 티켓은 읽기만 한다
- 실제 DB는 alembic `0004`다. 이 티켓은 마이그레이션을 만들지 않는다

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~6의 측정값이 리포트에 있다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/80-axis-verdict`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#80] feature: 축별 판정값을 내고, 프로필 값이 없으면 ELIGIBLE을 NEED_INFO로 바꾼다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 값, guard 전·후 둘 다).
  그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / 판정값 분포(guard 전·후) / guard가 바꾼 판정 / CLI 출력 예 / Notes(PR #12와의 관계)
- PR을 만든 뒤 Notion #80 페이지(`3aa41e61-65c0-81c9-95bc-fab45529bc96`)의 `PR` 프로퍼티에 새 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81c9-95bc-fab45529bc96 -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
