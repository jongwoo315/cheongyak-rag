# #69 법령 수집 — 구현 계획

> **For Claude:** This plan is executed via /ralph-loop:ralph-loop in a detached orch session.
> You are ALREADY in the worktree, checked out on the feature branch. Do NOT switch branches,
> create another worktree, or use AskUserQuestion / any interactive prompt — the session is
> headless and cannot receive input, so always take the autonomous (recommended) default and
> keep working. Do NOT use superpowers:executing-plans or subagent-driven-development.
> Emit `<promise>RALPH_DONE</promise>` ONLY when every Done-criteria item and every Pre-PR check
> is genuinely true AND the PR has been created — never to escape the loop.
> On a HARD, retry-proof API error (OpenAI insufficient_quota, 401/403, exhausted billing), STOP —
> do NOT emit RALPH_DONE, do NOT create a PR, do NOT spin retrying. It surfaces via the orch
> completion notification; a human fixes billing. (Transient TPM 429 is different — pace and retry.)
> A TRANSIENT error that stops being transient counts as HARD. If 429/529 keeps surfacing AND you
> have produced no commit and no file change for 20 minutes, STOP the same way. Waiting and
> spinning are indistinguishable in a headless loop — nobody is watching the screen, and the loop
> re-submits the prompt after every failed turn, so a server-side outage burns the whole iteration
> budget while the picker still reads `working`.

**Tier:** B · **Notion:** #69 · **설계:** `docs/plans/69-1005-design-law-parse.md` (먼저 읽을 것)

## jw 기준

api키가 정상적으로 작동한다, 규칙 조문을 제대로 파싱한다

## 통과 기준

1. `uv run python -m cheongyak_rag.ingest.law`가 `.env`의 `LAW_OC`로 검색·본문 두 호출을 하고 exit 0으로 끝난다.
   `data/raw/law-008243-<시행일>.json` 캐시와 `data/processed/law-008243-<시행일>.jsonl`을 쓴다
2. `LAW_OC`가 비어 있으면 `OC=test`로 대신하지 않고 exit 1, 원인 문구를 낸다 (테스트로 확인)
3. 대조 리포트(Task 4)가 실행 끝에 출력된다 — §실패 징후 1·3의 수치가 거기서 나온다
4. 현행 버전은 검색 응답에서 고른다(`현행연혁코드 == 현행`). MST `286965`를 코드에 박지 않는다
5. 캐시 파일이 있으면 본문을 다시 받지 않는다. 검색은 매번 한다(현행 MST가 바뀌었는지 보는 호출이라서)
6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 조문을 제대로 파싱.** 원본 JSON의 텍스트 필드(`조문내용`·`항내용`·`호내용`·`목내용`)를
   파서와 **따로 짠 코드로** 모두 모아, JSONL에서 빠진 것과 두 번 들어간 것을 센다.
   - **누락·중복 0, 개수(조문 90 · 장절 20 · 항 304 · 호 504 · 목 169) 일치** → 통과
   - **누락·중복 1~5** → 건마다 조문 번호·원문·원인을 PR 본문 표로 붙인다. 고칠 수 있으면 고치고 다시 잰다
   - **누락·중복 6 이상, 또는 개수 불일치** → 계층 처리(list·dict·없음)가 틀렸다. 접근을 다시 짠다
   - 개수는 2026-10-05에 현행 `2026-06-15` 판본에서 센 값이다. 실행 시 현행이 바뀌어 있으면 원본에서 다시 센 값과 대조하고 그 사실을 PR에 적는다
   - baseline 없음 — 첫 측정
2. **jw 기준 — API 키 작동.** `LAW_OC`로 두 호출이 HTTP 200이고 `법령명_한글 == 주택공급에 관한 규칙`.
   아니면 HARD 오류로 보고 멈춘다 — PR을 만들지 않고 RALPH_DONE을 내지 않는다
3. **#70 FAQ 인용과 현행 법령 대조 (값만, 임계값 없음).** FAQ JSONL의 `cited_articles`를 조 단위로 묶어
   (a) 현행에 없는 조 (b) `2024-05-29` 이후 개정 날짜가 붙은 조를 인용한 FAQ 쌍 수를 센다.
   판정은 PR 게이트에서 한다. FAQ의 `제N조`가 어느 법령인지(규칙·법·시행령) 안 갈라져 있으므로
   (a)는 다른 법령 조문이 섞여 실제보다 클 수 있다고 같이 적는다

## 이번에 안 하는 것

- 과거 시행일 버전 (#78)
- 별표 13개·부칙 본문 — 개수와 제목만 리포트에 남긴다
- DB 적재·임베딩·마이그레이션 (#73·#74). alembic을 건드리지 않는다
- 개정 감지 스케줄러

## Tasks

각 Task = 커밋 하나 (impl + test). 커밋 메시지는 한글, 접두사는 `feature:` `test:` `add:` `fix:` `docs:` `chore:` 중 하나,
괄호 scope 금지.

### Task 1 — 설정과 API 클라이언트

- `config.py`에 `law_oc`가 이미 있는지 보고 없으면 추가 (`.env.example`에는 `LAW_OC`가 이미 있다)
- `src/cheongyak_rag/ingest/law.py`: `search_current(oc) -> {mst, law_id, effective_date}`, `fetch_law(oc, mst, dest) -> dict`
- 응답 확인: 상태 코드 + JSON 파싱 + `법령명_한글`. 실패면 응답 앞 200자를 붙여 예외
- 테스트: `httpx.MockTransport`로 정상·오류 응답, 빈 `LAW_OC` → 예외. 실제 네트워크 테스트는 쓰지 않는다
- 실제 호출은 Task 5에서 한다

### Task 2 — 조문 파싱

- `parse_articles(law_json) -> list[Article]` — 설계 §산출물 필드
- `항`·`호`·`목`이 list·dict·없음 셋 중 무엇으로 와도 같은 결과를 낸다. 한 곳(헬퍼 하나)에서 처리한다
- `전문`(장·절)을 뒤따르는 조문의 `chapter`·`section`에 붙인다
- 가지번호 → `label` `제4조의2`
- `<개정 …>`·`<신설 …>` 날짜를 `amendments`로 뽑는다. 본문 `text`에서는 지우지 않는다 (원문 대조가 깨진다)
- 테스트 픽스처: 실제 응답을 `data/raw/`에 받아 쓰되, **항 없는 조·항 dict인 조·가지 조·삭제 조** 각 하나를 골라
  `tests/fixtures/law_sample.json`으로 잘라 커밋한다(작은 파일). 고정값으로 확인

### Task 3 — 대조 코드 (파서와 따로)

- `ingest/law_report.py`: 원본 JSON을 재귀로 훑어 텍스트 필드를 모으는 함수 — `parse_articles`를 부르지 않는다
- 누락·중복 세기, 계층 개수 세기(원본 쪽·출력 쪽 각각)
- 테스트: 일부러 항 하나를 뺀 출력, 두 번 넣은 출력에서 각각 잡는다

### Task 4 — CLI와 리포트

- `python -m cheongyak_rag.ingest.law` — search → fetch(캐시) → parse → JSONL → 리포트
- 리포트: 현행 MST·시행일, 계층 개수(원본 vs 출력), 누락·중복 목록, 별표·부칙 개수와 별표 제목, §실패 징후 3 수치
- §실패 징후 3은 FAQ JSONL(`data/processed/faq-20240529.jsonl`)이 없으면 FAQ CLI를 먼저 돌리라는 문구를 내고 그 항목만 건너뛴다
  (PDF는 `data/raw/faq-20240529.pdf`에 있다. 이 워크트리에서 `python -m cheongyak_rag.ingest.faq`로 만들 수 있다)
- 검증 실패면 exit 1, 이전 JSONL을 덮어쓰지 않는다 (#70 `af2d736`과 같은 방식)

### Task 5 — 실제 실행과 측정

- `LAW_OC`로 CLI를 두 번 돌린다. 두 번째에 본문 다운로드가 없는지 확인
- §실패 징후 1에 따라 Task 2로 돌아가 고친다
- README `## 데이터 수집` 절에 법령 실행 명령 한 줄 추가

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8000 &) ; sleep 8; curl -sf http://127.0.0.1:8000/health && echo BOOT_OK ; pkill -f "uvicorn cheongyak_rag"`. Postgres는 메인 repo(`/Users/jw/prv/cheongyak-rag`)에서 `docker compose up -d`로 이미 떠 있다. 워크트리에서 compose를 올리지 말 것. CLI는 Task 5에서 이미 실행했다.
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.

**`uv add`로 의존성을 추가하지 말 것** — 이 워크트리의 `.venv`는 메인 repo와 공유하는 심볼릭 링크라, 워크트리에서 `uv sync`·`uv add`를 하면 메인 repo의 editable 설치 경로가 바뀐다(#70에서 실제로 났다). 이번 Task에는 새 의존성이 필요 없다(httpx 기존). 꼭 필요하면 추가하지 말고 PR 본문에 적는다.

## Done criteria

- 위 §통과 기준 1~6이 전부 참이다
- §실패 징후 1·3의 수치가 PR 본문에 있다
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — 이 plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과
  (실패 징후 1·2의 수치와 어느 구간인지)
- PR 제목: `#69 feature: 주택공급규칙 현행 조문을 법제처 API로 수집·파싱`
- PR 생성 후 Notion #69의 `PR` 프로퍼티에 URL을 넣는다:
  `curl -X PATCH https://api.notion.com/v1/pages/3aa41e61-65c0-8165-8081-d9704c2da45c`
  (`Notion-Version: 2022-06-28`, `NOTION_API_KEY`, body `{"properties":{"PR":{"url":"<PR URL>"}}}` — python으로 파일을 만든 뒤 `--data-binary @file`)
- base 브랜치는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- `docs/decisions.md`의 #69 행은 건드리지 않는다 (PR 게이트에서 사람이 채운다)
