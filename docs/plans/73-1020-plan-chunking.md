# #73 청킹 — 구현 계획

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

**Tier:** C · **Notion:** #73 · **설계:** `docs/plans/73-1020-design-chunking.md` (먼저 읽을 것)

## jw 기준

현재 공고문에 맞는 청킹 방식을 선택해서 청약 관련 상세 내용이 검색되기 용이한 구조로 만든다

(「현재 공고문」 = 법령 조문과 FAQ. 착수 전 jw 확인, 2026-10-20)

## 통과 기준

1. `uv run python -m cheongyak_rag.retrieval.chunk`가 설계 §1의 조문 후보 5개와 FAQ 청크를
   `data/processed/chunks-<후보>.jsonl`로 쓰고, 후보마다 청크 수·글자 수 중앙값·최대를 출력한다
2. `uv run python -m cheongyak_rag.retrieval.chunk_eval --candidate <후보>`가
   `runs/73/<후보>/results.jsonl`(질문 한 줄, bm25·dense·hybrid 순위와 지표)과 `config.json`을 쓴다.
   `--faq`는 `runs/73/faq/`를 쓴다(leave-self-out)
3. `uv run python -m cheongyak_rag.retrieval.chunk_report`가 `docs/73-chunking.md`를 쓴다.
   첫 줄은 결론 한 문장 — 고른 후보와 `article` 대비 hybrid recall@5 차이(95% CI, p)
4. 두 번째 실행에서 OpenAI 호출 0회, 같은 후보의 `results.jsonl`이 바이트 단위로 같다
5. `uv run python -m cheongyak_rag.retrieval.query "질문"`이 고른 구조로 조문 청크 상위 5개
   (조 번호·위치·본문 앞 80자)와 FAQ 상위 3개(q_no·질문)를 출력하고 exit 0
6. `runs/73/`과 `docs/73-chunking.md`를 커밋한다. `data/`는 커밋하지 않는다
7. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 고른 구조에서 상세 내용이 더 잘 검색되나.** 설계 §1의 규칙으로 고른 후보와 `article`의
   golden 123문항 hybrid recall@5 차이, paired bootstrap 95% CI(10,000회, seed 0):
   - CI 하한 > 0 → **차이 있음**. 그 후보를 고른다
   - CI가 0을 포함하고 신뢰구간 폭의 절반 ≤ 0.05 → **차이 없음**. `article` 유지
   - CI가 0을 포함하고 신뢰구간 폭의 절반 > 0.05 → **판정 불가**. `article` 유지
   - 모든 후보의 CI 상한 < 0 → **모든 후보가 낮다**. `article` 유지 <!-- style-exempt -->
   - 같은 세 구간을 「정답 조가 긴 문항」 부분집합(정답 조 글자 수가 조문 중앙값 초과)에서도 내고 리포트에 적는다
2. **재현.** `article` 후보의 recall@5가 #131과 소수 셋째 자리까지 같다(bm25 0.680 · dense 0.545 ·
   hybrid 0.722, `runs/{bm25,dense,hybrid}/results.jsonl`). 같으면 통과. 다르면 버그다 — 원인을 찾기
   전에는 다른 후보를 재지 않는다
3. **청크 보존.** 후보마다, 조의 청크들에서 머리를 뗀 텍스트를 이으면 그 조의 본문 줄과 같다.
   누락 0·중복 0이면 통과, 하나라도 있으면 버그
4. **짧은 청크.** 글자 수 10 미만 청크 비율: ≤ 2% 통과 / 2~5% 리포트에 목록 / > 5% 청킹 규칙 결함으로 보고 고친다
5. **FAQ 자기 빼기 점검.** 자기 쌍을 넣고 돌렸을 때 자기 쌍이 1위인 비율: ≥ 0.95 통과 / 0.85~0.95 놓친 것
   목록 / < 0.85 버그. leave-self-out run의 상위 5개에 자기 쌍·같은 질문 쌍이 0개여야 한다(1개라도 있으면 버그)
6. **붙은 단어 (#73 페이지에서 옮김).** FAQ 질문 중 목차와 공백만 다른 32쌍(`faq_report`의 `spacing_diffs`)에서,
   붙은 본문 질문과 목차의 띄어 쓴 질문 사이의 kiwi 토큰 Jaccard 평균과 임베딩 코사인 평균:
   - 토큰 ≥ 0.95 이고 코사인 ≥ 0.98 → 영향 없음
   - 토큰 < 0.90 이거나 코사인 < 0.95 → 공백 복원을 별도 티켓으로 빼야 함, PR 본문에 적는다
   - 그 사이 → 쌍별 값을 리포트에 목록

## 이번에 안 하는 것

설계 §이번에 안 하는 것을 그대로 따른다. 특히 유효구간·지역·공급유형 메타데이터, 형태소 처리 변경,
golden set 변경, 조문·FAQ 섞은 순위, pgvector 적재는 하지 않는다.

## 작업 환경

- `.venv`는 이 워크트리 자체 것이다(이미 `uv sync` 했다). 메인 repo의 `.venv`를 쓰지 않는다
- `.env`는 메인 repo 것의 심볼릭 링크다. `OPENAI_API_KEY`는 셸 환경변수에 있다. 비어 있으면 HARD 오류로 멈춘다
- `data`는 메인 repo `data/`의 **심볼릭 링크**다. 법령·FAQ jsonl과 임베딩 캐시가 거기 있다. 다시 받지 않는다.
  `data`를 지우거나 그 안을 비우지 말 것. `git add`에 넣지 말 것(`.git/info/exclude`에 `/data`가 있다)
- 새 의존성 넣지 않는다

## Tasks

기존 `src/cheongyak_rag/retrieval/`의 `corpus`·`search`·`embed`·`evaluate`·`compare`·`golden`을
재사용한다. #131 파일의 동작은 바꾸지 않는다(#131 run을 다시 돌리면 같은 결과가 나와야 한다).
Task 하나 = 커밋 하나.

### Task 1 — 청크 (`chunk.py`)

- `Chunk(chunk_id, label, path, text, source, meta)` — `label`은 조(`제2조`), `path`는 위치
  (`제2조` · `제2조제1항` · `제2조제4호` · `제2조제1항제2호가목`), `source`는 `law`|`faq`
- `law_chunks(rows, candidate) -> list[Chunk]` — 후보 5개(설계 §1 표). 법령 jsonl의 `paragraphs`·`items`·
  `subitems` 구조로 자른다. 텍스트 정리는 `corpus._clean`과 같은 규칙. 삭제 조문 제외
- `faq_chunks(faq_rows, golden_labels) -> list[Chunk]` — 쌍 하나 = 청크. 텍스트는 질문 + 줄바꿈 + 답변.
  meta에 `q_no`·`major`·`middle`·`minor`·`cited`(golden 규칙으로 뽑은 규칙 조)
- CLI: 통과 기준 1
- 테스트: `article` 후보 텍스트가 `corpus.load_articles`의 `text`와 같다 / `item` 후보에 `제2조제4호` 청크가 있고
  「무주택세대구성원」이 들어 있다 / 항이 없는 조는 `paragraph` 후보에서 조 전체 하나 / `+head` 후보는 모든 청크가
  `제N조(제목)`로 시작 / 실패 징후 3 보존 검사를 함수로 만들어 실제 데이터로 통과

### Task 2 — 청크 순위 → 조 순위 (`chunk_eval.py`)

- `article_ranking(chunk_ranking: list[Chunk]) -> list[label]` — 조의 첫(가장 높은) 청크만 남긴다
- 후보 하나: BM25(청크) · dense(청크 임베딩, `Embedder` 캐시) → 각각 조 순위 → hybrid = `rrf([bm25_조, dense_조])`
- 지표는 `evaluate.metrics` 재사용. 줄에 정답 조마다 bm25·dense·hybrid 순위, 그리고 그 조에서 가장 높이 오른
  청크의 `path`를 남긴다
- `config.json`: 후보·청크 수·모델·k1·b·RRF k·질문 수·실행 시각·커밋(`evaluate._commit` 재사용)·OpenAI 호출 수
- 테스트: 가짜 청크로 집계 손계산 / 같은 조 청크 둘이 순위에 한 번만 / 가짜 임베더 주입(API 0) /
  가짜 데이터에서 `article` 후보가 `evaluate.evaluate_run`과 같은 순위를 낸다

### Task 3 — FAQ 검색 (`chunk_eval.py --faq`)

- golden 문항 i마다 FAQ 청크에서 쌍 i와 질문 텍스트가 같은 쌍을 빼고 BM25·dense·hybrid 순위
- `faq_hit@5`: 남은 상위 5개 중 하나라도 `cited`가 정답 조와 겹치면 1. `faq_hit@1`도 같이
- 실패 징후 5의 자기 포함 점검 run도 같이 돌려 `runs/73/faq/self_check.json`에 쓴다
- 테스트: 자기 쌍이 결과에 안 나온다 / 같은 질문 텍스트 쌍도 빠진다 / 손계산

### Task 4 — 붙은 단어 측정

- `faq_report`의 목차 대조에서 `spacing_diffs` 쌍을 가져와(재사용, 새로 짜지 않는다) 실패 징후 6의 두 값을 잰다
- 목차 텍스트는 `data/raw/faq-20240529.pdf`에서 `faq.parse_toc`로 읽는다. PDF를 다시 받지 않는다
- `runs/73/spacing.json`에 쌍별 값과 평균
- 테스트: 같은 문장이면 Jaccard 1·코사인 1(가짜 임베더)

### Task 5 — 리포트 (`chunk_report.py`)

- `compare.paired_permutation_p`·`bootstrap_ci`·`verdict`를 재사용한다
- `docs/73-chunking.md` 절:
  1. 결론 한 문장 + 실패 징후 1의 구간
  2. 후보 표 — 청크 수·글자 수 중앙값·bm25/dense/hybrid recall@5·hit@1·mrr, `article` 대비 hybrid 차이 CI·p
  3. 정답 조가 긴 문항 부분집합 — 같은 표
  4. 고른 후보와 `article`이 hit@5에서 갈린 문항 전부 — 질문, 정답 조, 두 후보의 순위, 고른 후보에서 가장 높이 오른 청크 `path`
  5. FAQ — `faq_hit@1`·`faq_hit@5` (bm25·dense·hybrid), 자기 포함 점검 값
  6. 정의형 질문 표본 — 설계 §3의 질문 9개, `article`과 고른 후보 각각 조문 상위 5개(조·path) + FAQ 상위 3개(q_no·질문).
     「이 표본의 정답은 사람이 단 라벨이 아니다」를 절 맨 위에 적는다
  7. 붙은 단어 — 실패 징후 6
  8. 점검 — 실패 징후 2·3·4의 값
- 판단어(개선·우수)를 쓰지 않는다. 숫자에는 비교 대상(`article`, #131 값)을 붙인다
- 테스트: 차이가 모두 0이면 「차이 없음」 문장 / 고르는 규칙 — CI 하한 > 0인 후보가 없으면 `article` / 갈린 문항이 빠짐없이 들어간다

### Task 6 — 질문 한 줄 검색 (`query.py`)

- `search(question, k=5) -> {"law": [Chunk…], "faq": [Chunk…]}` — 고른 후보(`runs/73/selected.json`에
  `chunk_report`가 쓴다)로 hybrid 순위. 조문은 조 단위로 중복 없이 상위 k개, 각 조에서 가장 높이 오른 청크를 돌려준다
- CLI: 통과 기준 5. #139가 이 함수를 generator 입력으로 쓴다
- 테스트: 가짜 임베더로 출력 꼴, 같은 조가 두 번 안 나온다

### Task 7 — 실제 실행

1. `chunk` → 실패 징후 3·4
2. `chunk_eval --candidate article` → 실패 징후 2. 다르면 멈추고 고친다
3. 나머지 후보 4개, `--faq` → 실패 징후 5
4. Task 4 측정 → 실패 징후 6
5. 아무 후보 하나를 다시 돌려 통과 기준 4
6. `chunk_report` → 리포트와 `selected.json`. 실패 징후 1
7. `query "무주택 세대구성원 기준이 뭔가요?"` → 통과 기준 5, 출력을 PR 본문에 붙인다
8. `runs/73/`, 리포트 커밋. 실행 끝에 새로 임베딩한 텍스트 수와 OpenAI 호출 수를 PR 본문에 적는다

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: `uv run python -m cheongyak_rag.retrieval.query "무주택 세대구성원 기준이 뭔가요?"`가 exit 0으로 끝나는 것을 smoke run으로 본다
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/` 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).

내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만 **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.

커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## Done criteria

- 통과 기준 1~7 전부
- 실패 징후 1~6 각각의 측정값과 어느 구간인지가 PR 본문에 있다
- PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절 — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 값과 구간, 정의형 표본의 「무주택 세대구성원」 질문 결과)
- PR 본문의 수치는 커밋된 `docs/73-chunking.md`와 같아야 한다. 리포트를 다시 만들었으면 PR 본문도 고친다
- PR 제목: `[#73] retrieval: 조문·FAQ 청킹 후보 비교와 검색 구조`
- PR 생성 뒤 Notion #73 페이지(`3aa41e61-65c0-817c-989e-e70c7f4a2da9`) `PR` 프로퍼티에 PR URL을 넣는다 (`NOTION_API_KEY`, Notion-Version 2022-06-28, `PATCH /v1/pages/{id}`)
- 커밋 접두사는 `~/.claude/rules/github.md` 표의 것만, 괄호 없이. 커밋 메시지는 한글
