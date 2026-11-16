# #135 FAQ 인용 커버 셈을 법령 이름으로 — 구현 계획

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

**Tier:** B — 리포트 셈 하나를 바꾸고 분류 함수를 옮긴다. 판정·검색·DB·OpenAI는 건드리지 않는다. 새 일은 인용 자리마다 법령 이름을 따로 읽어 분류를 검사하는 것
**Notion:** #135 (`3f841e61-65c0-81af-a9c3-eddbb2de0c0a`)
**흐름:** 이미 있다. 이 티켓은 판정 흐름 밖의 수집 리포트(#69 `law_report`의 FAQ 인용 커버)를 고친다. 판정 흐름의 stub은 바꾸지 않는다

## jw 기준

FAQ 40쌍에서 발생하던 문제를 수정해 현행 규칙에 있는 조를 인용하도록 한다

(되물은 뒤: 「현행 규칙」은 주택공급에 관한 규칙만이다)

기준을 세운 사례: #69 PR #2 재판정 유보 — FAQ 480쌍 중 조문을 인용한 182쌍에서 40쌍이 현행 규칙에 없는 조를 하나 이상 인용한다(46회). 출처: `docs/decisions.md` #69 재판정 행, Notion #135 본문

Claude가 붙인 뜻: 「규칙 조를 인용했다」 = 답변의 `제N조` 한 자리 앞, 같은 문장 안에서 가장 가까운 법령 이름이 주택공급에 관한 규칙이거나 법령 이름이 없다. #131이 정답 라벨을 만들 때 쓴 분류(`src/cheongyak_rag/retrieval/golden.py` `extract_citations`) 그대로다. jw 원문의 말이 아니다.

착수 때 이 뜻으로 집계한 값(main, 2026-11-16): 40쌍의 46회는 전부 다른 법령 인용으로 분류된다(주택법 계열 24 · 도시정비법 6 · 빈집특례법 6 · 민법 4 · 건축법 시행령 2 · 조세특례제한법 2 · 그 밖 2). 규칙 인용으로 분류됐는데 현행 규칙에 없는 조는 0회다. 즉 이 뜻으로는 기준을 세운 사례가 잡히지 않는다. 40쌍은 #69 리포트가 법령 이름을 보지 않고 조 번호로만 센 데서 나왔다. jw는 이 사실을 보고 「커버 셈을 고친다」를 골랐다.

## 설계

1. **분류 함수를 한 곳에 둔다.** `retrieval/golden.py`의 `Citation`·`extract_citations`와 그 정규식·도우미를 새 모듈 `src/cheongyak_rag/ingest/citations.py`로 옮긴다. `golden.py`는 거기서 가져다 쓴다(지금 이름으로 import가 계속 되게 둔다). 복사하지 않는다 — 두 곳이 다른 규칙으로 세면 #131 정답 라벨과 리포트가 다시 갈린다
2. **커버를 다시 정의한다.** `law_report.faq_cross`가 `pair["cited_articles"]` 대신 답변 원문에 `extract_citations`를 건다
   - 분모: 규칙 인용(분류 `rule` 또는 `none`)이 하나 이상 있는 쌍
   - 커버: 그 쌍의 규칙 인용 조(항·호는 뗀다)가 전부 현행 규칙에 있다. 삭제된 조는 현행에 없다(지금과 같다)
   - 다른 법령 인용만 있는 쌍은 분모에서 빼고 따로 센다. 다른 법령 인용 자리는 앞 법령 이름별로 센다
   - 참고 줄로 예전 셈(조 번호로만 집계한 값: 인용 있는 쌍 182 · 커버 142 · 커버 안 됨 40)을 같은 함수 안에서 계속 계산해 나란히 적는다. 이름을 「번호로만 센 커버」로 붙여 새 커버와 섞이지 않게 한다
3. **분류를 따로 검사한다.** 분류는 정규식이라 틀릴 수 있고, 리포트와 #131 정답 라벨이 이제 같은 함수를 쓰므로 같이 틀린다. 그래서 하위 에이전트(Agent 도구)가 분류 결과를 보지 않고 답변 원문을 읽어 인용 자리마다 법령 이름을 붙인다(법령 이름 라벨). 분류와 법령 이름 라벨이 다른 자리를 센다
   - 대상: FAQ 답변의 모든 인용 자리(착수 때 415자리 = 규칙 183 · 다른 법령 171 · 이름 없음 61, 182쌍)
   - 하위 에이전트에게는 쌍 번호, 답변 원문, 자리마다 앞뒤 문장과 그 조 라벨만 준다. `kind`·`before`는 주지 않는다
   - 붙이는 값: `규칙`(주택공급에 관한 규칙) · `다른 법령`(+ 법령 이름) · `이름 없음`(문맥에도 법령 이름이 없다) · `모름`(문맥상 갈리지 않는다) 중 하나와 근거 구절 한 줄
   - 분류와 비교할 때 `규칙`·`이름 없음`은 분류 `rule`·`none`과 같은 쪽으로 본다(규칙 인용). `다른 법령`은 `other`. `모름`은 따로 센다
   - 같은 모델이 읽는 것이라 완전히 독립된 확인은 아니다. 리포트에 그렇게 적는다
4. **분류는 이번에 고치지 않는다.** 분류와 법령 이름 라벨이 다른 자리가 나와도 목록으로 적기만 한다. 분류를 고치면 `runs/golden.jsonl`(#131 정답 라벨 123문항)이 바뀌어 #131·#73·#139 측정값과 비교할 수 없게 된다

## 통과 기준

1. `src/cheongyak_rag/ingest/citations.py`가 있고 `retrieval/golden.py`가 거기서 가져다 쓴다. `uv run python -c "from cheongyak_rag.retrieval.golden import main; from pathlib import Path; main(Path('/tmp/golden-135.jsonl'))"`로 만든 파일이 `runs/golden.jsonl`과 바이트 단위로 같다(`cmp` exit 0)
2. `law_report.faq_cross`가 설계 2대로 센다. 단위 테스트: 규칙 이름이 붙은 현행 조 → 커버 · 규칙 이름이 붙은 없는 조 → 커버 안 됨 · 이름 없는 조 → 규칙 인용으로 본다 · 다른 법령 조만 있는 쌍 → 분모에서 빠지고 따로 센다 · 다른 법령 조인데 번호가 규칙에 있는 경우 → 커버로 세지 않는다 · 번호로만 센 커버 참고 값이 지금 셈과 같다. 기존 `faq_cross` 테스트는 새 정의에 맞게 고친다(지우지 말고 고친다)
3. `format_report`의 FAQ 절이 새 커버(분모·커버·커버 안 됨), 다른 법령 인용만 있는 쌍 수, 다른 법령 인용 자리 법령 이름별 수, 번호로만 센 커버 참고 줄을 낸다. 「다른 법령 인용도 분모에서 빼지 않았다」 문구는 지운다
4. `runs/135/law-names.jsonl` — 인용 자리 한 줄에 `q_no`·자리 순번·조 라벨·법령 이름 라벨·법령 이름(다른 법령일 때)·근거 구절. 자리 수가 `extract_citations` 결과 전체와 같다
5. `uv run python -m cheongyak_rag.ingest.faq_cover_report`가 `docs/135-faq-cover.md`를 쓴다(API·DB를 부르지 않는다. `data/processed`의 법령 JSONL과 FAQ JSONL, `runs/135/law-names.jsonl`만 읽는다). 리포트에 실패 징후 1~4의 값·구간, 새 커버와 번호로만 센 커버 전후 표, 분류와 법령 이름 라벨이 다른 자리 전부(쌍 번호·조·분류·라벨·근거 구절), jw 표본 20자리가 있다
   - jw 표본: 다른 법령 인용 46자리(착수 때 커버 안 됨 40쌍의 것) 중 10 + 번호가 규칙에 있는 다른 법령 인용 중 5 + 이름 없음 중 5. 자리마다 답변 원문 문장 전체, 분류, 법령 이름 라벨을 적는다. 고르는 방법은 순서대로 고르게(간격 뽑기)로 하고 리포트에 적는다

## 실패 징후

용어: 규칙 인용·다른 법령 인용·커버·법령 이름 라벨·인용 자리는 `docs/concepts.md` `## 용어` 절 그대로 쓴다.

1. **jw 기준** — 법령 이름 라벨로 규칙 인용(`규칙` 또는 `이름 없음`)인데 현행 규칙에 없는 조를 인용한 쌍 수. 분류 기준 값도 나란히 적는다. 착수 때 값: 분류 기준 0/123(라벨은 아직 없음)
   - 통과: 라벨 기준 0
   - 다시 잰다: 라벨 기준 1~2. 그 쌍마다 답변 문장 전체, 조, 그 조가 예전 규칙 번호인지(법령 버전 목록 `law_versions`에서 읽기만 해서 확인할 수 있으면) 적는다. 코드는 더 고치지 않는다
   - 미완: 라벨 기준 3 이상
2. **분류와 법령 이름 라벨이 다른 인용 자리** — 415자리 중 규칙 인용 ↔ 다른 법령 인용이 갈린 자리 수(`모름`은 빼고 따로 적는다)
   - 정상: 0~4
   - 다시 잰다: 5~20. 전부 표로 적고, 그중 커버 판정을 바꾸는 자리(조가 현행 규칙에 없는 것)와 #131 정답 라벨을 바꾸는 자리를 따로 센다
   - 미완: 21 이상 — 분류를 이 셈에 못 쓴다
3. **#131 정답 라벨이 그대로인가** — 통과 기준 1의 `cmp`
   - 정상: 같다
   - 미완: 다르다. 옮기면서 동작이 바뀐 것이니 고친다(이 징후는 루프가 고쳐서 정상으로 만들 수 있는 것이다)
4. **새 커버 숫자** — 착수 때 main이 같은 분류로 집계한 값: 규칙 인용 있는 쌍 123 · 커버 123 · 다른 법령 인용만 있는 쌍 59
   - 정상: 세 값이 같다
   - 다시 잰다: 다르다. 어느 쌍이 왜 달라졌는지 적는다(예: `cited_articles`와 답변 정규식이 다르게 잡은 자리)

## 이번에 안 하는 것

- 다른 법령(주택법·도시정비법 등) 조문 수집 — jw가 「현행 규칙」을 규칙만으로 정했다. Notion #135 제목의 원래 범위다
- 분류 정규식 고치기 — 설계 4. 다른 자리는 목록으로만 남긴다
- `runs/golden.jsonl`·#131 이후 측정값 다시 내기
- `data/processed`·`data/raw`·`data/cache` 파일 쓰기. `python -m cheongyak_rag.ingest.law`(법제처 API를 부르고 `data/processed` 법령 JSONL을 다시 쓴다)는 돌리지 않는다
- 판정·검색·웹·배포

## Tasks

1. **분류 함수 옮기기** — 설계 1. `tests/`에 golden 분류 테스트가 있으면 그대로 통과해야 한다. 통과 기준 1의 `cmp`를 돌려 결과를 커밋 메시지 본문에 적는다
2. **커버 셈 바꾸기** — 설계 2, 통과 기준 2·3. `law_report`는 `.law` 파서를 import하지 않는다는 기존 테스트(`test_report_module_does_not_use_the_parser`)를 지킨다. `citations` import는 괜찮다
3. **법령 이름 라벨** — 설계 3, 통과 기준 4. 입력 파일(자리 목록, 분류 결과 없이)을 스크립트로 만들고 하위 에이전트에게 나눠 준다(한 번에 40자리 안팎). 결과를 `runs/135/law-names.jsonl`로 합친다. 하위 에이전트 프롬프트 원문을 `runs/135/law-names-prompt.md`로 커밋한다. 입력 파일은 커밋하지 않는다(`.gitignore`)
4. **리포트** — 통과 기준 5. 셈하는 부분은 함수로 두고 테스트한다(라벨과 분류 비교, 표본 뽑기)
5. **문서** — `docs/concepts.md`에 「인용 법령 분류 3개」 표(`rule`·`other`·`none` · 뜻 · 정의한 곳 `src/cheongyak_rag/ingest/citations.py` · 만든 티켓 #131, 옮긴 티켓 #135)를 더한다. `## 용어` 표는 main이 넣은 행을 쓰고 루프는 행을 더하지 않는다

## 환경

- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값(`LAW_OC`·`DATA_GO_KR_KEY`·OpenAI 키·`NEON_DIRECT_URL`·`TRACE_HASH_KEY`)은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- `data/` 아래 파일은 읽기만 한다
- 실제 DB는 쓰지 않는다. 어느 테이블에도 쓰지 않는다(`chunks`·`notices`·`notice_models` 포함). 이 티켓은 DB를 읽을 일도 없다
- OpenAI·법제처 API를 부르지 않는다. 테스트는 네트워크·실제 DB를 쓰지 않는다
- 워크트리에서 `docker compose up` 하지 않는다. Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. Pre-PR 서버 기동에 필요하면 `docker start cheongyak-db`
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8083을 쓰고 끝나면 끈다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8083 &) ; sleep 8 ; curl -sf http://127.0.0.1:8083/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8083'`
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · 통과 기준 1의 `cmp`(exit 0) · `uv run python -m cheongyak_rag.ingest.faq_cover_report`(exit 0)
>    - If no runner: state `no tests — skipped`, do not silently pass.
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## Done criteria

- 통과 기준 1~5가 전부 참이고, 실패 징후 1~4의 측정값과 구간이 `docs/135-faq-cover.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `runs/135/law-names.jsonl`·`runs/135/law-names-prompt.md`·`docs/135-faq-cover.md`를 커밋한다. 하위 에이전트 입력 파일과 실행 로그는 커밋하지 않는다(필요하면 `.gitignore`에 넣는다)
- `runs/golden.jsonl`은 바뀌지 않는다
- `docs/concepts.md`에 「인용 법령 분류 3개」 표를 더했다(Task 5)
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push origin feat/135-faq-cover`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#135] fix: FAQ 인용 커버를 조 번호가 아니라 법령 이름으로 센다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문(되물은 뒤 줄 포함) + 그 기준으로 잰 결과(실패 징후 1 라벨 기준 값·분류 기준 값·구간, 실패 징후 2~4 값과 구간). 그 아래 Summary / Changes / Notes. Notes에 「법령 이름 라벨은 같은 모델이 읽은 것이라 완전히 독립된 확인이 아니다」를 적는다
- PR을 만든 뒤 Notion #135 페이지의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3f841e61-65c0-81af-a9c3-eddbb2de0c0a -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
