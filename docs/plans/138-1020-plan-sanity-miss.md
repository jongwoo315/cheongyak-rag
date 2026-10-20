# #138 #131에서 놓친 검색 — 구현 계획

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

**Tier:** B · **Notion:** #138 · **설계:** `docs/plans/138-1020-design-sanity-miss.md` (먼저 읽을 것)

## jw 기준

티켓131에서 놓친 검색을 개선된 청킹으로 찾을 수 있다

## 통과 기준

1. `uv run python -m cheongyak_rag.retrieval.miss`가 `runs/138/sanity.jsonl`(후보 5개 × 점검 질문 20개 = 100줄),
   `runs/138/golden_misses.json`, `runs/138/causes.json`과 리포트 `docs/138-sanity-miss.md`를 쓰고 exit 0
2. 리포트 첫 줄은 결론 한 문장 — 실패 징후 1의 두 묶음 각각 후보별 값과 구간
3. 두 번째 실행에서 OpenAI 호출 0회, `runs/138/` 파일과 리포트가 바이트 단위로 같다
4. #131 리뷰 1차 #9 defer 테스트 둘이 있다(설계 §범위 4)
5. `runs/138/`과 리포트를 커밋한다. `data/`는 커밋하지 않는다. `runs/73/selected.json`과 #131 run 파일
   (`runs/{bm25,dense,hybrid,sanity}/`)은 바뀌지 않는다(`git diff main --stat -- runs/73 runs/bm25 runs/dense runs/hybrid runs/sanity`가 비어 있다)
6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — #131에서 놓친 검색을 청킹 후보로 찾나.** 후보는 `article` 외 넷. 두 묶음을 따로 판정한다(설계 §「#131에서 놓친 검색」 두 묶음)
   - **A. 점검 run에서 놓친 4건**(bm25 제59조, dense 제9조·제45조·제59조). 후보마다, 놓쳤던 retriever에서 자기 조가 1위가 된 건수:
     - 4건 → **찾음**
     - 1~3건 → **일부 찾음**. 못 찾은 건을 리포트에 적는다
     - 0건 → **못 찾음**
     - 구간과 함께 「1위 청크에 질문 문장이 글자 그대로 들어 있는 건수」와 1위 청크 글자 수 · 질문 글자 수를 적는다.
       이 값은 구간을 바꾸지 않는다 — 읽는 법은 설계 §열린 질문
   - **B. golden에서 #131 hybrid hit@5 = 0이었던 20문항.** 후보마다 찾은 수 F(후보 hybrid hit@5 = 1)와,
     #131이 맞힌 103문항 중 후보가 놓친 수 L:
     - F − L ≥ 3 → **찾은 것이 더 많다**
     - F − L ≤ −3 → **놓친 것이 더 많다**
     - 그 사이 → **차이 없음**
     - 이 묶음은 이미 커밋된 run을 다시 읽는 것이라 plan을 쓰기 전에 값을 알았다(설계 §선행 실측 B). 리포트에 그렇게 적는다
2. **재현.** `article` 후보의 점검 run이 `runs/sanity/results.jsonl`과 질문마다 bm25·dense 자기 순위와 1위 조까지 같다
   (BM25 19/20 · dense 17/20). 같으면 통과. 하나라도 다르면 버그 — 원인을 찾기 전에는 다른 후보를 재지 않는다
3. **원인에 숫자 근거.** `article`에서 놓친 4건 각각의 원인 문장이 `causes.json`의 숫자(낱말별 점수 기여, 코사인,
   조 글자 수 중 하나 이상)를 인용한다. 숫자 없는 원인 문장이 0건이면 통과, 1건 이상이면 미완 — 고친다
4. **BM25 낱말별 기여 검산.** 낱말별 점수 기여의 합이 `BM25.scores`의 그 조 점수와 1e-9 안에서 같다. 다르면 기여 계산이 틀린 것이다 — 고친다

## 이번에 안 하는 것

설계 §이번에 안 하는 것을 그대로 따른다. 특히 `runs/73/selected.json`(검색 구조)은 바꾸지 않고, 점검 질문과 golden을
바꾸지 않고, 새 golden run을 돌리지 않는다.

## 작업 환경

- 먼저 `uv sync`로 이 워크트리 자체 `.venv`를 만든다. 메인 repo의 `.venv`를 쓰지 않는다
  (메인 `.venv`는 메인 repo `src`를 editable로 물고 있다)
- `.env`는 메인 repo 것의 심볼릭 링크다. `OPENAI_API_KEY`는 shell 환경 변수에 있다. 비어 있으면 HARD 오류로 멈춘다
- `data`는 메인 repo `data/`의 **심볼릭 링크**다. 법령·FAQ jsonl과 임베딩 캐시가 거기 있다. 다시 받지 않는다.
  `data`를 지우거나 그 안을 비우지 말 것. `git add`에 넣지 말 것(`.git/info/exclude`에 `/data`가 있다)
- 점검 질문 20개와 모든 후보 청크의 임베딩은 캐시에 있다(설계 §선행 실측이 호출 0회였다). 새 호출이 생기면 수를 PR 본문에 적는다
- 새 의존성 넣지 않는다

## Tasks

기존 `src/cheongyak_rag/retrieval/`의 `corpus`·`search`·`embed`·`evaluate`·`compare`·`chunk`·`chunk_eval`을
재사용한다. 그 파일들의 동작은 바꾸지 않는다. 새 코드는 `retrieval/miss.py` 하나에 둔다. Task 하나 = 커밋 하나.

### Task 1 — 후보별 점검 run (`miss.sanity_by_candidate`)

- 입력: 법령 rows, `Article` 목록, 임베더. `evaluate.pick_sanity`·`first_sentence`로 질문 20개
- 후보마다 `chunk.law_chunks` → BM25(`chunk_eval._Doc`)·`dense_rank` 청크 순위 → `chunk_eval.article_ranks`
- 줄 하나 = 후보 × 질문: `candidate`, `label`, `query`, `query_chars`, `{bm25,dense,hybrid}_rank`, `{bm25,dense,hybrid}_top1`,
  `{bm25,dense}_own_path`(자기 조에서 가장 높이 오른 청크), `{bm25,dense}_own_chars`, `{bm25,dense}_own_has_query`(그 청크에 질문 문장이 글자 그대로 있나)
- 테스트: 가짜 임베더로 `article` 후보 줄의 bm25·dense 순위가 `evaluate.run_sanity`와 같다 / 질문이 청크 안에 그대로 있으면 `own_has_query`가 참

### Task 2 — golden 놓친 문항 (`miss.golden_misses`)

- `runs/hybrid/results.jsonl`에서 hit@5 = 0인 qid, 후보마다 `runs/73/<후보>/results.jsonl`의 같은 qid hybrid hit@5와 정답 조 순위
- 후보마다 F(찾은 수)·L(#131이 맞혔는데 놓친 수)·구간, 찾은 문항과 놓친 문항 목록(qid·질문·정답 조·#131 순위·후보 순위)
- 테스트: 손으로 만든 결과 파일 두 벌로 F·L·구간 / 구간 경계(F − L = 3, −3, 2)

### Task 3 — 원인 (`miss.causes`)

- `bm25_terms(bm25, query, label) -> dict[str, float]` — 낱말별 점수 기여. `search.py`를 고치지 않고 `BM25`의 `tf`·`idf`·`lengths`·`avg_len`·`k1`·`b`를 읽어 계산한다
- 놓친 4건마다: retriever, 질문, 자기 조와 1위 조의 점수(BM25) 또는 코사인(dense), 두 조의 글자 수와 토큰 수,
  BM25면 기여 상위 낱말 5개씩, dense면 `item` 후보에서 자기 조 청크 중 질문과 코사인이 가장 높은 청크의 코사인
- 원인 문장 한 줄씩 — 위 숫자를 인용한다(실패 징후 3)
- 테스트: 실패 징후 4의 검산 / 작은 문서 셋에서 손계산 값

### Task 4 — 리포트와 실행 진입점 (`miss.build_report`, `miss.main`)

- `main()`이 Task 1~3을 돌려 `runs/138/`에 쓰고 리포트를 쓴다. 끝에 OpenAI 호출 수를 출력한다
- `docs/138-sanity-miss.md` 절:
  1. 결론 한 문장 — 실패 징후 1 A·B 후보별 구간
  2. 묶음 A — 후보 × (20개 중 1위 수 bm25·dense·hybrid), 놓쳤던 4건의 후보별 순위, 1위 청크 글자 수·질문 글자 수·글자 그대로 들어 있나.
     「질문은 조문 첫 문장을 자른 것이라 자기 조 청크 안에 글자 그대로 있다」를 절 맨 위에 적는다
  3. 묶음 B — 후보 × F·L·구간, 찾은 문항과 놓친 문항 목록. 「이미 커밋된 run을 다시 읽은 값이다」를 절 맨 위에 적는다
  4. 원인 — 놓친 4건, 숫자와 원인 문장
  5. 재현 — 실패 징후 2의 값
- 판단어(개선·우수)를 쓰지 않는다. 숫자에는 비교 대상(`article`, #131 값)을 붙인다
- 테스트: 가짜 데이터로 절 다섯이 순서대로 있다 / 결론 문장에 후보 넷이 다 나온다

### Task 5 — #131 리뷰 1차 #9 defer 테스트

- `evaluate_run`(가짜 임베더) 결과를 `compare.build_report`에 그대로 넣어 리포트 문자열이 만들어지는 통합 테스트
- `embed.Embedder`를 tmp 캐시 파일과 가짜 OpenAI 클라이언트로 만들고 `write_run`을 두 번 — 두 번째 호출 수 0, `results.jsonl` 바이트 동일
- 프로덕션 코드는 바꾸지 않는다. 테스트가 기존 코드에서 실패하면 그 사실을 PR 본문에 적고 고친다

### Task 6 — 실제 실행

1. `uv run python -m cheongyak_rag.retrieval.miss` → 실패 징후 2를 먼저 본다. 다르면 멈추고 고친다
2. 실패 징후 1·3·4의 값
3. 한 번 더 돌려 통과 기준 3 (`git status`로 `runs/138/`과 리포트에 변경이 없는지)
4. `runs/138/`, 리포트 커밋

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: `uv run python -m cheongyak_rag.retrieval.miss`가 exit 0으로 끝나는 것을 smoke run으로 본다
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/` 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).

내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만 **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.

커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## Done criteria

- 통과 기준 1~6 전부
- 실패 징후 1~4 각각의 측정값과 어느 구간인지가 PR 본문에 있다
- PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절 — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1 A·B의 후보별 값과 구간)
- PR 본문의 수치는 커밋된 `docs/138-sanity-miss.md`와 같아야 한다. 리포트를 다시 만들었으면 PR 본문도 고친다
- PR 제목: `[#138] retrieval: #131 점검 run 놓친 조 원인과 청킹 후보로 다시 보기`
- PR 생성 뒤 Notion #138 페이지(`3fe41e61-65c0-81a1-ac54-d4bd9d936006`) `PR` 프로퍼티에 PR URL을 넣는다 (`NOTION_API_KEY`, Notion-Version 2022-06-28, `PATCH /v1/pages/{id}`)
- 커밋 접두사는 `~/.claude/rules/github.md` 표의 것만, 괄호 없이. 커밋 메시지는 한글
- base 브랜치(`main`)를 작업 브랜치에 merge·rebase하지 않는다
