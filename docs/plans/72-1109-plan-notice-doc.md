# #72 공고문 수집(L3) — 구현 계획

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
> On a HARD, retry-proof API error (OpenAI insufficient_quota, 401/403, exhausted billing), STOP —
> do NOT emit RALPH_DONE, do NOT create a PR, do NOT spin retrying. It surfaces via the orch
> completion notification; a human fixes billing. (Transient TPM 429 is different — pace and retry.)
> A TRANSIENT error that stops being transient counts as HARD. If 429/529 keeps surfacing AND you
> have produced no commit and no file change for 20 minutes, STOP the same way. Waiting and
> spinning are indistinguishable in a headless loop — nobody is watching the screen, and the loop
> re-submits the prompt after every failed turn, so a server-side outage burns the whole iteration
> budget while the picker still reads `working`.

**Tier:** B · **Notion:** #72 · **설계:** `docs/plans/72-1109-design-notice-doc.md` (먼저 읽을 것 — 착수 때 실측한 사실과 결과 5개 정의가 거기 있다)

**흐름:** 끝까지 도는 흐름은 이미 있다(#71~#85). 이 티켓은 그 흐름의 「공고 수집」 옆에 공고문 파일을 받아 두는 단계를 더한다.
판정 흐름은 아직 이 파일을 읽지 않는다 — 읽는 쪽은 #75(골든셋)와 앞으로의 L3 청킹이다. 판정·검색·웹 코드를 고치지 않는다.

## jw 기준

공고문 pdf를 오류없이 다운로드할 수 있다

## 통과 기준

1. `uv run python -m cheongyak_rag.ingest.notice_doc`가 실제 DB `notices` 84건을 읽어(쓰지 않는다) 공고마다 상세 페이지를 받고,
   공고문 링크마다 첨부를 받아 `data/raw/notices/`(PDF)·`data/raw/notices/quarantine/`(그 밖)에 저장하고,
   목록 `data/raw/notices/manifest.jsonl`과 실행 요약 `runs/72/last_run.json`을 쓰고 exit 0이다.
   공고 하나가 실패해도 나머지를 계속하고, 실패는 결과 `error`로 남긴다
2. 파일 이름은 `<houseManageNo>_<pblancNo>_<atchmnflSeqNo>_<atchmnflSn>.<ext>`. `ext`는 앞 바이트로 정한 것이다
3. `Content-Disposition`은 `filename*=UTF-8''…`(RFC 5987)와 `filename="…"` 두 꼴을 다 읽는다. 둘 다 있으면 `filename*`를 따른다.
   헤더가 없으면 앞 바이트만으로 정하고 「헤더 없음」을 목록에 적는다
4. 목록 한 줄(링크 하나) 칸: `house_manage_no` · `pblanc_no` · `url` · `header_filename` · `header_ext` · `magic_ext` · `ext_mismatch` ·
   `result`(설계 §3의 5개 중 하나) · `path` · `bytes` · `sha256` · `pages` · `text_chars` · `error`(문구, 없으면 null) · `fetched_at`.
   링크가 없는 공고는 `url`이 null인 한 줄을 남기고 `result`=`no_link`, 같은 페이지의 다른 외부 링크를 `error` 대신
   `note`에 적는다
5. 같은 명령 두 번째 실행에서 파일이 있고 크기·sha256이 같으면 첨부를 다시 받지 않는다. 두 번째 실행의 새 다운로드 수가 0이고
   결과별 공고 수가 첫 실행과 같다
6. `uv run python -m cheongyak_rag.ingest.notice_doc_report`가 `docs/72-notice-doc.md`를 쓴다. 첫 줄은 결론 한 문장(오류 수 /
   링크 있는 공고 수, PDF 수, 격리 수, 링크 없음 수). 그 아래 결과 5개 표, 오류·격리·링크 없음 공고 번호와 이름, 텍스트 없는 PDF 목록,
   확장자 어긋남 목록, 재실행 결과, 실행 시간·받은 바이트 합
7. 요청 사이 0.5초, 429·5xx·연결 오류는 1·2·4·8초 뒤 최대 4번 다시 시도한다. 첨부가 50MB를 넘으면 받다 멈추고 `error`로 센다.
   시간 제한은 페이지 30초, 첨부 120초
8. 테스트는 네트워크를 쓰지 않는다(`httpx.MockTransport`). 실제 페이지에서 잘라 만든 HTML 조각 두 개(링크 있음 — 2026000517,
   링크 없음 — 2026820012)를 `tests/fixtures/`에 둔다. 다룰 것: 두 헤더 꼴, 헤더 없음, 앞 바이트별 확장자, 확장자 어긋남,
   PDF인데 안 열림, 크기 초과, 429 뒤 성공, 재실행에서 다시 안 받음, 링크 없음
9. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 공고문을 오류 없이 받았나.** 측정값은 「공고문 링크가 있는 공고 중 결과가 `error`인 공고 수」다(착수 때 74건).
   - 0 → 통과
   - 1~3 → 오류 공고마다 URL·HTTP 상태·문구를 리포트에 적고, 그 공고만 한 번 더 받는다. 두 번째에 받아지면 두 값을 다 적는다
     (일시 오류). 그래도 실패하면 원인을 리포트에 적고 끝낸다
   - 4 이상 → 미완. 원인을 고치고 다시 잰다. 고칠 수 없는 원인(사이트 차단 등)이면 그 사실과 값을 리포트·PR 본문 맨 위에 적는다
   - 링크 없음(LH 10건)은 오류에 넣지 않고 따로 적는다. 링크 있는 공고 수가 74가 아니면 그 차이와 이유를 리포트에 적는다
2. **링크를 못 찾은 것이 사이트 구조가 바뀐 탓인가.** 결과 `no_link`가 LH 10건 밖에서 나오면 그 공고 HTML의 `pop_btn_txt` 부분을
   리포트에 붙인다. 10건 밖 `no_link`가 0 → 통과 · 1~3 → 리포트에 적는다 · 4 이상 → 링크 찾는 코드를 고치고 다시 잰다
3. **텍스트 없는 PDF(스캔본 의심).** 오류가 아니다. 건수와 공고 번호만 리포트에 적는다(baseline 없음 — 첫 측정)
4. **HWP 비율.** 오류가 아니다. `hwp`·`other` 건수를 리포트에 적는다(baseline 없음 — 첫 측정. 바탕 설계가 「수집 돌려봐야 나옴」으로 남긴 값)

## 범위 밖

- LH청약플러스에서 LH 10건 공고문 받기 — 다른 사이트다
- PDF 본문 텍스트 추출·섹션 나누기·chunks 적재 — L3 청킹 티켓 몫. `pages`·`text_chars`만 센다
- HWP 파싱
- DB 테이블·마이그레이션
- 판정·검색·API·웹 코드 변경, Vercel·Neon 배포

## Task

1. **헤더·확장자 함수** — `src/cheongyak_rag/ingest/notice_doc.py`에 `parse_disposition(header) -> str | None`(두 꼴), `magic_ext(head: bytes) -> str`
   (`pdf`·`hwp`·`hwpx`·`unknown`), `find_doc_links(html) -> list[str]`(`getAtchmnfl.do` 절대 URL), `other_links(html)`. 테스트 먼저.
   HTML 조각은 실제 페이지(위 두 공고)를 받아 `pop_btn_txt` 앞뒤만 남겨 `tests/fixtures/`에 둔다 — 이 한 번만 네트워크를 쓴다
2. **받기·저장·판정** — 공고 하나를 받아 목록 줄을 돌려주는 함수(재시도·크기 제한·시간 제한·PDF 열기·`pages`·`text_chars`·저장 위치),
   재실행에서 다시 안 받기. `MockTransport`로 테스트
3. **CLI** — `python -m cheongyak_rag.ingest.notice_doc [--limit N] [--out runs/72/last_run.json]`. DB에서 `house_manage_no`·`pblanc_no`·`pblanc_url`을
   읽고(SELECT만), 목록·실행 요약을 쓴다. 요약: 공고 수, 결과별 공고 수, 오류 수, 새 다운로드 수, 받은 바이트, 걸린 시간, 시작·끝 시각
4. **실제 실행 두 번** — 첫 실행 → `runs/72/last_run.json`을 `runs/72/run1.json`으로 복사 → 두 번째 실행(`runs/72/last_run.json`). 실패 징후 1의 구간에 따라
   처리한다
5. **리포트** — `src/cheongyak_rag/ingest/notice_doc_report.py` → `docs/72-notice-doc.md`. `docs/concepts.md`에 개념 표 「공고문 수집 결과 5개」를
   더한다(설계 §3 그대로, 정의한 파일·줄 칸 포함). README 「데이터」 또는 그에 맞는 절에 한 줄과 실행 명령을 더한다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8 ; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`
>    - 웹(`web/`)은 고치지 않으므로 `npm run build`는 돌리지 않는다. 고쳤다면 돌린다
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check`
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 컨테이너가 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 공고문 파일은 `data/raw/notices/`에 쓴다(심볼릭 링크라 메인 repo `data/raw/`에 쌓인다. gitignore 대상이라 커밋되지 않는다). `data/raw/`의 다른 파일과 `data/cache`를 지우거나 다시 쓰지 않는다
- 실제 DB는 읽기만 한다. `notices`·`notice_models`·`chunks`·`law_versions`·`notice_law_versions`·`traces`·`verdict_daily_count`에 쓰지 않는다. 마이그레이션을 더하지 않는다
- 테스트는 네트워크·실제 DB를 쓰지 않는다. DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다
- 청약홈 사이트에 보내는 요청은 실제 실행 두 번 + fixture 만들기 + 실패 징후 1의 다시 받기뿐이다. 실행을 그 이상 되풀이하지 않는다 — 고친 뒤 다시 잴 때만 한 번 더 실행한다
- `User-Agent`는 일반 브라우저 문자열로 둔다. NetFUNNEL 대기 페이지가 오면(HTML에 `netfunnel`) 30초 쉬고 다시 시도하고, 그래도 오면 그 공고를 `error`로 센다
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8171을 쓰고 끝나면 끈다

## Done criteria

- 통과 기준 1~9가 전부 참이고, 실패 징후 1~4의 측정값과 구간이 `docs/72-notice-doc.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `docs/concepts.md`에 개념 표 「공고문 수집 결과 5개」를 더했다. `## 용어` 표에는 main 세션이 이미 넣은 「공고문」·「격리」 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push -u origin feat/72-notice-pdf`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#72] feature: 청약홈 공고문 수집 — 첨부 다운로드, 확장자 판별, HWP 격리`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(오류 수 / 링크 있는 공고 수, 구간) + 링크 없음 수와 번호. 그 아래 Summary / Changes / Notes
- PR을 만든 뒤 Notion #72 페이지(`3aa41e61-65c0-81f0-816d-cc227b4e5744`)의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81f0-816d-cc227b4e5744 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
