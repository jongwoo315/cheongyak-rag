# #74 검색 색인을 Postgres에 적재 — 구현 계획

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

**Tier:** C · **Notion:** #74 · **설계:** `docs/plans/74-1027-design-pg-index.md` (먼저 읽을 것 — 테이블 칸, 부분 인덱스를 고른 이유, 열린 질문이 거기 있다)

## jw 기준

기존에 메모리에서 계산하던 임베딩 결과를 postgresql 테이블에 적재하고 인덱스도 추가된다

## 통과 기준

1. alembic `0004`가 테이블 `chunks`(설계 §3 칸 전부)와 인덱스 셋을 만든다 — HNSW(`vector_cosine_ops`) `WHERE source='law'` · HNSW `WHERE source='faq'` · `tokens` GIN. `downgrade`가 셋과 테이블을 지운다. 테스트 DB에서 upgrade → downgrade → upgrade가 통과한다
2. 청크는 `query.Index`와 같은 함수로 만든다 — `law_chunks(load_law_rows(), selected_candidate())` + `faq_chunks(load_faq(), …)`. 새로 청크를 자르는 코드를 쓰지 않는다
3. 적재는 한 트랜잭션에서 `chunks`를 비우고 전부 넣는다. 두 번 돌려도 행 수·`chunk_id` 집합·벡터가 같다(테스트)
4. `tokens` = `to_tsvector('simple', ' '.join(search.tokenize(text)))`. 빈 `tokens` 행이 없다
5. `nearest(engine, query_vec, source, k)` — `WHERE source = :source ORDER BY embedding <=> :q LIMIT :k`. `SET enable_seqscan = off`에서 `EXPLAIN`이 해당 부분 인덱스 이름을 보여 준다(테스트). #79가 이 함수를 쓴다
6. CLI `python -m cheongyak_rag.retrieval.index_db` — 실제 DB에 적재. `--report`면 실패 징후 1~6을 재서 `docs/74-pg-index.md`·`runs/74/last_run.json`에 쓴다. 실패 징후 1이 미완 구간이면 리포트를 쓴 뒤 exit 1
7. 전체 테스트 · `ruff check` · `ruff format --check` 통과

## 실패 징후

baseline 없음 — 이번이 첫 측정이고 #79의 기준값이 된다. 측정은 전부 **실제 DB**(`cheongyak`)에 적재한 뒤 한다.

1. **jw 기준 — 적재와 인덱스.** 메모리 계산이 쓰는 청크 568개(조문 88 + FAQ 480)와 DB를 대조한다
   - 값: 행 수 · `chunk_id` 집합 차이 · `text`가 다른 행 수 · 벡터가 다른 행 수(캐시 벡터와 원소별 차이 > 1e-6) · 있는 인덱스 이름 · `EXPLAIN` 결과
   - pgvector `vector`는 float4로 저장한다. 캐시는 float64 JSON이라 정확히 같을 수 없다 — 그래서 1e-6
   - 통과: 568행, 집합 차이 0, `text` 다른 행 0, 벡터 다른 행 0, 인덱스 셋이 있고 `EXPLAIN`(기본 설정과 `enable_seqscan=off` 둘 다 적는다)에서 `enable_seqscan=off`일 때 부분 인덱스를 탄다
   - 다시 잰다: 행·벡터는 맞고 인덱스도 있는데 `enable_seqscan=off`에서도 인덱스를 안 탄다 → 쿼리의 `WHERE`가 부분 인덱스 조건과 글자 그대로 같은지, `ORDER BY … LIMIT` 모양인지 고쳐서 다시 잰다
   - 미완: 행 수·집합·`text`·벡터 중 하나라도 어긋난 행이 1개 이상, 또는 인덱스가 하나라도 없다
2. **HNSW top-k가 전수 계산과 같은가.** golden 123문항(`runs/golden.jsonl`의 질문)마다 `nearest` top-k 집합과 메모리 `dense_rank` top-k 집합을 비교한다. 조문 k=5, FAQ k=3. 값은 집합이 같은 문항 비율(조문·FAQ 따로)
   - 통과: 둘 다 0.98 이상
   - 다시 잰다: 0.90 이상 0.98 미만 → `SET hnsw.ef_search = 100`으로 다시 잰다. 두 값을 다 적는다
   - 미완: 0.90 미만
   - 다른 문항은 질문·빠진 청크·대신 들어온 청크를 리포트에 적는다
3. **k개보다 적게 돌아온 문항 수**(설계 §3 「필터 × ANN」). 2번과 같은 문항·k로 센다
   - 통과: 0
   - 다시 잰다: 1~3 → `EXPLAIN`으로 부분 인덱스를 타는지 확인하고 고쳐서 다시 잰다
   - 미완: 4 이상
4. **캐시에 없던 청크 텍스트 수**(568개 중). 캐시에 없으면 「기존 임베딩 결과」가 아니라 새로 만든 벡터다
   - 통과: 0
   - 다시 잰다: 1~5 → 어느 청크인지 적고 #73 이후 청크 텍스트가 바뀐 이유를 찾는다
   - 미완: 6 이상
   - golden 질문의 캐시 미스와 API 호출 수는 따로 적는다(판정에 안 쓴다)
5. **재실행.** CLI를 두 번 돌린 뒤 행 수·`chunk_id` 집합·벡터를 비교한다
   - 통과: 바뀐 것 0
   - 다시 잰다: 없음 — 바뀐 것이 있으면 미완
   - 미완: 1개 이상
6. **빈 `tokens` 행 수**
   - 통과: 0
   - 다시 잰다: 1~3 → 어느 청크인지 적는다(내용 없는 조문인지 확인)
   - 미완: 4 이상

## 이번에 안 하는 것

- `query.Index`·#139 답 생성의 검색을 DB로 바꾸는 것 — #79
- DB에서 BM25 점수 계산(`ts_rank`는 IDF가 없어 BM25가 아니다) — #79
- L3 공고문(#72), 다른 법령(#135), 다른 청킹 후보, 법령 여러 버전의 조문 — 설계 §6

## Tasks

TDD로 한다. Task 하나 = 커밋 하나(구현 + 테스트).

### Task 1 — 마이그레이션 0004

- `alembic/versions/0004_chunks.py`. 칸·CHECK·인덱스는 설계 §3. 인덱스 이름은 `chunks_embedding_law_hnsw`·`chunks_embedding_faq_hnsw`·`chunks_tokens_gin`
- `tests/conftest.py`의 `pg_engine` `TRUNCATE` 목록에 `chunks`를 더한다
- 테스트: 테스트 DB에서 테이블·인덱스 셋이 `pg_indexes`에 있다. `alembic downgrade 0003` → `upgrade head`가 통과한다

### Task 2 — 청크를 행으로

- `retrieval/index_db.py`에 `build_rows(embedder, law_mst) -> list[dict]`. 통과 기준 2의 함수만 쓴다. `text_sha256`은 `embed.text_key`
- `law_mst`: `law_versions`에서 `effective_date = 2026-06-15`인 행의 `mst`. 없으면 None(설계 §5-2)
- 테스트: 가짜 embedder(`tests/fakes.py` 방식)로 행 수 = 조문 청크 + FAQ 청크, `chunk_id` 중복 없음, `source`가 `law`·`faq`뿐, FAQ 행의 `law_mst`는 None

### Task 3 — 적재

- `load(engine, rows)`: 한 트랜잭션에서 `DELETE FROM chunks` → insert. `tokens`는 SQL에서 `to_tsvector('simple', :joined)`
- 테스트: 두 번 적재해도 행 수·집합·벡터가 같다. 빈 `tokens` 행 0. 트랜잭션 중간에 실패하면 이전 행이 그대로 남는다

### Task 4 — `nearest`

- 통과 기준 5. 벡터는 `pgvector.sqlalchemy` 또는 `pgvector.psycopg` 등록으로 넘긴다
- 테스트: 가짜 벡터 몇 개로 코사인 순서가 numpy 계산과 같다. `enable_seqscan=off`에서 `EXPLAIN` 출력에 `chunks_embedding_law_hnsw`가 있다. `source='law'`로 k개를 요청하면 k개가 돌아온다

### Task 5 — CLI와 리포트

- `python -m cheongyak_rag.retrieval.index_db [--report]`. 실제 DB(`settings.database_url`)에 `alembic upgrade head`가 돼 있어야 한다 — 안 돼 있으면 안내하고 exit 2
- `--report`: 적재 → 실패 징후 1~6 측정 → `docs/74-pg-index.md`, `runs/74/last_run.json`
- 리포트 첫 줄은 한 문장: 행 수 · 벡터 불일치 수 · 인덱스 개수 · HNSW top-k 일치 비율(조문·FAQ) · 캐시에 없던 청크 수
- 리포트에 적을 것: 실패 징후 1~6 값과 구간, `EXPLAIN` 원문(기본·`enable_seqscan=off`), 열린 질문(설계 §5)에서 고른 값, pgvector·kiwipiepy 버전, 임베딩 API 호출 수
- 실패 징후 1이 미완이면 exit 1

### Task 6 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.retrieval.index_db --report` exit 0
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
- 실제 DB는 alembic `0003`이다. 이 티켓이 `0004`를 만들고 CLI 실행 전에 `uv run alembic upgrade head`로 실제 DB에 적용한다
- `.env`·`data`·`.venv`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `data/cache`의 임베딩 캐시 파일을 지우거나 다시 쓰지 않는다(append만 `Embedder`가 한다)
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~6의 측정값이 리포트에 있다 (다시 잰다·미완 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/74-pg-index`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#74] feature: 조문·FAQ 청크 임베딩을 Postgres 테이블에 적재하고 HNSW·GIN 인덱스를 붙인다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 값).
  그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / 열린 질문에서 고른 것 / CLI 출력 / Notes
- PR을 만든 뒤 Notion #74 페이지(`3aa41e61-65c0-819e-ab3c-ccf3d52ee05f`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-819e-ab3c-ccf3d52ee05f -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
