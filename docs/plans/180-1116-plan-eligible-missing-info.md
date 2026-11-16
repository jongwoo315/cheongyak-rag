# #180 「정보가 없다」에 기대는 ELIGIBLE 막기 — 구현 계획

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
> Also before emitting it, `git status --porcelain` must print nothing. Commit what belongs in
> the PR; add generated files (run logs, caches, scratch output) to `.gitignore`. A leftover
> untracked file keeps the dispatcher waiting, and the review never starts.
> On a HARD, retry-proof API error (OpenAI insufficient_quota, 401/403, exhausted billing), STOP —
> do NOT emit RALPH_DONE, do NOT create a PR, do NOT spin retrying. It surfaces via the orch
> completion notification; a human fixes billing. (Transient TPM 429 is different — pace and retry.)
> A TRANSIENT error that stops being transient counts as HARD. If 429/529 keeps surfacing AND you
> have produced no commit and no file change for 20 minutes, STOP the same way. Waiting and
> spinning are indistinguishable in a headless loop — nobody is watching the screen, and the loop
> re-submits the prompt after every failed turn, so a server-side outage burns the whole iteration
> budget while the picker still reads `working`.

**Tier:** C — 판정값을 바꾸는 도메인 핵심 로직(프로필 가능 규칙)
**Notion:** #180 (`40d41e61-65c0-8103-8ba2-eaff116bb7f1`)
**설계:** `docs/plans/180-1116-design-eligible-missing-info.md` — 규칙 둘(§2)·「정보가 없음」 칸 정의(§3)·숫자 읽는 법(§4)은 거기가 기준이다
**흐름:** 이미 있다(공고 + 프로필 → 축별 하위 질의 → 검색 → 판정 → 집계 → 응답 → 웹). 판정 단계의 무주택·세대주 축 ELIGIBLE을 LLM 대신 코드가 정한다. 새 stub은 없다

## jw 기준

'정보가 없음' 프로필 칸에 정답 라벨 'ELIGIBLE'이 붙는 케이스가 발생하지 않는다

(되물은 뒤: 「정답 라벨」은 시스템 판정, LLM이 낸 ELIGIBLE을 뜻한다)

## 통과 기준

1. `generate/rules.py`에 프로필 가능 규칙 `homeless-2`·`householder-2`가 설계 §2 조건·이유 문장 그대로 있다. 규칙마다 걸리는 경우(칸 true)·안 걸리는 경우(false·비어 있음) 단위 테스트가 있다
2. `judge_one`이 불가 규칙 다음에 가능 규칙을 건다. 호출이 성공했고 `forced`가 아닐 때만 건다. 걸리면 `verdict == "ELIGIBLE"`, `ruled=True`, `rule`에 규칙 번호, `original_verdict`에 모델 판정, `reason`은 규칙 이유 문장이다. 테스트: 모델 NEED_INFO·UNVERIFIABLE·INELIGIBLE이 ELIGIBLE로 바뀐다 · `forced`면 안 바뀐다 · 호출 오류면 안 바뀐다 · 칸이 비면 guard가 그대로 NEED_INFO로 바꾼다
3. 응답 체크리스트 `note`가 가능 규칙을 불가 규칙과 다른 문구로 적는다(설계 §2). 모델도 ELIGIBLE이었으면 「모델 판정도 ELIGIBLE」
4. harness를 `--out-dir runs/180`으로 돌리고 `docs/180-eval.md`를 만들었다. 시연 18쌍을 `runs/180/demo/`로 돌렸다. `runs/81`·`runs/82`·`docs/81-answer.md`·`docs/82-eval.md`는 그대로다
5. `docs/180-eligible.md`에 jw 기준 측정값·구간, 실패 징후 2~5 측정값·구간, 지표 7개 `runs/82` 대비 전후 표, 가능 규칙이 바꾼 하위 질의 수(규칙별·모델 판정별), 설계 §4 세 줄이 있다

## 실패 징후

용어: 「정보가 없음」 칸은 설계 §3 정의를 그대로 쓴다. 표본은 골든셋 50문항(`runs/180/run.jsonl`)과 시연 18쌍(`runs/180/demo/last_run.json`) 둘이다.

1. **jw 기준** — 두 표본의 최종 시스템 ELIGIBLE 중 「정보가 없음」 칸이 하나라도 있는 하위 질의 수(두 표본 합). 표본별 값과 분모를 같이 적는다. 착수 때 값(변경 전 코드): 골든셋 0/44 · 시연 0/8
   - 통과: 0
   - 다시 잰다: 1~2. 그 하위 질의를 표본·문항(또는 공고×프로필)·축·「정보가 없음」 칸·판정을 바꾼 주체(가능 규칙·모델)와 함께 표로 적는다. 규칙·결손 분석 표는 더 고치지 않는다
   - 미완: 3 이상
2. **이유를 LLM이 쓴 ELIGIBLE** — 두 표본의 최종 ELIGIBLE 중 `ruled`가 아닌 것(이유가 모델 문장인 것) 수. 착수 때 골든셋 44/44 · 시연 8/8
   - 정상: 0
   - 다시 잰다: 1~2. 그 하위 질의와 모델 이유 문장, 가능 규칙이 안 걸린 까닭을 적는다
   - 미완: 3 이상
3. **틀린 ELIGIBLE** — 골든셋에서 최종 ELIGIBLE인데 정답 라벨이 ELIGIBLE이 아닌 하위 질의 수. `runs/82` 0/44
   - 정상: 0
   - 다시 잰다: 1~2. 문항·축·프로필 칸 값·정답 라벨·정답 이유를 적는다. 규칙·라벨은 고치지 않는다
   - 미완: 3 이상
4. **판정 정확도** — 골든셋 맞힌 하위 질의 수. `runs/82` 421/524
   - 정상: 421 이상
   - 다시 잰다: 416~420. 정답과 달라진 하위 질의를 `runs/82` 판정과 나란히 적는다
   - 미완: 415 이하
5. **치명오답** — `runs/82` 0/91
   - 정상: 0
   - 다시 잰다: 1~2. 그 하위 질의를 축·공고·정답·시스템 판정과 함께 적는다
   - 미완: 3 이상

나머지 지표(recall@5 등)는 이번 기준이 아니다. `runs/82` 값과 전후만 적는다.

## 이번에 안 하는 것

- 이유 문장을 단어 목록으로 검사하기 — #181 범위이고 설계 §5에서 안 골랐다
- 프롬프트·응답 칸 수정, 판정 캐시 키 변경 — 설계 §5
- 무주택·세대주 축에서 LLM 호출 건너뛰기 — 설계 §5
- 다른 축의 ELIGIBLE 허용, ELIGIBLE guard 표 변경
- 골든셋·정답 라벨·라벨 규칙 수정 — 어긋남을 찾아도 적기만 한다
- 웹 화면 수정 — 체크리스트 `note`·`reason` 문자열만 바뀐다
- 배포(Vercel 재배포) — 머지 뒤 따로 한다

## Tasks

1. **프로필 가능 규칙** — `generate/rules.py`에 `rule_eligible(axis, query, profile: dict) -> tuple[str, str] | None`(규칙 번호, 이유 문장). 표는 설계 §2 두 줄. 불가 규칙 표처럼 규칙 표에서 보는 칸 이름을 뽑을 수 있게 둔다(Task 4 리포트가 「정보가 없음」 칸 3번을 이 표에서 뽑는다). 모듈 docstring에 가능 규칙을 더한다.
   단위 테스트: 규칙마다 true면 걸림 · false면 안 걸림 · 비어 있으면 안 걸림 · 다른 축이면 안 걸림
2. **판정에 연결** — `verdict.py` `judge_one`에서 불가 규칙 다음, 호출 성공이고 `forced`가 아닐 때 `rule_eligible`을 건다. 처리는 통과 기준 2. `aggregate._note`에 가능 규칙 문구(통과 기준 3). `eval/run.py`는 고치지 않는다(`sys_pre_verdict`가 이미 `ruled`를 본다). 판정 캐시 키·프롬프트는 바꾸지 않는다.
   단위 테스트: 통과 기준 2의 다섯 경우 · `note` 문구 두 경우
3. **두 표본 다시 돌리기**
   - 골든셋: `uv run python -m cheongyak_rag.eval.run --budget-usd 10 --out-dir runs/180` → `uv run python -m cheongyak_rag.eval.report --run-dir runs/180 --out docs/180-eval.md`
   - 시연: `generate/aggregate_report.py`에 출력 디렉터리 인자(`--out-dir`, 기본값 지금 그대로 `runs/81`·`docs/81-answer.md`)를 더하고 `--out-dir runs/180/demo`로 돌린다. 리포트 md도 그 디렉터리에 쓴다
   - 프롬프트가 같아 판정 캐시가 거의 맞는다. 오래 걸리면 백그라운드로 돌리고 끝난 뒤 그 shell을 끈다. 예산 상한에서 멈추면(exit 1) 그 사실을 리포트에 적고 다시 돌리지 않는다 <!-- style-exempt -->
4. **리포트** — `generate/eligible_report.py`(새 파일)가 `runs/75/golden.jsonl`·`runs/180/run.jsonl`·`runs/82/run.jsonl`·`runs/180/demo/last_run.json`·`runs/81/last_run.json`·`runs/80/profiles/`와 DB 공고 값(읽기만)으로 실패 징후 1~5를 계산해 `docs/180-eligible.md`를 쓴다. 「정보가 없음」 칸 판정은 함수로 두고 테스트한다(결손 분석 두 목록 + 가능 규칙 칸 중 빈 것). 변경 전 값(`runs/82`·`runs/81`)도 같은 함수로 계산해 「착수 때 값」 열로 나란히 적는다. 리포트 내용: 통과 기준 5
5. **문서** — `docs/concepts.md`의 「프로필 불가 규칙」 표 옆에 「프로필 가능 규칙」 표(규칙 번호 · 축 · 조건 · 정의한 곳 · 만든 티켓 #180)를 더한다. 「판정값 5개」 절의 「코드가 LLM 판정을 바꾸는 경우」에 가능 규칙을 더한다

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값(`LAW_OC`·`DATA_GO_KR_KEY`·OpenAI 키·`NEON_DIRECT_URL`·`TRACE_HASH_KEY`)은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 실제 DB는 읽기만 한다. 어느 테이블에도 쓰지 않는다(`chunks`·`notices`·`notice_models` 포함). 마이그레이션을 더하지 않는다. `trace.run_traced`와 API 판정 엔드포인트를 부르지 않는다
- `data/cache`는 덧붙이기만 한다(판정 캐시·임베딩 캐시). 파일을 지우거나 다시 쓰지 않는다
- OpenAI는 Task 3에서만 부른다(상한 $10씩). 테스트는 OpenAI·네트워크·실제 DB를 쓰지 않는다 — DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다 <!-- style-exempt -->
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8083을 쓰고 끝나면 끈다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8083 &) ; sleep 8 ; curl -sf http://127.0.0.1:8083/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8083'`
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `uv run python -m cheongyak_rag.golden.check`(exit 0) · `uv run python -m cheongyak_rag.eval.report --run-dir runs/180 --out docs/180-eval.md`(exit 0)
>    - If no runner: state `no tests — skipped`, do not silently pass.
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## Done criteria

- 통과 기준 1~5가 전부 참이고, 실패 징후 1~5의 측정값과 구간이 `docs/180-eligible.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `runs/180/`(harness·시연 결과)·`docs/180-eval.md`·`docs/180-eligible.md`를 커밋한다. 실행 로그는 커밋하지 않는다(필요하면 `.gitignore`에 넣는다)
- `docs/concepts.md`에 「프로필 가능 규칙」 표를 더했다(Task 5). `## 용어` 표에는 main 세션이 이미 넣은 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push origin feat/180-eligible-missing-info`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#180] feature: 프로필 가능 규칙 — 무주택·세대주 ELIGIBLE을 프로필 칸으로 정하고 이유도 코드가 쓴다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문(되물은 뒤 줄 포함) + 그 기준으로 잰 결과(실패 징후 1 값·착수 때 값·구간, 실패 징후 2~5 값과 구간). 그 아래 Summary / Changes / Notes. Notes에 설계 §4 세 줄을 그대로 옮긴다
- PR을 만든 뒤 Notion #180 페이지의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/40d41e61-65c0-8103-8ba2-eaff116bb7f1 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
