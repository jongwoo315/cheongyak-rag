# #138 검색 문장 — 구현 계획

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

**Tier:** B — 검색 쪽 새 로직, 파일 몇 개. 되돌리기 쉽고 DB·스키마는 안 바꾼다
**Notion:** #138 (`3fe41e61-65c0-81a1-ac54-d4bd9d936006`)
**설계:** `docs/plans/138-1112-design-search-text.md` — 원인(§2)·검색 문장 표(§3)·숫자 읽는 법(§4)은 거기가 기준이다
**흐름:** 이미 있다(공고 → 축별 하위 질의 → 검색 → 판정 → harness). 바꾸는 단계는 축별 검색(`retrieval/axes.py`의 `search`)이 BM25·임베딩에 넣는 문장 하나다

## jw 기준

청약통장·기관추천 두 질문이 상위 5개에 정답 조문을 올리면 성공

## 통과 기준

1. 검색 문장이 설계 §3 표의 네 문장 그대로다(글자까지). 공고 주택 구분(`notices.house_dtl_secd`)이 `01`·`03`이 아니거나 비었으면 하위 질의 문장을 그대로 쓴다. 단위 테스트가 네 경우와 바뀌지 않는 경우를 고정한다
2. `AxisPlan.queries`와 `QueryHits.query`는 하위 질의 문장 그대로다. 골든셋 파일·`generate/aggregate.py`의 문장 표·`eval/run.py`의 맞추기는 고치지 않는다. harness 실행에서 `counts.unmatched_system_queries`가 #76과 같다
3. 검색 문장은 조문·FAQ 검색 둘 다에 쓴다(임베딩 한 번)
4. harness를 `--out-dir runs/138`로 돌리고 리포트를 `--run-dir runs/138 --out docs/138-eval.md`로 만들었다. `runs/76`·`docs/76-eval.md`는 그대로다
5. `docs/138-search-text.md`에 jw 기준 측정값·구간, 실패 징후 2~4의 측정값·구간, 지표 7개 #76 대비 전후 표가 있다

## 실패 징후

1. **jw 기준** — `runs/138/run.jsonl`에서 정답 근거 조문(`제` 로 시작하는 라벨)이 있는 하위 질의 중
   ① 청약통장(`axis=account`) 하위 질의, ② 기관추천(`axis=special_type`이고 하위 질의 문장이 「기관추천 특별공급의 신청 자격과 요건은 어떻게 되나요?」) 하위 질의 각각에서,
   정답 근거 조문 하나 이상이 `law_top5`에 든 하위 질의 수 / 전체. #76 값은 ① 0/50 · ② 0/42
   - 통과: ①·② 둘 다 전부 들었다
   - 다시 잰다: 둘 다 절반 넘게 들었지만 하나라도 전부가 아니다. 놓친 하위 질의를 주택 구분(`01`·`03`)과 정답 근거 조문별로 나눠 표로 적는다. 검색 문장은 더 고치지 않는다
   - 미완: 둘 중 하나라도 절반 이하로 들었다
2. **다른 축으로 샜나** — ①·② 밖의 하위 질의(#76에서 432개 모두 들었다)에서 `law_top5`가 #76과 글자까지 다른 하위 질의 수. 문장·코퍼스가 같으므로 0이어야 한다
   - 정상: 0
   - 다시 잰다: 1~5. 그 하위 질의를 축·문장·두 실행의 `law_top5`와 함께 적고, 검색 문장 함수가 그 하위 질의에 걸렸는지 확인해 적는다
   - 미완: 6 이상 (검색 문장 바꾸기가 다른 하위 질의에 샜다)
3. **주택 구분과 정답 근거 조문이 맞나** — 청약통장 하위 질의 50개에서 「주택 구분 `03`인데 정답 근거 조문이 제28조」 또는 「`01`인데 제27조」인 공고 수. 기관추천 42개도 같은 방식(`01`↔제36조, `03`↔제35조)으로 센다
   - 정상: 둘 다 0
   - 다시 잰다: 합쳐 1~3. 그 공고 이름·`house_dtl_secd`·정답 근거 조문을 표로 적는다(라벨은 고치지 않는다)
   - 미완: 합쳐 4 이상 (주택 구분 칸으로 검색 문장을 고르는 방식이 정답 라벨과 안 맞는다)
4. **치명오답이 늘었나** — 치명오답 수. #76은 2/91
   - 정상: 2 이하
   - 다시 잰다: 3~5. 늘어난 하위 질의를 축·공고·정답 라벨·시스템 판정·인용 조문과 함께 적는다
   - 미완: 6 이상

판정 지표(판정 정확도·정당 abstain·부당 abstain·citation precision)는 이번 기준이 아니다. #76 값과 전후만 적는다(설계 §4).

## 이번에 안 하는 것

- 다른 축·다른 특별공급 유형의 검색 문장 — #76에서 놓친 하위 질의가 없다
- RRF 가중치, FAQ 인용 조문 끌어오기, LLM 검색 문장 다시 쓰기, 조문 청크 별칭(재색인) — 설계 §3 「안 고른 것」
- 확인용 문항 따로 만들기 — 골든셋이 유일한 측정 데이터다. 검색 문장을 정답 근거 조문을 보고 썼다는 것을 리포트에 적는 것으로 대신한다(설계 §4)
- 골든셋·정답 라벨·`axes.AXES`의 기대 조 수정 — 실패 징후 3이 어긋남을 찾아도 적기만 한다
- 웹(`web/`) — 검색 결과를 보여 주는 화면은 바뀌는 문장이 없다

## Tasks

1. **주택 구분을 Facts에 싣는다** — `load_facts` SQL에 `n.house_dtl_secd`를 더하고 `Facts`에 칸 하나(`house_dtl_secd: str | None`). 기존 테스트의 `Facts(...)` 생성을 맞춘다
2. **검색 문장 함수** — `retrieval/axes.py`에 `search_text(query: str, facts_or_house_dtl_secd) -> str`. 설계 §3 표를 상수로 두고 표에 있는 하위 질의·주택 구분이면 그 문장, 아니면 `query` 그대로.
   `search`가 BM25·임베딩·FAQ 검색에 이 문장을 쓰고, `QueryHits.query`에는 하위 질의 문장을 넣는다. `search`가 `plan`을 넘겨받는 경우에도 주택 구분을 알 수 있게 `AxisPlan`에 주택 구분 칸을 더하거나 `Facts`를 넘긴다 — 둘 중 테스트가 덜 바뀌는 쪽.
   단위 테스트: 네 문장 · `02`·`None`일 때 그대로 · 다른 축 하위 질의는 그대로 · `QueryHits.query`가 하위 질의 문장
3. **검색만 먼저 확인** — harness 전에 골든셋 50개 공고로 축별 검색만 돌려(OpenAI 판정 호출 없음, 임베딩은 캐시) 실패 징후 1·2의 검색 쪽 값을 미리 본다. 스크립트는 `src/cheongyak_rag/retrieval/`가 아니라 테스트나 리포트 생성 코드에 둔다. 값이 미완 구간이면 Task 4로 넘어가기 전에 Task 2 구현이 설계 §3 표와 같은지 다시 본다(문장을 바꾸지 않는다)
4. **harness 다시 돌리기** — `uv run python -m cheongyak_rag.eval.run --budget-usd 10 --out-dir runs/138` → `uv run python -m cheongyak_rag.eval.report --run-dir runs/138 --out docs/138-eval.md`.
   오래 걸리면 백그라운드로 돌리고 끝난 뒤 그 shell을 끈다. 예산 상한에서 멈추면(exit 1) 그 사실을 리포트에 적고 다시 돌리지 않는다 <!-- style-exempt -->
5. **리포트** — `docs/138-search-text.md`: jw 기준(실패 징후 1) 측정값·구간 / 실패 징후 2~4 측정값·구간 / 지표 7개 #76 대비 전후 표 / 설계 §4의 「검색 문장은 정답 근거 조문을 보고 썼다」 한 줄. 측정은 `runs/76/run.jsonl`과 `runs/138/run.jsonl`을 읽어 계산하는 코드로 하고, 그 코드를 테스트한다
6. **문서** — `docs/concepts.md`에 개념 표 「주택 구분」(`01` 민영주택 · `03` 국민주택, 정의한 곳 `retrieval/axes.py`, 만든 티켓 #138)을 더한다. 축 7개 표는 바꾸지 않는다

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 실제 DB는 읽기만 한다. 어느 테이블에도 쓰지 않는다(`chunks`·`notices`·`notice_models` 포함). 마이그레이션을 더하지 않는다. `trace.run_traced`와 API 판정 엔드포인트를 부르지 않는다
- `data/cache`는 덧붙이기만 한다(판정 캐시·임베딩 캐시). 파일을 지우거나 다시 쓰지 않는다. 설계 §3의 네 검색 문장 임베딩은 이미 캐시에 있다
- OpenAI는 Task 4의 harness 실행에서만 부른다(판정 캐시가 안 맞는 하위 질의만 새로 돈다, 상한 $10). 테스트는 OpenAI·네트워크·실제 DB를 쓰지 않는다 — DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다 <!-- style-exempt -->
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8138을 쓰고 끝나면 끈다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8138 &) ; sleep 8 ; curl -sf http://127.0.0.1:8138/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8138'`
>    - 웹(`web/`)은 고치지 않으므로 `npm run build`는 돌리지 않는다
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `uv run python -m cheongyak_rag.golden.check`(exit 0) · `uv run python -m cheongyak_rag.eval.report --run-dir runs/138 --out docs/138-eval.md`(exit 0)
>    - If no runner: state `no tests — skipped`, do not silently pass.
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## Done criteria

- 통과 기준 1~5가 전부 참이고, 실패 징후 1~4의 측정값과 구간이 `docs/138-search-text.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `runs/138/run.jsonl`·`runs/138/metrics.json`·`docs/138-eval.md`·`docs/138-search-text.md`를 커밋한다. 실행 로그는 커밋하지 않고 `.gitignore`에 넣는다
- `docs/concepts.md`에 개념 표 「주택 구분」을 더했다. `## 용어` 표에는 main 세션이 이미 넣은 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push origin feat/138-search-text`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#138] feature: 검색 문장 — 청약통장·기관추천 하위 질의를 주택 구분에 맞는 법령 말로 검색한다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 ①·② 값과 구간, 실패 징후 2~4 값과 구간). 그 아래 Summary / Changes / Notes. Notes에 설계 §4의 첫 항목을 그대로 옮긴다
- PR을 만든 뒤 Notion #138 페이지의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3fe41e61-65c0-81a1-ac54-d4bd9d936006 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
