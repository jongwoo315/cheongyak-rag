# #70 유권해석 FAQ 파싱 — 구현 계획

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

**Tier:** B · **Notion:** #70 · **설계:** `docs/plans/70-1001-design-faq-parse.md` (먼저 읽을 것)

## jw 기준

에러없이 pdf파싱이 이루어지고, 특히 qna 쌍이 섹션에 맞게 분리가 된다

## 통과 기준

1. `uv run python -m cheongyak_rag.ingest.faq` 가 exit 0으로 끝나고 `data/processed/faq-20240529.jsonl`을 쓴다
2. 쌍 수 = 480, `q_no`가 1~480 빈틈·중복 없음
3. 섹션 대조 리포트(Task 4)가 실행 끝에 출력된다 — 아래 §실패 징후 1번의 수치가 거기서 나온다
4. 모든 쌍의 `question`·`answer`가 비어 있지 않다
5. PDF는 `data/raw/faq-20240529.pdf`에 캐시되고, 있으면 다시 받지 않는다(두 번째 실행 로그에 다운로드 줄이 없다)
6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 섹션 분리.** 각 쌍의 본문 섹션(`major`·`middle`·`minor`)을 목차의 같은 Q번호 섹션과
   대조한 불일치 건수. 질문 텍스트도 목차 질문과 공백 정규화 후 같아야 일치로 센다.
   - **불일치 0** → 통과
   - **불일치 1~10** → 불일치 전부를 PR 본문에 표로 붙이고 건마다 원인을 적는다:
     `PDF` (목차와 본문이 실제로 다르게 인쇄됨 — 해당 쪽 번호와 두 문자열을 근거로) / `파서`.
     `파서` 원인은 고치고 다시 잰다. 루프가 끝날 때 `파서` 원인이 남아 있으면 그대로 PR에 적는다
   - **불일치 11 이상, 또는 쌍 수 ≠ 480** → 섹션 경계 인식 자체가 틀렸다. 접근을 다시 짠다
   - baseline 없음 — 첫 측정이다
2. **jw 기준 — 에러 없이.** 실행 중 예외 0, exit 0. PyMuPDF가 stderr에 내는 경고는 실패로 치지 않되
   건수를 리포트에 적는다
3. **답변 경계 새는 것.** 답변 안에 (a) 쪽 머리말(대분류 제목 반복) (b) 목차에 있는 중분류·소분류 제목
   (c) 다음 질문 텍스트가 들어간 쌍 수. **0이면 통과 / 1~5면 목록을 PR에 붙인다 / 6 이상이면 실패**
4. **답변 길이 이상치.** 답변 글자 수 분포(최소·중앙값·최대)를 리포트에 적고, 30자 미만 또는
   3000자 초과인 쌍을 전부 나열한다. 임계값이 아니라 눈으로 볼 목록이다 — 판정은 PR 게이트에서 한다

## 이번에 안 하는 것

- DB 적재·임베딩·마이그레이션 (#73). 이 PR은 alembic을 건드리지 않는다
- `가. 주요내용` 설명 본문 수집 — 건너뛴 쪽 수·글자 수만 리포트에 남긴다
- 표 구조 보존 — 표가 섞인 답변 수만 센다
- 참조조문의 법령 이름 연결

## Tasks

각 Task = 커밋 하나 (impl + test). 커밋 메시지는 한글, 접두사는 `feature:` `test:` `add:` `chore:` 중 하나,
괄호 scope 금지 (`feature(faq):` ✗).

### Task 1 — 의존성과 PDF 캐시

- `uv add pymupdf`
- `src/cheongyak_rag/ingest/__init__.py`, `src/cheongyak_rag/ingest/faq.py`
- `fetch_pdf(dest: Path) -> Path` — 파일이 있으면 그대로 반환, 없으면 설계 문서의 다운로드 URL로 받는다(httpx,
  User-Agent 지정, 쿠키 유지 — molit.go.kr은 쿠키 없이 리다이렉트를 무한 반복한다)
- 테스트: 파일이 이미 있으면 네트워크를 안 탄다 (httpx 호출을 막아 두고 확인). 실제 다운로드 테스트는 쓰지 않는다
- `data/raw/faq-20240529.pdf`는 이미 워크트리에 놓여 있다(gitignore 대상). 커밋하지 않는다

### Task 2 — 목차 파싱

- `parse_toc(doc) -> list[TocEntry]` — Q번호 → (대분류, 중분류, 소분류, 질문 텍스트)
- 목차는 본문 첫 대분류 제목이 나오기 전 쪽들이다. 두 줄로 접힌 질문을 이어 붙인다. 점선 리더(`····`)와 쪽 번호를 뗀다
- 대분류 표기가 `Ⅰ.`·`Ⅱ`(점 없음)처럼 섞여 있다 — 정규화해서 `Ⅰ. 청약자격(공통)` 꼴로 맞춘다
- 테스트: 실제 PDF로 480개, 1~480 연속, Q1·Q3(두 줄)·Q480의 섹션과 질문 텍스트를 고정값으로 확인.
  PDF가 없으면 skip하지 말고 실패시킨다 (조용한 skip 금지)

### Task 3 — 본문 파싱

- `parse_body(doc) -> list[FaqPair]` — 설계 문서 §산출물 필드 그대로
- 섹션은 **본문 제목에서** 읽는다. 목차 결과를 섹션 라벨로 복사하지 않는다 (설계 §섹션 정답)
- 질문 줄 판별에 목차의 질문 번호 순서를 쓰는 것은 괜찮다(다음에 나올 번호가 N+1이라는 것). 섹션 라벨만 금지
- 쪽 머리말·쪽 번호 제거, 법령 인용 블록은 답변에 포함
- `cited_articles`: `제\d+조(의\d+)?(제\d+항)?(제\d+호)?` 정규식, 중복 제거, 등장 순서 유지
- 테스트: Q1 질문·답변 앞부분, Q3(두 줄 질문), 각 대분류 첫 질문 하나씩, Q480의 섹션을 고정값으로 확인

### Task 4 — CLI와 대조 리포트

- `python -m cheongyak_rag.ingest.faq` — fetch → parse_toc → parse_body → JSONL 쓰기 → 리포트 출력
- 리포트에 들어갈 것: 쌍 수, 섹션 불일치 건수와 전체 목록, 답변 경계 새는 쌍 목록(실패 징후 3), 답변 길이
  분포와 이상치 목록, 표가 섞인 답변 수, 건너뛴 `주요내용` 쪽 수·글자 수, stderr 경고 건수
- `data/processed/`를 `.gitignore`에 추가한다. JSONL은 커밋하지 않는다
- 테스트: 리포트 함수가 일부러 섹션을 틀린 입력에서 불일치를 잡는다 (대조 로직 자체의 테스트)

### Task 5 — 실제 실행과 측정

- 실제 PDF로 CLI를 두 번 돌린다. 두 번째 실행에 다운로드가 없는지 확인
- §실패 징후 1·3 결과에 따라 Task 3로 돌아가 고친다. 불일치 원인을 `PDF`로 분류할 때는 쪽 번호와 목차·본문
  두 문자열을 근거로 남긴다. 근거 없이 `PDF`로 분류하지 않는다
- README `## 메모` 위에 `## 데이터 수집` 절 추가 — FAQ 실행 명령 한 줄과 산출물 경로

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8000 &) ; sleep 8; curl -sf http://127.0.0.1:8000/health && echo BOOT_OK ; pkill -f "uvicorn cheongyak_rag"`. Postgres는 메인 repo(`/Users/jw/prv/cheongyak-rag`)에서 `docker compose up -d`로 이미 떠 있다. 워크트리에서 compose를 올리지 말 것(프로젝트 이름이 달라져 같은 포트를 다투는 별개 DB가 생긴다). CLI는 Task 5에서 이미 실행했다.
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.

## Done criteria

- 위 §통과 기준 1~6이 전부 참이다
- §실패 징후 1·3의 수치가 PR 본문에 있고, 불일치·새는 쌍이 있으면 전체 목록과 원인이 같이 있다
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — 이 plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과
  (실패 징후 1·2의 수치와 어느 구간인지)
- PR 제목: `#70 feature: 국토부 청약 FAQ PDF를 Q&A 쌍으로 파싱`
- PR 생성 후 Notion #70의 `PR` 프로퍼티에 URL을 넣는다:
  `curl -X PATCH https://api.notion.com/v1/pages/3aa41e61-65c0-81a8-a459-c05d55e5c175`
  (`Notion-Version: 2022-06-28`, `NOTION_API_KEY`, body `{"properties":{"PR":{"url":"<PR URL>"}}}` — python으로 파일을 만든 뒤 `--data-binary @file`)
- base 브랜치는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- `docs/decisions.md`의 #70 행은 건드리지 않는다 (PR 게이트에서 사람이 채운다)
