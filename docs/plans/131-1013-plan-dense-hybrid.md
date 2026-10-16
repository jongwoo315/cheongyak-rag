# #131 dense vs hybrid 검색 비교 — 구현 계획

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

**Tier:** C · **Notion:** #131 · **설계:** `docs/plans/131-1013-design-dense-hybrid.md` (먼저 읽을 것)

## jw 기준

dense, hybrid 비교가 잘 이루어지고 이해가 된다

## 통과 기준

1. `uv run python -m cheongyak_rag.retrieval.golden`이 `runs/golden.jsonl`을 쓰고, 분류별 인용 수와 뺀 질문 수·이유를 출력한다
2. `uv run python -m cheongyak_rag.retrieval.evaluate --run bm25|dense|hybrid`가 `runs/<run>/results.jsonl`(질문 한 줄)과 `runs/<run>/config.json`을 쓴다
3. `uv run python -m cheongyak_rag.retrieval.compare`가 `docs/131-dense-vs-hybrid.md`를 쓴다. 설계 §「이해가 된다」를 어떻게 보이나의 7개 절이 전부 있다
4. dense run을 두 번째로 돌리면 OpenAI 호출이 0회이고 `results.jsonl`이 바이트 단위로 같다
5. 점검 run(§실패 징후 3)의 결과가 리포트에 있다
6. `runs/`와 `docs/131-dense-vs-hybrid.md`를 커밋한다. `data/cache/`는 커밋하지 않는다
7. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 비교가 잘 이루어진다.** 세 run이 같은 질문 집합에서 돌았고, dense 대비 hybrid의
   `recall@5` 차이가 읽히는 결론을 낸다.
   - 세 run의 `results.jsonl` 줄 수가 `runs/golden.jsonl` 줄 수와 다르거나 질문 id 집합이 다르면 → 실패. 비교가 성립하지 않는다
   - 95% 신뢰구간이 0을 포함하지 않는다 → 「차이 있음」으로 통과. 방향과 크기를 리포트 첫 줄에 쓴다
   - 신뢰구간이 0을 포함하고 반폭이 0.05 이하 → 「차이 없음」으로 통과. 이것도 결론이다
   - 신뢰구간이 0을 포함하고 반폭이 0.05를 넘는다 → 「문항 부족으로 판정 불가」. 리포트에 그렇게 쓰고, 실측 문항별 차이의 표준편차로 반폭 0.05에 필요한 문항 수를 계산해 적는다. 결론을 지어내지 않는다
   - baseline 없음 — 이번이 첫 측정, 다음 티켓의 기준이 된다
2. **jw 기준 — 이해가 된다.** 리포트의 「갈린 질문」 절에 `hit@5`가 dense와 hybrid에서 다른 질문이
   **전부** 있고, 줄마다 정답 조의 BM25·dense·hybrid 순위가 있다.
   - 빠진 질문 0, 순위 칸 빈 것 0 → 통과
   - 1개 이상 빠졌거나 순위 칸이 비었다 → 실패. 리포트 생성 코드를 고친다
   - 읽고 이해가 되는지는 PR 게이트에서 jw가 본다. 루프는 이 줄을 판정하지 않는다
3. **점검 — 검색 버그.** 현행 조문 20개(조 번호 순으로 고르게)에서 본문 첫 문장을 그대로 질문으로 넣는다.
   - BM25: 20개 모두 그 조가 1위 → 통과. 18~19개 → 놓친 것마다 질문·1위 조를 PR 본문에 적는다. 17개 이하 → 토크나이저나 색인 버그다. 비교 run으로 넘어가지 않고 고친다
   - dense: 18개 이상 1위 → 통과. 15~17개 → 놓친 것을 PR 본문에 적는다. 14개 이하 → 임베딩 입력(문서 텍스트 조립)을 의심하고 고친다
4. **정답 라벨 수.** 사전 측정(이름 구분 없이 번호만 맞춘 것)은 142쌍이다. 법령 이름으로 거른 뒤 남는 질문 수:
   - 100개 이상 → 통과
   - 60~99개 → 뺀 질문을 이유별로 세어 PR 본문에 적는다. 비교는 진행한다
   - 60개 미만 → 법령 분류 규칙이 너무 좁다. 뺀 질문 20개를 손으로 보고 규칙을 고친다
5. **`제N조`가 든 질문.** 질문 원문에 `제N조`가 든 질문을 뺀 결과에서 hybrid−dense `recall@5` 차이의 부호가
   전체 결과와 반대면 ⚠로 리포트 첫 절에 적는다. 같은 부호면 값만 적는다
6. **제53조 쏠림.** 제53조가 정답에 든 질문을 뺀 결과도 같은 방식으로 본다. 부호가 반대면 ⚠

## 이번에 안 하는 것

설계 §이번에 안 하는 것을 그대로 따른다. 특히 generator·abstain·provider 비교, pgvector·tsvector 적재,
항 단위 청킹은 하지 않는다.

## 작업 환경

- `.venv`는 이 워크트리 자체 것이다. 처음에 `uv sync`를 돌린다. 메인 repo의 `.venv`를 쓰지 않는다
- `.env`는 메인 repo 것의 심볼릭 링크다. `OPENAI_API_KEY`는 셸 환경변수에 있고 `.env`의 값은 비어 있다 — pydantic-settings는 환경변수를 `.env`보다 먼저 읽는다. 키가 비어 있으면 HARD 오류로 멈춘다
- `data/processed/faq-20240529.jsonl`과 `law-008243-20260615.jsonl`은 이미 복사돼 있다. 다시 받지 않는다
- 새 의존성: `uv add kiwipiepy numpy`. 그 밖의 의존성은 넣지 않는다(BM25·통계는 직접 짠다)

## Tasks

새 패키지 `src/cheongyak_rag/retrieval/`. 테스트는 `tests/test_retrieval_*.py`. Task 하나 = 커밋 하나.

### Task 1 — 의존성과 자리

- `uv sync`, `uv add kiwipiepy numpy`
- `.gitignore`에 `data/cache/` 추가
- `src/cheongyak_rag/retrieval/__init__.py`

### Task 2 — 문서 (`corpus.py`)

- `load_articles(path) -> list[Article]` — 삭제 조문 제외. `Article(label, title, text)`
- `text` = `제N조(제목)` 머리 줄 + 조문 본문 + 항·호·목 본문을 순서대로 줄바꿈으로 이은 것
- 테스트: 실제 JSONL로 88개, 가지 조문 라벨(`제4조의2` 꼴), 항이 없는 조의 본문이 들어가는지, 목까지 들어가는지

### Task 3 — 정답 라벨 (`golden.py`)

- 인용 자리마다 법령 분류: 규칙 / 다른 법령 / 이름 없음 (설계 §정한 것의 표)
- 「가장 가까운 법령 이름」은 그 인용이 있는 문장 안에서 인용보다 앞에 나온 것 중 가장 가까운 것이다. `제N조` 바로 앞에 붙은 이름 하나가 뒤따르는 `제N조, 제M조`에 다 걸리는 경우(「주택법」 제2조 및 제4조)를 테스트로 확인한다
- 출력 `runs/golden.jsonl`: `{qid, q_no, question, gold: [label...], has_article_in_question: bool}`. qid는 `faq-<q_no>`
- 콘솔 요약: 분류별 인용 수, 남은 질문 수, 뺀 질문 수와 이유별 수
- 테스트: 66번 쌍(「주택법」 제2조 → 다른 법령), 53번 쌍(「주택공급에 관한 규칙」 제23조 제4항 → 규칙, 정답 `제23조`), 이름 없는 인용, 현행에 없는 조를 규칙으로 인용한 쌍이 빠지는지

### Task 4 — 검색 (`search.py`, `embed.py`)

- `tokenize(text) -> list[str]` — kiwipiepy, 설계의 품사만
- `BM25(docs, k1=1.2, b=0.75).rank(query) -> list[label]` — 88개 전체 순위. 직접 짠다
- `embed.py` — `embed(texts) -> np.ndarray`. 캐시 `data/cache/embed-<model>.jsonl`(텍스트 sha256 → 벡터). 캐시에 없는 것만 API로 보내고, 한 요청에 묶어 보낸다
- `dense_rank(query_vec, doc_vecs, labels) -> list[label]` — 코사인
- `rrf(rankings, k=60) -> list[(label, score)]`
- 테스트: 작은 가짜 문서로 BM25 손계산 값과 비교, 조사가 붙은 형태가 같은 토큰이 되는지(`주택을`/`주택은` → `주택`), RRF 손계산, 임베딩은 가짜 함수 주입(테스트에서 API 호출 0), 캐시 적중 시 API 호출 0

### Task 5 — 실행과 지표 (`evaluate.py`)

- 지표: `recall@5`, `hit@1`, `hit@5`, `mrr`, `gold_rank`(정답 조마다 순위)
- CLI `--run bm25|dense|hybrid` → `runs/<run>/results.jsonl` + `config.json`(모델·k1·b·RRF k·문서 수·질문 수·실행 시각·커밋)
- hybrid 줄에는 정답 조마다 BM25 순위·dense 순위·RRF 점수도 남긴다 (리포트 설명용)
- CLI `--sanity` → 실패 징후 3의 점검 run. `runs/sanity/results.jsonl`
- 테스트: 지표 손계산, 정답 2개 중 1개만 상위 5개 안일 때 `recall@5 = 0.5`

### Task 6 — 비교와 리포트 (`compare.py`)

- paired permutation(10,000회, seed 0)과 bootstrap 95% 신뢰구간(10,000회, seed 0)을 numpy로 직접 짠다
- `docs/131-dense-vs-hybrid.md` — 설계 §「이해가 된다」를 어떻게 보이나의 1~7절 + 실패 징후 1의 결론 문장(세 구간 중 어느 것인지) + 점검 run 결과 + 제53조 제외 결과
- 리포트 첫 줄은 결론 한 문장이다. 「hybrid가 dense보다 recall@5가 +0.0xx (95% CI …, p=…)」 꼴. 판단어(개선·우수)를 쓰지 않는다
- 테스트: 차이가 모두 0이면 p=1·CI [0,0], 같은 seed면 같은 결과, 갈린 질문이 빠짐없이 리포트에 들어가는지

### Task 7 — 실제 실행

1. `golden` → 실패 징후 4 확인
2. `evaluate --sanity` → 실패 징후 3 확인. 걸리면 고치고 다시
3. `evaluate --run bm25`, `--run dense`, `--run hybrid`
4. `evaluate --run dense`를 한 번 더 돌려 OpenAI 호출 0과 `results.jsonl` 동일을 확인 (통과 기준 4)
5. `compare` → 리포트. 실패 징후 1·2·5·6 확인
6. `runs/`, 리포트 커밋

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: `uv run python -m cheongyak_rag.retrieval.compare`가 exit 0으로 끝나는 것을 smoke run으로 본다
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/` 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.

내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션의 available-skills에 없다.

## Done criteria

- 통과 기준 1~7 전부
- 실패 징후 1~6 각각의 측정값과 세 구간 중 어디인지가 PR 본문에 있다
- PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절 — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1·2의 값)
- PR 제목: `[#131] retrieval: FAQ 질문으로 규칙 조문 검색 — dense vs hybrid 비교`
- PR 생성 뒤 Notion #131 페이지(`3ec41e61-65c0-81da-9569-da6b398dcec5`) `PR` 프로퍼티에 PR URL을 넣는다 (`NOTION_API_KEY`, Notion-Version 2022-06-28, `PATCH /v1/pages/{id}`)
- 커밋 접두사는 `~/.claude/rules/github.md` 표의 것만, 괄호 없이. 커밋 메시지는 한글
