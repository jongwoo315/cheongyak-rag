# #81 집계 + 응답 조립(B8/B9) — 구현 계획

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

**Tier:** B · **Notion:** #81 · **설계:** `docs/plans/81-1103-design-aggregate.md`(먼저 읽을 것 — 집계 규칙 세 가지 결정, 응답 칸, 측정 방법) · **바탕 설계:** `docs/plans/0727-design-cheongyak-rag.md` §Flow B(B8·B9)·§168 우선순위 · **앞 티켓:** #80 `src/cheongyak_rag/generate/verdict.py`·`verdict_report.py`

**흐름:** 판정 흐름은 하위 질의마다 최종 판정(B7)까지 있다. 이 티켓이 그 뒤 B8 집계·B9 응답을 처음 만든다. B9b 질문 랭킹(#82)은 응답의 `questions` 빈 목록으로, trace(#83)·화면(#84)은 자리 없이 다음 티켓이다.

## jw 기준

프롬프트에 따른 성능 변화를 확인할 수 있다, 검색에 없는 답이 나오는지 확인할 수 있다
(되물은 뒤: b8 코드가 규칙대로 합치는가, 검색에 없는 답이 나오는지 확인할 수 있다)

## 통과 기준

1. `src/cheongyak_rag/generate/aggregate.py`(새 파일)에 B8 집계와 B9 응답 조립이 있다. LLM·네트워크를 부르지 않는다(근거 원문은 `chunks`를 읽는다)
2. B8: 설계 §B8 집계 규칙 그대로 — 우선순위 `INELIGIBLE` > `UNVERIFIABLE` > `NEED_INFO` > `CONDITIONAL` > `ELIGIBLE`, 일반공급 판정 = 켜진 일반 축(무주택·청약통장·거주·재당첨·세대주), 특별공급 유형 X 판정 = 켜진 일반 축 + 소득·자산 + 유형 X 질의, 전역 판정 = 일반공급 판정, `verdict=None`은 `UNVERIFIABLE`, 켜진 축이 없는 경로는 `None`
3. B9 응답 칸: 전역 판정 · 특별공급 유형별 판정 · 신청 가능한 경로(`ELIGIBLE`·`CONDITIONAL`) · 축별 체크리스트(판정값·이유·조건·필요한 정보·인용) · 인용마다 `chunks` 원문과 출처 · 가점 범위 · `questions`(빈 목록) · 하위 질의마다 검색 밖 언급(이유의 `제N조`·`제N조의M`·`Qn` 중 `context_labels`에 없는 것). 응답은 `dataclasses.asdict` 뒤 `json.dumps`가 된다
4. 규칙 일치 테스트: 7칸(일반 축 5 + 소득·자산 + 유형 질의 1) × 6가지 상태(꺼짐 + 판정값 5)의 조합 279,936개 전부를 넣고, 우선순위 목록의 순번 최솟값으로 따로 계산한 기대값과 다른 조합이 0이다. 유형 질의가 여러 개인 경우·`verdict=None`·켜진 축 0인 경로는 따로 테스트한다 <!-- style-exempt -->
5. `uv run python -m cheongyak_rag.generate.verdict <공고> --profile <json>` 출력 맨 위에 응답 텍스트가 나오고, 그 아래는 지금 출력 그대로다
6. `--report`가 아래 실패 징후 1~4를 재고 `docs/81-answer.md`·`runs/81/last_run.json`을 쓴다. **징후 1 또는 2가 미완이면 exit 1**
7. system 프롬프트(`SYSTEM`)·user 메시지 조립·축별 필요한 칸 표(`REQUIRED_FIELDS`)를 바꾸지 않는다. 리포트의 `system_sha`가 `92f338a4`다
8. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

표본: #80과 같은 공고 6건(`runs/79/last_run.json`) × 프로필 3종(`runs/80/profiles/`), 18쌍. baseline: PR #14 측정(`runs/80/last_run.json`, 머지 `17434c8`).

### 1. jw 기준 앞 절 — B8 코드가 규칙대로 합치는가

- 잴 것:
  - A. 규칙 일치 테스트(통과 기준 4)에서 기대값과 다른 조합 수 <!-- style-exempt -->
  - B. 실데이터 대조: 18쌍의 응답에서 경로별 판정(일반공급 1 + 특별공급 유형별) 중, 측정 코드가 B8 코드를 부르지 않고 같은 규칙으로 다시 계산한 값과 다른 것의 수. 분모(경로 판정 총수)를 같이 적는다
- 통과: A 0 · B 0
- 다시 잰다: 없음 — 규칙이 결정론적이라 1 이상이면 코드나 측정이 틀린 것이다
- 미완: A 또는 B가 1 이상
- 같이 적는 값: 18쌍의 전역 판정 분포, 특별공급 유형별 판정 분포, 신청 가능한 경로가 1개 이상인 쌍 수

### 2. jw 기준 뒤 절 — 검색에 없는 답이 나오는지 확인할 수 있는가

- 잴 것:
  - C. 하위 질의 135개 중, 응답에 붙은 검색 밖 언급과 측정 코드가 이유 원문·`context_labels`에서 따로 센 검색 밖 언급이 다른 하위 질의 수
  - D. 응답에 실린 근거 원문 중 그 하위 질의 `context_labels`에 없거나 `chunks`에서 다시 읽은 `text`와 글자가 다른 것의 수. 분모(실린 근거 원문 총수)를 같이 적는다
  - E. 검색 밖 언급이 붙은 하위 질의 수. 착수 때 main 세션이 조 번호만 세어 15였다(FAQ 번호 포함하면 달라질 수 있다)
- 통과: C 0 · D 0 · E 1 이상
- 다시 잰다: C 0 · D 0인데 E 0 — 표시가 한 번도 안 붙어 검사가 도는지 알 수 없다. 리포트에 그 사실을 적고 정규식·라벨 꼴부터 확인한다
- 미완: C 또는 D가 1 이상
- 같이 적는 값: 이유 문장의 조·FAQ 번호 언급 총수와 그중 검색 밖 수(착수 때 조 번호만 145 중 65), 최종 `ELIGIBLE` 중 검색 밖 언급이 붙은 수(착수 때 8 중 0), 검색 밖 언급이 붙은 하위 질의 전부(공고·프로필·축·질의·언급한 번호·이유 원문)

### 3. 같은 응답을 읽었나 — 호출 수

- 잴 것: 첫 실행 LLM 호출 수, 같은 명령 두 번째 실행 호출 수, 하위 질의 최종 판정 분포가 PR #14와 칸마다 같은지
- 통과: 둘 다 0 · 분포 같음
- 다시 잰다: 첫 실행 1~3. 캐시 키가 왜 달라졌는지 리포트에 적는다
- 미완: 첫 실행 4 이상 또는 분포가 다름

### 4. 출처 링크

- 잴 것: 응답에 실린 링크 형식마다 한 번 요청해 받은 HTTP 상태
- 통과: 실린 링크 형식이 전부 200
- 다시 잰다: 없음
- 미완: 200이 아닌 형식이 실렸다. 200이 안 나오는 형식은 링크 없이 출처 글자만 싣는다(설계 §B9)

## 이번에 안 하는 것

설계 §이번에 안 하는 것 그대로 — 질문 랭킹(#82), trace(#83), HTTP API·화면(#84), 판정 정확도(#75·#76), system 프롬프트 수정(#143), 검색 밖 언급으로 판정을 바꾸는 규칙.

## Tasks

### Task 1 — B8 집계

- `generate/aggregate.py`: 우선순위 상수, 경로별 합치기, 전역 판정. 입력은 `axes.AxisPlan` 목록과 `verdict.Verdict` 목록
- 세대주 축이 일부 특별공급 유형에만 걸리는 차이를 반영하지 않았다는 `ponytail:` 주석을 단다(설계 §B8)
- 테스트: 통과 기준 4 전부. 279,936개 조합 테스트가 10초를 넘으면 조합을 줄이지 말고 계산을 벡터화하거나 `itertools.product` 순회를 가볍게 한다 <!-- style-exempt -->
- 커밋: `feature: #81 축별 판정을 경로별 판정으로 합친다`

### Task 2 — B9 응답 조립과 검색 밖 언급

- 응답 dataclass와 조립 함수. 근거 원문은 `chunks`에서 읽는다(`verdict.present_in_chunks`와 같은 조건 — 조문은 공고 MST 행, FAQ는 `faq` 행)
- 출처: 조문 「주택공급에 관한 규칙 제N조」 + MST·시행일, FAQ 「2024 주택청약 FAQ Qn」. 링크는 징후 4로 200을 확인한 형식만 싣는다
- 가점: `profile.score(profile, notice.as_of)`의 범위
- 검색 밖 언급: 이유 문장에서 `제\d+조(의\d+)?`와 `Q\d+`를 뽑아 그 하위 질의 `context_labels`에 없는 것. 「제53조제1항」처럼 항이 붙어도 조 번호로 센다
- 텍스트 렌더 함수와 `verdict` CLI 출력 맨 위 연결(통과 기준 5)
- 테스트: 가짜 판정으로 경로별 판정·신청 가능한 경로·근거 원문·검색 밖 언급(조·FAQ·항 붙은 꼴·문맥 안에 있는 번호는 안 붙음)
- 커밋: `feature: #81 판정 응답을 조립하고 검색 밖 언급을 표시한다`

### Task 3 — `--report`

- `generate/verdict_report.py`를 넓히거나 `generate/aggregate.py`에 `--report`를 둔다(쉬운 쪽). #80 측정의 표본 읽기·캐시 실행을 그대로 쓴다
- 측정 코드의 B 재계산과 C 재계산은 `aggregate.py` 함수를 import하지 않는다
- 리포트 첫 줄: 징후 1·2 값을 한 문장씩
- 리포트 절: 1. 징후 1~4 표 · 2. 18쌍 응답 전부(전역 판정·경로별 판정·신청 가능한 경로) · 3. 검색 밖 언급이 붙은 하위 질의 전부(이유 원문) · 4. 응답 한 개 전문(더샵 분당하이스트 × 꽉 찬 프로필) · 5. 표본
- 징후 1 또는 2가 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 가짜 판정으로 B가 1이면 exit 1, E가 0이면 「다시 잰다」 문구, D가 1이면 exit 1
- 커밋: `feature: #81 집계와 응답을 재는 리포트를 더한다`

### Task 4 — 실제 DB와 캐시로 측정

- `--report`를 실제 DB(5433)에 돌려 `docs/81-answer.md`·`runs/81/last_run.json`을 커밋한다. 같은 명령을 한 번 더 돌려 두 번째 실행 호출 수를 잰다
- 첫 실행 호출이 0이 아니면 징후 3대로 원인을 찾는다. 프롬프트를 고쳐서 맞추지 않는다
- 미완이 나오면 규칙·정규식을 결과에 맞춰 고치지 않는다. 코드가 설계와 다른 곳만 고치고, 그래도 미완이면 리포트를 그대로 커밋하고 PR 본문에 그 사실을 쓴다
- 커밋: `docs: #81 집계·응답 측정 리포트`

### Task 5 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: 공고 하나와 `runs/80/profiles/empty.json`으로 `uv run python -m cheongyak_rag.generate.verdict <house_manage_no> --profile runs/80/profiles/empty.json` exit 0 — 출력 맨 위에 응답(전역 판정 · 경로별 판정 · 체크리스트)이 나온다
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
- `.env`·`.venv`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `data/cache`의 임베딩·`gen-`·`verdict-` 캐시 파일을 지우거나 다시 쓰지 않는다. `verdict-gpt-5.4-mini.jsonl`은 append만 한다(이번 측정은 읽기만 하는 것이 기대값이다)
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다(가짜 클라이언트)
- 실제 DB의 `chunks`·`notices`·`notice_models`를 쓰거나 지우지 않는다. 이 티켓은 읽기만 한다
- 실제 DB는 alembic `0004`다. 이 티켓은 마이그레이션을 만들지 않는다

## Done criteria

- 통과 기준 1~8이 전부 참이고 실패 징후 1~4의 측정값과 구간이 리포트에 있다. 결과가 통과 구간이 아니어도 Task 4의 처리를 했으면 끝낸다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/81-aggregate`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#81] feature: 축별 판정을 경로별 판정으로 합치고 근거 원문이 붙은 응답을 만든다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(징후 1의 A·B, 징후 2의 C·D·E와 구간).
  그 아래 Summary / Changes / 실패 징후 1~4 측정값 표 / 응답 한 개 전문 / 검색 밖 언급 예 / Notes(설계 §B8에서 정한 세 가지)
- PR을 만든 뒤 Notion #81 페이지(`3aa41e61-65c0-8117-b35a-f96f9061957a`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-8117-b35a-f96f9061957a -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
