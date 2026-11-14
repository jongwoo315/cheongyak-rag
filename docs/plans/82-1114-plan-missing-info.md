# #82 결손 분석 + 질문 순서 — 구현 계획

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

**Tier:** C — 판정 결과를 바꾸는 도메인 핵심 로직(프로필 불가 규칙)과 응답 형식 변경
**Notion:** #82 (`3aa41e61-65c0-810c-b320-cd1693305103`)
**설계:** `docs/plans/82-1114-design-missing-info.md` — 규칙 목록(§2.1)·결손 분석(§2.2)·질문 순서(§2.3)·필요한 질문의 정의(§3)·숫자 읽는 법(§4)은 거기가 기준이다
**흐름:** 이미 있다(공고 + 프로필 → 축별 하위 질의 → 검색 → 판정 → 집계 → 응답 → 웹). 바꾸는 stub은 응답의 `questions`(늘 빈 목록)다. 판정 단계에 프로필 불가 규칙을 더한다

## jw 기준

입력한 프로필에서 어느 필드가 부족한지 분석이 된다, 불가 판정 여부를 먼저 진행하여 불필요한 질문을 하지 않는다

## 통과 기준

1. 프로필 불가 규칙이 설계 §2.1의 규칙 번호 그대로 있다(`referral-1`·`newlywed-3` 제외). 규칙마다 걸리는 경우·안 걸리는 경우 단위 테스트가 있다. 1순위 가입 기간 N은 설계 §2.1의 기본값(24·12·6)이다
2. 규칙이 걸린 하위 질의는 `Verdict.verdict == "INELIGIBLE"`, `ruled=True`, `rule`에 규칙 번호, `original_verdict`에 모델 판정이 있다. 응답 체크리스트의 `note`에 그 사실이 한 줄로 있다. harness `sys_pre_verdict`가 규칙 전 모델 판정이다
3. 결손 분석 함수가 하위 질의마다 없는 정보 목록과 불가 판정을 낼 수 있는 빈 칸 목록을 낸다(설계 §2.2). 정보 이름은 라벨 규칙 `need` 칸의 17개 이름 그대로다
4. `Answer.questions`가 설계 §2.3대로 채워진다: INELIGIBLE 경로 제외, 일반공급 INELIGIBLE이면 빈 목록, 같은 정보 합치기, 순서. 질문 한 줄 칸은 설계 §2.3 마지막 문단. `render_text`가 질문을 순서대로 적는다
5. 웹 결과 화면(`web/components/Result.tsx`)이 질문 목록을 순서대로 보여 준다. 프로필에 칸이 없는 정보는 「입력란 없음」으로 표시한다. `web/lib/types.ts`의 `questions: unknown[]`을 실제 타입으로 바꾼다. `npm run build`가 통과한다
6. harness를 `--out-dir runs/82`로 돌리고 리포트를 `--run-dir runs/82 --out docs/82-eval.md`로 만들었다. `runs/138`·`docs/138-eval.md`는 그대로다
7. `docs/82-missing-info.md`에 jw 기준 측정값·구간, 실패 징후 2~4 측정값·구간, 지표 7개 #138 대비 전후 표, 설계 §4 세 줄이 있다

## 실패 징후

용어: 필요한 질문 · 불필요한 질문 · 빠진 질문은 설계 §3 정의를 그대로 쓴다. 시스템 질문은 `runs/82/run.jsonl`의 시스템 판정으로 만든다.

1. **jw 기준** — 두 값을 잰다
   - ① 결손 분석: 정답 라벨이 NEED_INFO인 하위 질의 378개 중, 결손 분석의 없는 정보 집합이 정답 라벨 `need` 집합과 같은 하위 질의 수
   - ② 불필요한 질문: 문항 50개 중 시스템 질문에 불필요한 질문이 하나라도 있는 문항 수. 비교값으로 같은 수를 「규칙 없이 `runs/138` 판정 + 경로 거르기 없이 NEED_INFO 하위 질의의 정보를 다 묻기」로도 센다
   - 통과: ① 378/378 이고 ② 0문항
   - 다시 잰다: ① 360~377 이거나 ② 1~3문항. 어긋난 하위 질의(축·질의·정답 `need`·결손 분석 값)와 불필요한 질문이 있는 문항(질문·그 질문이 쓰인 하위 질의·정답 판정·시스템 판정)을 표로 적는다. 규칙·정보 표는 더 고치지 않는다
   - 미완: ① 359 이하 이거나 ② 4문항 이상
2. **빠진 질문이 늘었나** — 문항 50개 중 빠진 질문이 하나라도 있는 문항 수. 비교값은 같은 질문 거르기를 `runs/138` 판정(규칙 없음)에 돌린 값이다(LLM이 경로를 잘못 닫아 생기는 빠진 질문은 거기에도 있다)
   - 정상: 비교값 이하
   - 다시 잰다: 비교값보다 1~3 많다. 늘어난 문항마다 빠진 질문과 경로를 닫은 하위 질의(규칙 번호 또는 LLM 판정)를 적는다
   - 미완: 비교값보다 4 이상 많다
3. **규칙이 정답과 어긋났나** — 규칙이 INELIGIBLE로 바꾼 하위 질의 중 정답 라벨이 INELIGIBLE이 아닌 수
   - 정상: 0
   - 다시 잰다: 1~3. 그 하위 질의를 규칙 번호·프로필 칸 값·정답 라벨·정답 이유와 함께 적는다. 규칙·라벨은 고치지 않는다
   - 미완: 4 이상
4. **치명오답** — 치명오답 수. `runs/138`은 2/91
   - 정상: 2 이하
   - 다시 잰다: 3~5. 늘어난 하위 질의를 축·공고·정답·시스템 판정과 함께 적는다
   - 미완: 6 이상

판정 지표 7개(판정 정확도·부당 abstain 등)는 이번 기준이 아니다. `runs/138` 값과 전후만 적고, 규칙이 바꾼 하위 질의 수(모델 판정별)를 같이 적는다(설계 §4).

## 이번에 안 하는 것

- `referral-1`·`newlywed-3` 규칙 — 공고문 사실(도시재생 부지제공자, 신혼부부 갈래)이 DB에 없다
- 공고문에서 1순위 가입 기간을 읽기 — DB 기본값(24·12·6)을 쓴다. 시·도지사가 늘린 공고는 틀린다(설계 §2.1)
- 프로필 칸 늘리기(소득·예치금·거주 등)와 웹에서 질문에 답하는 입력란 — 따로 티켓
- 규칙이 걸리면 LLM 호출 건너뛰기, 프롬프트 수정 — 설계 §5
- 골든셋·정답 라벨·라벨 규칙 수정 — 어긋남을 찾아도 적기만 한다
- 배포(Vercel 재배포) — 머지 뒤 따로 한다

## Tasks

1. **프로필 불가 규칙** — `src/cheongyak_rag/generate/rules.py`(새 파일)에 `rule_ineligible(axis, query, profile: dict, facts: axes.Facts, as_of: date) -> tuple[str, str] | None`(규칙 번호, 이유 한 문장). 특별공급 유형은 하위 질의 문장으로 가린다(`aggregate._TYPE_BY_QUERY`와 같은 방식, 표를 새로 만들지 말고 재사용). 규칙 표의 위에서부터 처음 맞는 것. 날짜 계산은 라벨 규칙 §2 그대로(가입일 + N개월이 `as_of` 이전·같은 날이면 지났다, 만 나이, 혼인 7년). 1순위 N은 `facts.flags`(투기과열지구·청약과열지역)와 `facts.area`(서울·경기·인천)로 정한다.
   단위 테스트: 규칙마다 걸리는 경우 하나·바로 옆 안 걸리는 경우 하나 · 칸이 비었으면 안 걸린다 · 기관추천은 `homeless_now=false`여도 안 걸린다 · N 경계(24·12·6)
2. **판정에 연결** — `verdict.py`의 `Verdict`에 `ruled: bool`·`rule: str | None`. `judge_one`에서 ELIGIBLE guard 다음, 호출이 성공했을 때(`error`가 없을 때) 규칙을 적용한다. `forced`(인용 0개로 UNVERIFIABLE)여도 규칙이 걸리면 INELIGIBLE이다. `original_verdict`는 규칙 전 모델 판정. `reason`은 규칙 이유 문장으로 바꾼다. `aggregate._note`에 규칙 줄. `eval/run.py`의 `sys_pre_verdict` 조건에 `ruled`를 더한다(그 한 줄만 고친다). 판정 캐시 키·프롬프트는 바꾸지 않는다
3. **결손 분석** — `src/cheongyak_rag/generate/questions.py`(새 파일)에 정보 이름 표(17개: 이름 · 한국어 문장 · 프로필 칸인지)와 `analyze(plan_axis, query, profile: dict, facts) -> Missing(info: list[str], can_rule_out: list[str])`. 없는 정보는 설계 §2.2, 불가 판정을 낼 수 있는 빈 칸은 Task 1 규칙이 그 하위 질의에서 보는 프로필 칸 중 비어 있는 것(규칙 표에서 칸 이름을 뽑아 쓴다 — 목록을 따로 손으로 쓰지 않는다).
   단위 테스트: 축 7개·특별공급 유형 8개 각각 · 청약통장 `01`·`03`·모름 · 신혼부부 `married=false`
4. **질문** — 같은 파일에 `build_questions(plans, verdicts, profile, facts) -> list[Question]`(설계 §2.3). 경로는 `aggregate.aggregate`를 부른다. `build_answer`가 `Answer.questions`를 채우고 `render_text`가 「확인할 질문」 아래 순서대로 적는다.
   단위 테스트: 일반공급 INELIGIBLE이면 빈 목록 · INELIGIBLE 특별공급 경로의 정보는 빠진다 · 두 경로에 걸린 정보는 하나로 합쳐지고 경로 둘이 달린다 · 불가 판정을 낼 수 있는 빈 칸이 먼저 · 경로 수가 많은 것이 먼저 · UNVERIFIABLE 하위 질의는 묻지 않는다
5. **웹** — `web/lib/types.ts`에 `Question` 타입, `Result.tsx`에 질문 목록(순서 그대로, 프로필에 칸이 없는 정보는 「입력란 없음」, 쓰이는 경로 이름). 다른 화면은 고치지 않는다. `cd web && npm ci && npm run build`
6. **harness 다시 돌리기** — `uv run python -m cheongyak_rag.eval.run --budget-usd 10 --out-dir runs/82` → `uv run python -m cheongyak_rag.eval.report --run-dir runs/82 --out docs/82-eval.md`. 프롬프트가 같아 판정 캐시가 거의 맞는다. 오래 걸리면 백그라운드로 돌리고 끝난 뒤 그 shell을 끈다. 예산 상한에서 멈추면(exit 1) 그 사실을 리포트에 적고 다시 돌리지 않는다 <!-- style-exempt -->
7. **리포트** — `src/cheongyak_rag/generate/questions_report.py`가 `runs/75/golden.jsonl`·`runs/82/run.jsonl`·`runs/138/run.jsonl`과 DB 공고 값(읽기만)으로 실패 징후 1~4와 비교값을 계산해 `docs/82-missing-info.md`를 쓴다. 필요한 질문 판정(설계 §3)과 정답 라벨로 경로 판정 합치기는 함수로 두고 테스트한다. 리포트 내용: jw 기준(①·②와 비교값) 측정값·구간 / 실패 징후 2~4 측정값·구간 / 지표 7개 `runs/138` 대비 전후 표 / 규칙이 바꾼 하위 질의 수(규칙 번호별·모델 판정별) / 문항 하나의 질문 목록 예시(부분 프로필 문항 하나) / 설계 §4 세 줄
8. **문서** — `docs/concepts.md`에 개념 표 둘을 더한다: 「프로필 불가 규칙」(규칙 번호 · 축/유형 · 조건 · 정의한 곳 · 만든 티켓 #82)과 「정보 이름 17개」(이름 · 뜻 · 프로필에 칸이 있는지 · 정의한 곳). 「판정값 5개」 절의 「코드가 LLM 판정을 바꾸는 경우 둘」을 셋으로 고친다

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값(`LAW_OC`·`DATA_GO_KR_KEY`·OpenAI 키·`NEON_DIRECT_URL`·`TRACE_HASH_KEY`)은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 실제 DB는 읽기만 한다. 어느 테이블에도 쓰지 않는다(`chunks`·`notices`·`notice_models` 포함). 마이그레이션을 더하지 않는다. `trace.run_traced`와 API 판정 엔드포인트를 부르지 않는다
- `data/cache`는 덧붙이기만 한다(판정 캐시·임베딩 캐시). 파일을 지우거나 다시 쓰지 않는다
- OpenAI는 Task 6의 harness 실행에서만 부른다(상한 $10). 테스트는 OpenAI·네트워크·실제 DB를 쓰지 않는다 — DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다 <!-- style-exempt -->
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8082를 쓰고 끝나면 끈다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8082 &) ; sleep 8 ; curl -sf http://127.0.0.1:8082/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8082'`
>    - 웹: `cd web && npm ci && npm run build` 통과
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `uv run python -m cheongyak_rag.golden.check`(exit 0) · `uv run python -m cheongyak_rag.eval.report --run-dir runs/82 --out docs/82-eval.md`(exit 0)
>    - If no runner: state `no tests — skipped`, do not silently pass.
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## Done criteria

- 통과 기준 1~7이 전부 참이고, 실패 징후 1~4의 측정값과 구간이 `docs/82-missing-info.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `runs/82/run.jsonl`·`runs/82/metrics.json`·`docs/82-eval.md`·`docs/82-missing-info.md`를 커밋한다. 실행 로그와 `web/node_modules`·`web/.next`는 커밋하지 않는다(필요하면 `.gitignore`에 넣는다)
- `docs/concepts.md`에 개념 표 둘을 더했다(Task 8). `## 용어` 표에는 main 세션이 이미 넣은 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push origin feat/82-missing-fields`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#82] feature: 결손 분석과 질문 순서 — 프로필로 정해지는 불가 판정을 먼저 내고 필요한 질문만 묻는다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 ①·② 값과 비교값, 구간, 실패 징후 2~4 값과 구간). 그 아래 Summary / Changes / Notes. Notes에 설계 §4 세 줄을 그대로 옮긴다
- PR을 만든 뒤 Notion #82 페이지의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-810c-b320-cd1693305103 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
