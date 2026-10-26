# #77 프로필 정규화 + 가점 계산(B1) — 구현 계획

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

**Tier:** C · **Notion:** #77 · **설계:** `docs/plans/77-1026-design-profile-score.md` (먼저 읽을 것 — 정답 출처 세 곳과 FAQ 사례 표, 열린 질문이 거기 있다)

## jw 기준

사용자 입력이 수치화되어 당첨 적합도를 계산할 수 있다

(되물은 뒤 jw: 「당첨 적합도는 취소. 판정용 값으로 바꿀 수 있다」)

## 통과 기준

1. `src/cheongyak_rag/profile.py`에 입력 `Profile`(설계 §2 필드, 전부 optional), 판정용 값 계산, 항목 점수, 부분 프로필 범위가 있다.
   LLM·네트워크 호출이 없다. 날짜 연산은 표준 라이브러리만 쓴다(의존성 추가 없음)
2. 점수표 원문 대조 테스트: `data/raw/law-008243-20260615.json`의 별표 1 표를 파싱한 (항목, 구간, 점수) 40행이 코드 상수와 전부 같다.
   파서는 표의 행 수(16 · 7 · 17)도 확인한다 — 파싱이 행을 빠뜨리면 대조가 공허하게 참이 된다
3. FAQ 사례 테스트: 설계 §1 표의 q_no 11개(46 · 151 · 153 · 154 · 156 · 157 · 158 · 159 · 161 · 162 · 170) 각각이 테스트 하나 이상이고,
   테스트 docstring에 q_no와 답의 숫자를 적는다. FAQ 170의 기간 산정 예시 6행은 6개 전부 고정한다.
   **이 테스트 파일은 구현 커밋보다 먼저 커밋한다** — 기대값이 구현을 보고 정해지지 않았다는 증거다
4. 경계 테스트: 세 점수표의 각 구간 시작일·전날, 제10조⑥(2023-12-31 이전 2년 · 합계 5년), 배우자 가산 3점·③ 합계 17점,
   설계 §6 열린 질문 네 개를 고른 쪽으로 고정
5. 범위 테스트
   - soundness: 시드 고정 무작위 완전 프로필 2000개 × 무작위로 필드를 지운 프로필에서 실제 점수(항목별·합계)가 범위 밖인 건수 0
   - 완전 프로필이면 `lo == hi`, 빈 프로필이면 합계 범위가 (①0 + ②5 + ③1) ~ (32 + 35 + 17)
   - tightness: 필드 **하나만** 모르는 경우를 필드마다 만들고, 그 필드의 가능한 값을 전부(날짜는 하루 단위, 수는 0~10) 넣어 본
     실제 최소·최대와 범위 `lo`·`hi`가 같은 비율을 잰다(실패 징후 3)
6. CLI `uv run python -m cheongyak_rag.profile_score`
   - `--profile <json> --as-of YYYY-MM-DD` · `--profile <json> --notice <house_manage_no>:<pblanc_no>` → JSON 출력(판정용 값 · 항목 점수 · 범위 · `missing`), exit 0
   - `--notice` 공고의 `mst`가 `286965`가 아니면 계산하지 않고 그 사실을 출력, exit 1
   - `--report` → `runs/77/sample-profiles.json`(완전 · 통장 가입일만 모름 · 빈 프로필 3개, 이 티켓에서 만든다)을 DB 공고 전부에 계산하고
     `runs/77/last_run.json`과 `docs/77-profile-score.md`를 쓴다. 리포트 첫 줄은 결론 한 문장(실패 징후 1·2의 값).
     §열린 질문에 설계 §6 네 개를 무엇으로 골랐는지 적는다. 점수표 대조 어긋남 ≥1 또는 soundness 위반 ≥1이면 exit 1
7. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 사용자 입력을 판정용 값으로 바꿀 수 있나.** 세 값을 같이 본다
   - (a) FAQ 사례 테스트 일치 수 / 사례 수 (통과 기준 3)
   - (b) 점수표 원문 대조에서 어긋난 칸 수 (통과 기준 2)
   - (c) 공고 전부 × 샘플 프로필 3개 계산 중 실패(예외 · `mst` 불일치) 수
   - 통과: (a) 전부 일치, (b) 0, (c) 0
   - 다시 잰다: (a)에서 어긋난 사례가 있고 그 사례가 전부 설계 §6 열린 질문에 걸린 것(원문 해석이 갈리는 자리)이다.
     그 사례마다 고른 해석과 다른 해석의 계산값을 둘 다 리포트에 적고, FAQ 답과 맞는 쪽으로 고친 뒤 다시 잰다
   - 미완: (b) 1 이상, (c) 1 이상, 또는 (a)에서 열린 질문과 무관한 불일치가 1건 이상
2. **부분 프로필 범위가 실제 값을 놓치나 (soundness).** 통과 기준 5의 무작위 2000건에서 실제 점수가 범위 밖인 건수
   - 통과: 0
   - 다시 잰다: 1 이상이고 전부 설계 §6의 날짜 경계(2월 29일 · 30세 생일 당일)에 걸린다. 그 사례를 리포트에 적고 고친 뒤 시드를 바꿔 다시 잰다
   - 미완: 그 밖의 위반이 1건 이상
3. **범위가 쓸모 없이 넓은가 (tightness, baseline 없음 — 첫 측정).** 필드 하나만 모를 때 범위 `lo`·`hi`가 전수 대입의 실제 최소·최대와 같은 비율
   - 통과: 0.95 이상
   - 다시 잰다: 0.80 이상 0.95 미만. 어긋난 (필드, 항목)을 리포트에 표로 적고 범위 규칙을 고쳐 다시 잰다
   - 미완: 0.80 미만
4. **기간 세는 법이 FAQ와 하루 어긋나나.** FAQ 170 예시 6행 중 `N년M월D일` 문자열까지 맞는 행 수
   - 통과: 6/6
   - 다시 잰다: 점수는 6/6 맞고 문자열만 하루 어긋남 → 가입일 포함 여부를 다시 보고 고친다
   - 미완: 점수가 하나라도 어긋남
5. **점수표 파서가 행을 빠뜨렸나.** 파싱한 행 수가 16 · 7 · 17이 아니면 미완(대조가 공허하게 참이 된다)

## 이번에 안 하는 것

설계 §7 그대로다. 요약: 제53조 무주택 간주 판정, 특별공급 배점표, 자격 판정(#79), 결손 분석 순서(#82),
해외 체류·외국인·손자녀·의무복무, API·폼·저장, 마이그레이션. 별표 1은 MST `286965` 것만 쓴다.

## Tasks

각 Task가 커밋 하나다(impl + test). 순서대로 한다.

### Task 1 — 점수표 상수와 원문 대조

- `src/cheongyak_rag/profile.py`: 세 점수표 상수(구간 경계는 년·개월 단위로, 점수), 점수 조회 함수
- `tests/test_profile_table.py`: raw JSON의 별표 1 `별표내용` 줄 목록에서 상자 표를 파싱해 (항목, 구간 문자열, 점수) 행을 뽑고
  행 수 16 · 7 · 17을 확인한 뒤 상수와 대조. 구간 문자열(`8년 이상～9년 미만`, `6개월 미만`, `6명이상`)을 경계 값으로 바꾸는 작은 파서를 테스트 안에 둔다
- 표는 2열 배치다(왼쪽 구간·점수, 오른쪽 구간·점수). 줄마다 `│`로 나눠 칸 3·4와 5·6을 각각 읽는다

### Task 2 — FAQ 사례 테스트 먼저 (구현 전 커밋)

- `tests/test_profile_faq.py`: 설계 §1 표의 11개 q_no. 각 테스트 docstring에 q_no와 답의 숫자 문장. 이 시점에는 실패해도 된다(xfail 금지 — 그냥 RED로 커밋)
- FAQ 170 예시 6행: (가입일, 공고일, 기간 문자열, 배우자 점수)
- FAQ 46: 성년이 2026-01-01인 사람이 2019-01-01 가입, 공고일 2026-01-01 → 미성년 인정 4년
- FAQ 151: 1986-05-01생 무주택(소유 이력 없음, 미혼), 공고일 2026-05-01 → 무주택기간 10년, ① 22점 (만 30세 2016-05-01부터)

### Task 3 — 기간 계산

- 가입일·기산일 당일을 1일로 세는 `(년, 개월, 일)` 계산. FAQ 170 문자열을 만든다
- 만 나이, 30세 되는 날, 만 19세 되는 날. 2월 29일 → 평년 2월 28일(설계 §6-2)
- 경계 테스트(통과 기준 4의 날짜 부분)

### Task 4 — 판정용 값과 점수 (완전 프로필)

- 무주택 기산일(FAQ 153 네 칸 · 156), `homeless_now=False` → 0점, 30세 미만 미혼 → 0점(설계 §6-1)
- 부양가족 수(배우자 · 미혼 자녀 · 30세 이상 1년 · 직계존속은 세대주 + 소유자 없음일 때만)
- 통장 가입기간에 제10조⑥, 배우자 가산(50% → ③ 점수표 → 3점까지, ③ 합 17점까지)
- 결과 타입: 판정용 값마다 값과 근거 문자열(`"별표1 1호가목3"`, `"제10조⑥"`)을 같이 둔다 — #79가 판정 프롬프트에 넘긴다
- Task 2 테스트가 전부 GREEN이 된다

### Task 5 — 부분 프로필 범위

- 설계 §4 규칙. 항목별 `[lo, hi]`, 합계, `missing`
- soundness 무작위 2000건(시드 고정), 완전 → `lo == hi`, 빈 프로필 범위
- tightness 측정 함수(리포트가 부른다). 필드 하나만 모르는 경우의 전수 대입

### Task 6 — CLI와 리포트

- `src/cheongyak_rag/profile_score.py`: 통과 기준 6. DB 연결은 `asof.py`와 같은 방식(`sqlalchemy` 엔진 + `config.settings`, 테스트에서 `engine`을 주입)을 쓴다. `notice_law_versions` view에서 공고일·`mst`를 읽는다
- `runs/77/sample-profiles.json` 3개
- `--report`가 `runs/77/last_run.json`, `docs/77-profile-score.md`를 쓴다. 리포트 절: 결론 한 줄 · 점수표 대조 · FAQ 사례 표(q_no, 기대, 계산, 일치) · 범위 soundness · tightness(필드별 표) · 공고별 계산 요약 · 열린 질문
- `tests/test_profile_cli.py`: `--as-of` JSON 모양, `mst` 불일치 exit 1(가짜 행으로), `--report` exit 코드 규칙

### Task 7 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.profile_score --report` exit 0
> 3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check`
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).
>
> 내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만(다각도 finder + 후보별 독립 검증 CONFIRMED/PLAUSIBLE/REFUTED + failure_scenario 강제) **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.
>
> 커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. DB는 이미 alembic `0003`이다. 이 티켓은 마이그레이션을 만들지 않는다
- `.env`·`data`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다
- 테스트는 기존 `tests/conftest.py`의 DB fixture 방식을 따른다

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~5의 측정값이 리포트에 있다 (다시 잰다·미완 구간이면 고쳐서 다시 잰 값)
- Task 2의 FAQ 테스트 커밋이 Task 4 구현 커밋보다 앞선다(`git log`로 확인)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/77-profile-score`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#77] feature: 프로필 입력을 판정용 값과 가점(부분 입력이면 범위)으로 바꾼다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문(되물은 뒤 문장 포함) + 그 기준으로 잰 결과(실패 징후 1의 세 값).
  그 아래 Summary / Changes / 실패 징후 1~5 측정값 표 / 열린 질문에서 고른 것 / CLI 출력 / Notes
- PR을 만든 뒤 Notion #77 페이지(`3aa41e61-65c0-81c5-b1c6-c80f5b2fed2f`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81c5-b1c6-c80f5b2fed2f -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
