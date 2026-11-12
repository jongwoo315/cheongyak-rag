# #76 Eval harness — 구현 계획

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

**Tier:** B — 새 측정 코드 여러 파일. 판정 흐름·스키마는 안 바꾼다
**Notion:** #76 (`3aa41e61-65c0-815a-a8e0-d37c4b15a324`)
**설계:** `docs/plans/76-1112-design-eval-harness.md` — 지표 정의(§3.3)와 읽는 법(§4)은 거기가 기준이다
**흐름:** 측정 흐름(골든셋 → 판정 → 정답과 비교 → 리포트)을 이 티켓이 처음 만든다. Task 1이 문항 1개로 끝까지 잇는다

## jw 기준

「청약공고 질의에 대한 검색을 완료하고, 검색결과에 대한 판정 기준을 세울 수 있다」
(되물은 뒤: 「내가 말한 판정기준은 eval harness 쪽이었어」)

## 통과 기준

1. `uv run python -m cheongyak_rag.eval.run --budget-usd 10`이 골든셋 문항 50개를 전부 돌리고 `runs/76/run.jsonl`(하위 질의 한 줄)과
   `runs/76/metrics.json`을 쓴다. 정답 라벨 524개가 run 파일에 한 줄씩 있다(못 맞춘 라벨도 줄을 남기고 `matched=false`)
2. `metrics.json`에 설계 §3.3 지표 7개(recall@5 · hit@5 · citation precision · 판정 정확도(축 7개 + 전체) · 치명오답률 ·
   정당 abstain 비율 · 부당 abstain 비율)가 값·분자·분모로 있다. 못 맞춘 라벨 수 · 판정 실패 수 · FAQ 인용 수 · 비용 · 호출 수도 있다
3. `uv run python -m cheongyak_rag.eval.report`가 `runs/76/run.jsonl`만 읽어 지표를 **`cheongyak_rag.eval.metrics`를 import하지 않고**
   따로 계산하고, `metrics.json`과 다른 지표 수를 센다. 리포트 `docs/76-eval.md`를 쓴다
4. 리포트에 있는 것: 맨 위 jw 기준과 그 기준으로 잰 결과 · 지표 표(값·분자·분모) · 축별 판정 정확도 표 · 정답 × 시스템 판정값 표(5×5) ·
   치명오답 하위 질의 전부(문항 id · 공고명 · 하위 질의 · 시스템 이유 · 정답 이유) · 실패 징후 측정값과 구간 · 설계 §4 「지표를 읽는 법」
5. 같은 명령을 두 번째 돌리면 LLM 호출 0회이고 `metrics.json` 지표 값이 첫 번째와 같다(리포트에 두 실행 값을 같이 적는다)
6. 판정 흐름 코드(`retrieval/`·`generate/verdict.py`·`generate/aggregate.py`·`trace.py`·`api.py`)와 `runs/75/`를 고치지 않았다
7. 테스트: 지표 함수 단위 테스트(정의마다 손으로 만든 run 줄로 기대값), 하위 질의 맞추기 테스트(못 맞춘 라벨이 분모에 남는다),
   report의 따로 계산이 harness와 같은 값을 내는 테스트. 테스트는 OpenAI·실제 DB를 쓰지 않는다
8. `docs/concepts.md`에 개념 표 「eval 지표 7개」(이름(코드 식별자) · 뜻 한 줄 · 정의한 파일·줄 · 만든 티켓 #76)

## 실패 징후

1. **jw 기준 — 검색 완료.** 정답 라벨 524개 중 (못 맞춘 라벨 + 시스템 조문 검색 결과가 0개인 라벨) 수
   - 통과: 0
   - 다시 잰다: 1~10. 하나씩 원인(질의 문장 차이·공고 정보 없음·검색 오류)을 리포트에 적고, 판정 흐름 코드를 고치지 않은 채 run을 한 번 더 돌려 다시 센다
   - 미완: 11 이상
2. **jw 기준 — 판정 기준.** 지표 7개 중 (값이 없거나 분모가 0인 지표 + report가 따로 계산한 값과 harness 값이 다른 지표) 수
   - 통과: 0
   - 다시 잰다: 1~2. 다른 이유를 찾아 측정 코드나 harness를 고치고 report를 다시 돌린다(run은 다시 안 돌려도 된다)
   - 미완: 3 이상
3. 판정 실패(`Verdict.error`) 하위 질의 수
   - 통과: 0
   - 다시 잰다: 1~10. 오류 문구를 리포트에 적고 run을 한 번 더 돌린다(캐시가 성공한 것은 다시 부르지 않는다)
   - 미완: 11 이상
4. 비용 — 첫 실행 비용
   - 통과: $10 이하 <!-- style-exempt -->
   - 미완: 상한에서 멈춤. 멈춘 위치·쓴 금액을 리포트에 적고 더 돌리지 않는다 <!-- style-exempt -->
5. 재현성 — 두 번째 실행의 LLM 호출 수와 지표 차이
   - 통과: 호출 0 · 다른 지표 0
   - 다시 잰다: 그 외. 캐시 키가 왜 바뀌었는지 리포트에 적는다
6. 지표 값 자체 — **적기만 한다. 구간이 없다.** 첫 측정이라 baseline이 없다(이번 값이 다음 티켓의 기준선이 된다).
   값이 낮아도 판정 흐름을 고치지 않는다. 낮은 값이 정상일 수 있다 — 이 측정의 목적은 값을 내는 것이다

## 이번에 안 하는 것

- 지표 임계값 정하기 — 결과를 보고 jw가 정한다
- 판정 흐름 개선(검색·프롬프트·guard·ELIGIBLE guard 표) — 문제가 보여도 리포트에 적기만 한다
- `NEED_INFO` 정밀도 · 확정까지의 질문 수(설계 §5)
- 골든셋 수정. 정답 라벨이 틀려 보이면 리포트 「정답 라벨이 의심스러운 것」 절에 문항 id·하위 질의·이유만 적는다
- CI 연결 · 배포 사이트에 돌리기 · `traces`에 쓰기

## Tasks

각 Task = 커밋 하나. TDD — 실패하는 테스트를 먼저 쓴다.

1. **끝까지 잇기(문항 1개)** — `src/cheongyak_rag/eval/` 패키지: `run.py`(골든셋 읽기 → 문항마다 `verdict.judge` → 하위 질의 맞추기 →
   `runs/76/run.jsonl`), `metrics.py`(지금은 판정 정확도 하나만), `report.py`(`docs/76-eval.md`에 한 줄). `--limit 1`로 문항 1개를 끝까지 돌린다.
   이 단계에서 지표 값이 낮거나 비어 있는 것은 정상이다
   - 클라이언트·캐시·임베더는 `generate/verdict_report.py`의 `measure`가 쓰는 방식을 그대로 따른다(`make_client` + `RetryingClient`,
     `GenCache(vd.cache_path_for(model))`, `Embedder`, `axes.Cache`). `HardApiError`면 멈춘다
   - 프로필은 `profile.Profile.from_dict(row["profile"])`, 공고는 `house_manage_no`·`pblanc_no`
2. **하위 질의 맞추기와 run 줄** — `(문항 id, axis, query)`로 맞춘다. 정답 라벨마다 한 줄, 못 맞춘 라벨은 `matched=false`. 시스템이 만든 하위 질의 중
   정답 라벨이 없는 것은 수만 센다. run 줄 칸: 설계 §3.4
3. **지표 7개** — `metrics.py`에 설계 §3.3 정의대로. 함수 하나가 지표 하나. 단위 테스트에 정의마다 경계 사례(분모 0, FAQ 인용, 판정 실패, 못 맞춘 라벨)
4. **report의 따로 계산** — `report.py`가 `run.jsonl`만 읽어 지표를 다시 계산(import 금지)하고 다른 지표 수를 센다. 리포트 전 절(통과 기준 4)
5. **전체 실행 두 번** — 문항 50개를 `--budget-usd 10`로 돌리고(오래 걸린다 — 백그라운드로 돌리면 끝난 뒤 그 shell을 끈다), 같은 명령을 한 번 더 돌린다.
   실패 징후 1~5를 재서 구간과 함께 리포트에 적는다. 구간이 「다시 잰다」면 그 구간의 처리를 한다
6. **문서** — `docs/concepts.md` 개념 표 「eval 지표 7개」, README에 실행 명령 한 줄

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 실제 DB는 읽기만 한다. 어느 테이블에도 쓰지 않는다. 마이그레이션을 더하지 않는다. `trace.run_traced`와 API 판정 엔드포인트를 부르지 않는다
- `data/cache`는 덧붙이기만 한다(판정 캐시·임베딩 캐시). 파일을 지우거나 다시 쓰지 않는다
- OpenAI는 Task 1·5의 실행에서만 부른다. 모델은 `settings.openai_gen_model`(배포와 같은 값). 테스트는 OpenAI·네트워크·실제 DB를 쓰지 않는다 —
  DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8176을 쓰고 끝나면 끈다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8176 &) ; sleep 8 ; curl -sf http://127.0.0.1:8176/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8176'`
>    - 웹(`web/`)은 고치지 않으므로 `npm run build`는 돌리지 않는다
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `uv run python -m cheongyak_rag.golden.check`(exit 0) · `uv run python -m cheongyak_rag.eval.report`(exit 0)
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## Done criteria

- 통과 기준 1~8이 전부 참이고, 실패 징후 1~6의 측정값과 구간이 `docs/76-eval.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `runs/76/run.jsonl`·`runs/76/metrics.json`(두 번째 실행 값도)·`docs/76-eval.md`를 커밋한다. 실행 로그는 커밋하지 않고 `.gitignore`에 넣는다
- `docs/concepts.md`에 개념 표 「eval 지표 7개」를 더했다. `## 용어` 표에는 main 세션이 이미 넣은 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push origin feat/76-eval-harness`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#76] feature: eval harness — 골든셋 50문항을 판정 흐름에 돌려 지표 7개를 낸다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1·2의 측정값과 구간, 지표 7개 값 표). 그 아래 Summary / Changes / Notes
- PR을 만든 뒤 Notion #76 페이지의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-815a-a8e0-d37c4b15a324 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
