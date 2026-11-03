# #80 세 번째 시도 — ELIGIBLE 이유가 프로필에 없는 값에 기대지 않게 한다 — 구현 계획

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

**Tier:** C · **Notion:** #80 · **설계:** `docs/plans/80-1030-design-eligible-reason.md`(먼저 읽을 것 — 왜 다시 하나, 바꾸는 표 한 줄, 측정 방법) · **직전 설계:** `docs/plans/80-1030-design-eligible-guard.md` · **바탕 설계:** `docs/plans/80-1029-design-axis-verdict.md` · **이전 리뷰:** `docs/plans/80-1030-review-axis-verdict.md`(PR #12) · `docs/plans/80-1030-review-eligible-guard.md`(PR #13)

## jw 기준

프로필에서 없는 이유로 eligible 판정을 하지 않는다

## 통과 기준

1. PR #13(커밋 `f42b690`)의 판정 모듈·측정 코드·테스트·프로필 3종·`runs/80/pr12_baseline.json`을 가져온다. 가져온 직후 `uv run pytest -q`가 통과한다
2. `REQUIRED_FIELDS["account"]`가 「#77에 없음」(`None`)이고 `NEED_INFO_TEXT["account"]`가 「청약통장 예치금(민영주택) 또는 납입 횟수·금액(국민주택)」이다. 나머지 6개 축의 표는 PR #13 그대로다
3. guard 테스트(가짜 클라이언트):
   - `account`에서 LLM이 `ELIGIBLE`이면 `savings_join_date`가 있어도 없어도 `NEED_INFO`·`guarded`·`original_verdict="ELIGIBLE"`
   - `account`에서 `INELIGIBLE`은 안 바뀐다
   - `homeless`·`householder`는 PR #13 테스트 그대로(칸이 있으면 `ELIGIBLE` 유지, 없으면 `NEED_INFO`)
4. `--report`가 아래 실패 징후 1~6을 재고 `docs/80-axis-verdict.md`·`runs/80/last_run.json`을 쓴다. **징후 1(jw 기준) 또는 징후 2가 미완이면 exit 1**
5. 징후 1의 이유 문장 검사는 guard 표(`REQUIRED_FIELDS`)를 읽지 않는다. 단어 목록은 측정 코드에 따로 둔다
6. system 프롬프트(`SYSTEM`)와 user 메시지 조립을 바꾸지 않는다. 리포트의 `system_sha`가 PR #12·#13과 같은 `92f338a4`다
7. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

baseline: PR #13 측정(`f42b690:runs/80/last_run.json`). 같은 표본·같은 프롬프트라 guard 전 값은 이것과 같아야 한다.

### 1. jw 기준 — 프로필에 없는 값을 이유로 든 ELIGIBLE

- 잴 것(guard 후 최종 판정, 세 프로필 전부):
  - A. 최종 `ELIGIBLE` 중 이유에 `예치금` `납입` `거주` `소득` `자산` `당첨` 중 하나라도 나오는 판정 수
  - B. 최종 `ELIGIBLE` 총수
  - 같이 적는 값: guard 전 `ELIGIBLE` 중 A와 같은 단어가 나오는 판정 수(PR #13 최종값으로는 꽉 찬 프로필 통장 2 · 일부 프로필 통장 3)
- 통과: A 0이고 B 1 이상
- 다시 잰다: A 0이고 B 0 — 잴 판정이 없어 기준이 공허하게 참이다. 리포트에 그 사실을 적고 판정 없음·guard 범위부터 확인한다
- 미완: A 1 이상
- 리포트에 최종 `ELIGIBLE` 전부를 공고·프로필·축·하위 질의·이유 원문으로 싣는다(설계 §측정 방법 2)

### 2. guard가 정상 판정을 지웠나

- 잴 것: `full.json`에서 `homeless`·`householder` 축 판정 중 guard가 바꾼 수. 꽉 찬 프로필은 이 두 축의 칸이 다 있다
- 통과: 0
- 다시 잰다: 없음 — guard는 축·칸 표로 정해지므로 1이면 표나 칸 읽기 코드가 틀린 것이다
- 미완: 1 이상

### 3. 판정을 내리긴 하는가

- 잴 것: `full.json`의 `homeless` 축(공고 6건) 판정 중 `ELIGIBLE`·`INELIGIBLE`·`CONDITIONAL` 수. PR #13은 6/6
- 통과: 5/6 이상
- 다시 잰다: 3~4/6. guard가 바꿨는지(징후 2)부터 본다. 프롬프트는 고치지 않는다(통과 기준 6)
- 미완: 2/6 이하
- 같이 적는 값: `full.json` `account` 축 판정값 분포(이제 `ELIGIBLE`이 나올 수 없다 — PR #13은 `ELIGIBLE` 4 · `UNVERIFIABLE` 2)

### 4. PR #12 징후 1 — 켜진 축만 판정하고, 판정값이 5개 중 하나이고, 남은 인용이 실제로 있다

- 잴 것: PR #13 plan 징후 4와 같다 — 판정 없음·5값 밖 수, 꺼진 축 호출 수, `UNVERIFIABLE`이 아닌데 인용 0개인 판정 수(guard가 바꾼 `NEED_INFO` 포함), 측정 코드가 `chunks`에서 따로 다시 조회해 없는 라벨 수
- 통과: 전부 0
- 다시 잰다: 나머지가 0이고 판정 없음이 1~2개이며 전부 일시 오류
- 미완: 그 밖

### 5. 같은 응답을 읽었나 — 호출 수와 비용

- 잴 것: 첫 실행 LLM 호출 수·비용, 같은 명령 두 번째 실행 호출 수, guard 전 프로필 × 축 × 판정값 분포가 PR #13 guard 전 분포와 같은지
- 통과: 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 칸마다 같음
- 다시 잰다: 첫 실행 호출 1~3. 캐시 키가 왜 달라졌는지 찾아 리포트에 적는다
- 미완: 첫 실행 호출 4 이상 또는 $3 초과, 또는 guard 전 분포가 다름 <!-- style-exempt -->

### 6. 값만 적는 것

- 프로필 × 축별 guard가 바꾼 판정 수(PR #13 32/135), `forced` 수(PR #13 0/135)
- 최종 `ELIGIBLE` 중 「~라는 정보가 없어」처럼 값이 없는 것을 근거로 드는 이유 수. 정규식 `정보가 없|사유가 없|별도.{0,15}없`. PR #13 최종값으로는 2(꽉 찬 프로필 무주택 1 · 일부 프로필 통장 1)
- 구간 없음

## 이번에 안 하는 것

설계 §이번에 안 하는 것 그대로 — 프로필 칸 추가(#82), system 프롬프트 수정(#143), 이유 문장으로 판정을 바꾸는 규칙, 무주택 기간·`homeless_now=false` 일관성 검사(PR #13 리뷰 16·17), 직전 설계 §이번에 안 하는 것 전부.

## Tasks

### Task 1 — PR #13 코드 가져오기

- `git checkout f42b690 -- src/cheongyak_rag/generate/verdict.py src/cheongyak_rag/generate/verdict_report.py tests/test_generate_verdict.py tests/test_generate_verdict_report.py runs/80/profiles runs/80/pr12_baseline.json`
- `docs/80-axis-verdict.md`·`runs/80/last_run.json`은 가져오지 않는다 — Task 4가 새로 쓴다. 비교용 PR #13 값은 `git show f42b690:runs/80/last_run.json`으로 읽는다
- `uv run pytest -q` 통과를 확인하고 커밋(`feature: #80 PR #13의 판정 모듈과 측정 코드를 가져온다`)

### Task 2 — 통장 축 표 한 줄

- `generate/verdict.py`: `REQUIRED_FIELDS["account"] = None`, `NEED_INFO_TEXT["account"]` 문구 교체, 표 위 주석에 이유(가입일만으로는 예치금·납입 요건을 모른다)를 한 줄
- 테스트: 통과 기준 3. PR #13의 「`account`에 가입일이 있으면 `ELIGIBLE` 그대로」 테스트는 이번 규칙에 맞게 바꾼다

### Task 3 — `--report` 고치기

- `generate/verdict_report.py`의 징후를 이 plan의 1~6으로 바꾼다. 구간 경계는 이 plan 그대로
- PR #13 비교값이 필요하면 `runs/80/pr13_baseline.json`으로 필요한 숫자만 뽑아 커밋한다(출처 커밋 `f42b690`을 파일에 적는다). `pr12_baseline.json`은 그대로 둔다
- 징후 1의 단어 목록과 징후 6의 정규식은 측정 코드 상수로 둔다(통과 기준 5)
- 리포트 첫 줄: 징후 1 값을 한 문장으로(「최종 ELIGIBLE N개 중 프로필에 없는 값을 이유로 든 것 0(guard 전 N)」 꼴)
- 리포트 절: 1. 징후 1~6 표 · 2. 최종 `ELIGIBLE` 전부(이유 원문) · 3. 판정값 분포(프로필 × 축, guard 전·후) · 4. guard가 바꾼 판정 전부(이유 원문) · 5. 표본(공고 6건 × 프로필 3종 전부)
- 징후 1 또는 2가 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 가짜 클라이언트로 징후 1 A가 1이면 exit 1, B가 0이면 「다시 잰다」, 징후 2가 1이면 exit 1

### Task 4 — 실제 DB와 캐시로 측정

- `uv run python -m cheongyak_rag.generate.verdict_report --report`를 실제 DB(5433)에 돌려 리포트를 커밋한다. 같은 명령을 한 번 더 돌려 두 번째 실행 호출 수를 잰다
- 첫 실행 호출이 0이 아니면 징후 5대로 원인을 찾는다. 프롬프트를 고쳐서 맞추지 않는다
- 징후 1이 미완이면 단어 목록이나 guard 표를 결과에 맞춰 고치지 않는다. 리포트를 그대로 커밋하고 PR 본문에 그 사실을 쓴다

### Task 5 — Pre-PR 그리고 PR

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
- PR 제목: `[#80] feature: 축별 판정값을 내고, 프로필 값으로 다 확인할 수 없는 축은 ELIGIBLE을 내지 않는다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 A·B, guard 전 값 함께).
  그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / 최종 ELIGIBLE 이유 원문 / 판정값 분포(guard 전·후) / CLI 출력 예 / Notes(PR #12·#13과의 관계)
- PR을 만든 뒤 Notion #80 페이지(`3aa41e61-65c0-81c9-95bc-fab45529bc96`)의 `PR` 프로퍼티에 새 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81c9-95bc-fab45529bc96 -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
