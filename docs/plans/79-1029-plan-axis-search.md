# #79 요건 7축 쪼개기와 축별 검색 — 구현 계획

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

**Tier:** C · **Notion:** #79 · **설계:** `docs/plans/79-1029-design-axis-search.md` (먼저 읽을 것 — 7축 표, 켜는 조건, 기대 조, 검색 흐름, 이번에 안 하는 것이 거기 있다)

## jw 기준

7축별로 나눠서 retriever 단계가 잘돌고, 켜진 축 목록과 축마다 검색된 근거 청크 top-k를 확인한다

## 통과 기준

1. `nearest()`가 `law_mst` 조건을 받는다. 안 주면 지금과 같게 동작한다(기존 테스트 그대로 통과)
2. `retrieval/axes.py`에 축 7개가 설계 §2 표대로 있다(id·이름·켜는 조건·하위 질의 문장·기대 조). `plan()`이 공고 하나에 대해 축 7개의 켜짐 여부·이유·하위 질의를 돌려준다
3. `search()`가 켜진 축마다 조문 상위 5개(공고 MST로 거른 것)·FAQ 상위 3개를 돌려준다. dense는 DB `nearest`, BM25는 앱, 합치기는 `search.rrf`
4. CLI `python -m cheongyak_rag.retrieval.axes <house_manage_no>`가 축 목록(켜짐·이유·하위 질의)과 축마다 top-k(조문: 조 · 제목 · 본문 앞 80자, FAQ: Q번호 · 질문)를 출력한다
5. `--report`가 공고 84건을 전부 돌려 실패 징후 1~6을 재고 `docs/79-axis-search.md`·`runs/79/last_run.json`을 쓴다. 징후 1이 미완이면 exit 1
6. 리포트 §표본: 켜진 축 목록이 서로 다른 공고마다 하나씩 골라(착수 실측으로는 최소 3종) 축마다 top-k 전체와 하위 질의 문장을 싣는다
7. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

baseline 없음 — 이번이 첫 측정이다. 각 값은 다음 티켓(#80)의 기준선이 된다.

### 1. jw 기준 — 7축 검색이 끝까지 동작하고, 켜진 축 목록과 축마다 top-k가 나온다

- 잴 것: 공고 84건 전부에 대해
  - 예외가 난 공고 수
  - MST를 못 정한 공고 수
  - 켜진 축 목록이 측정 코드가 SQL로 따로 다시 계산한 목록과 다른 공고 수(측정 코드는 `axes.plan`을 부르지 않고 `notices`·`notice_models`를 직접 읽는다)
  - 켜진 축 중 조문 5개·FAQ 3개보다 적게 돌아온 (공고, 축) 수
  - 리포트 §표본에 실린 공고 수 ↔ 켜진 축 목록의 종류 수
- 통과: 예외 0 · MST 못 정함 0 · 목록 다름 0 · 적게 돌아옴 0 · 표본이 목록 종류마다 1건
- 다시 잰다: 예외·MST·목록이 0이고 적게 돌아온 (공고, 축)이 1~3개. `ef_search`를 올려 다시 재고, 원인(필터 × ANN인지 행이 모자란지)을 리포트에 적는다
- 미완: 예외 1개 이상, MST 못 정함 1개 이상, 목록 다름 1개 이상, 적게 돌아옴 4개 이상, 표본 빠짐 중 하나라도

### 2. 축마다 기대 조가 조문 상위 5개 안에 드는가

- 잴 것: 서로 다른 하위 질의마다 조문 상위 5개에 설계 §2 표의 기대 조가 하나라도 있는지. 축 단위로는 그 축의 하위 질의 전부에서 들면 「든 축」으로 센다. 축 7개 중 든 축 수와 축마다 (든 하위 질의 / 하위 질의) 값
- 통과: 6~7축
- 다시 잰다: 4~5축. 안 든 축의 하위 질의 문장을 고쳐 다시 잰다. 고치기 전·후 문장과 값을 둘 다 리포트에 적는다. 기대 조는 바꾸지 않는다
- 미완: 3축 이하
- 기대 조는 main 세션이 구현 전에 조 제목만 보고 정했다. 정답 대조가 아니다

### 3. DB 경로가 메모리 검색과 같은 결과를 내는가

- 잴 것: 서로 다른 하위 질의마다 `axes.search`의 조문 상위 5개 집합 ↔ `query.Index(candidate).search(같은 문장)`의 조문 상위 5개 집합, FAQ 상위 3개도 같게. 둘 다 같은 하위 질의 비율
- 통과: 0.98 이상
- 다시 잰다: 0.90 이상 0.98 미만. 다른 하위 질의와 빠진 청크를 리포트에 적고 원인을 본다(HNSW 근사, 동점 순서, 토큰화)
- 미완: 0.90 미만

### 4. 임베딩 API 호출 수 (`--report` 한 번)

- 통과: 50회 이하
- 다시 잰다: 51~150회. 하위 질의가 왜 그렇게 많은지 적는다
- 미완: 151회 이상

### 5. 공고 하나를 처리하는 시간 (축 7개 전부, 임베딩 캐시가 찬 상태)

- 잴 것: 84건의 중앙값과 최댓값
- 통과: 중앙값 2초 이하
- 다시 잰다: 중앙값 2초 초과 5초 이하. 어느 단계가 오래 걸리는지 적는다
- 미완: 중앙값 5초 초과

### 6. 꺼진 축 수가 착수 실측과 같은가

- 착수 실측(2026-10-29): 특별공급 축 둘이 꺼진 공고 5건, 재당첨제한 축이 꺼진 공고 48건
- 통과: 둘 다 같다
- 다시 잰다: 다르고, 그 사이 공고 데이터가 바뀐 것으로 설명된다(공고 수·해당 칸 값을 적는다)
- 미완: 다르고 데이터 변경으로 설명되지 않는다

## 이번에 안 하는 것

설계 §6. rerank · LLM 하위 질의 재작성 · 축 동시 실행 · 프로필로 축 끄기(#82) · 축별 판정(#80) · `query.Index`/#139 경로 교체 · 다른 법령(#135) · API 엔드포인트(#84).

## Tasks

각 Task는 TDD(실패하는 테스트 → 구현 → 통과)로 하고 Task 하나가 커밋 하나다.

### Task 1 — `nearest()`에 `law_mst` 조건

- `retrieval/index_db.py` `nearest_sql(source, *, law_mst=False)`·`nearest(..., law_mst: str | None = None)`. 값은 바인드 변수로 넘긴다(source 리터럴 규칙은 그대로)
- 테스트: MST가 다른 조문 행 둘을 넣고 `law_mst`를 주면 그 MST 행만 나온다. 안 주면 기존과 같다. `force_index=True`에서도 부분 인덱스를 탄다(`explain`)

### Task 2 — 축 정의와 `plan()`

- `retrieval/axes.py`: 축 7개 정의(설계 §2 표). `plan(engine, house_manage_no, pblanc_no) -> list[AxisPlan]` — `id`·`name`·`on`·`reason`·`queries`(문자열 목록)·`law_mst`
- 하위 질의
  - 축마다 고정 문장 하나. `residence`는 공급지역명을, `special_type`은 공급이 있는 특별공급 유형마다 문장 하나씩(유형 이름을 끼운다)
  - 문장은 FAQ 질문 말투로 쓴다(예: 「무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?」). 문장 전체를 코드 상수로 두고 리포트에 싣는다
- 켜는 조건을 쓰기 전에 `data/processed/law-008243-20260615.jsonl`에서 제54조(재당첨 제한)·제28조(민영주택의 일반공급, 세대주 요건)·제4조 본문을 읽는다. 설계 §2 조건과 어긋나면 조건을 고치고 무엇을 왜 바꿨는지 리포트 §열린 질문에 적는다
- MST는 view `notice_law_versions`에서 읽는다. 없으면 `law_mst=None`이고 조문 검색을 하지 않는다(징후 1에 센다)
- 테스트: 테스트 DB에 공고·주택형 행을 넣어 조건마다(특별공급 0/양수, 규제 표시 넷 각각) 켜짐·이유가 맞는지

### Task 3 — 축별 검색 `search()`

- `search(engine, embedder, house_manage_no, pblanc_no, *, k=5, faq_k=3) -> list[AxisResult]` — 켜진 축마다 하위 질의별 조문 top-k · FAQ top-faq_k (`Chunk`와 같은 칸: chunk_id·label·path·title·text)
- 하위 질의는 한 번에 모아 `embedder.embed`로 임베딩한다
- 조문: `nearest(source='law', law_mst=MST, k=전체)`로 dense 순위, 같은 조건의 행을 DB에서 읽어 `search.BM25`로 BM25 순위, `search.rrf`로 합친다. FAQ도 같게(`law_mst` 없음). BM25 색인은 (source, MST)마다 한 번 만들어 재사용한다
- 테스트: `tests/test_retrieval_index_db.py`의 가짜 임베더 방식을 따른다. 켜진 축만 결과가 있고, 조문 결과가 공고 MST 행뿐이고, 개수가 k·faq_k인지. OpenAI를 부르지 않는다

### Task 4 — CLI

- `python -m cheongyak_rag.retrieval.axes <house_manage_no> [--pblanc-no N] [-k 5] [--faq-k 3]`
- 출력: 공고명·MST, 축 7개(켜짐/꺼짐 · 이유), 켜진 축마다 하위 질의와 조문·FAQ top-k (`query.format_result`와 같은 꼴)
- 테스트: 출력에 축 7개 이름과 켜진 축의 결과 줄이 있다

### Task 5 — `--report`

- `retrieval/axes_report.py` (#74 `index_db_report.py` 방식): 실패 징후 1~6 측정, `docs/79-axis-search.md`·`runs/79/last_run.json`
- 리포트 첫 줄: 징후 1 값을 한 문장으로(「공고 84건 중 예외 0건, 켜진 축 목록이 다시 계산한 것과 다른 공고 0건, 적게 돌아온 축 0개이고, 기대 조가 든 축은 7개 중 N개다」 꼴)
- 리포트 절: 1. 징후 1~6 표(측정값·구간) · 2. 축 7개 표(이름 · 켜진 공고 수 · 하위 질의 문장 · 기대 조 든 비율) · 3. 표본(켜진 축 목록 종류마다 공고 1건, 축마다 top-k 전체) · 4. 어긋난 곳(목록 다름·적게 돌아옴·메모리와 다름 사례) · 5. 열린 질문에서 고른 것(켜는 조건을 바꿨으면 여기)
- 징후 1이 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 작은 테스트 DB로 md·json에 징후 6개가 다 있고, 목록이 다른 경우 exit 1

### Task 6 — 실제 DB로 측정

- `uv run python -m cheongyak_rag.retrieval.axes_report --report`를 실제 DB(5433)에 돌려 리포트를 커밋한다. 다시 잰다·미완 구간이면 plan에 적힌 대로 고쳐 다시 잰다
- 실제 DB는 alembic `0004`다. 이 티켓은 마이그레이션을 만들지 않는다

### Task 7 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: 공고 하나로 `uv run python -m cheongyak_rag.retrieval.axes <house_manage_no>` exit 0
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
- `.env`·`data`·`.venv`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `data/cache`의 임베딩 캐시 파일을 지우거나 다시 쓰지 않는다(append만 `Embedder`가 한다)
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다
- 실제 DB의 `chunks`·`notices`·`notice_models`를 쓰거나 지우지 않는다. 이 티켓은 읽기만 한다

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~6의 측정값이 리포트에 있다 (다시 잰다·미완 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/79-axis-search`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#79] feature: 공고마다 요건 7축을 켜고 끄고 축마다 조문·FAQ를 따로 검색한다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 값).
  그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / 열린 질문에서 고른 것 / CLI 출력 예 / Notes
- PR을 만든 뒤 Notion #79 페이지(`3aa41e61-65c0-8175-b832-f9129e66d597`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-8175-b832-f9129e66d597 -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
