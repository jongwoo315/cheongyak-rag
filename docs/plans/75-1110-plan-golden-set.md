# #75 골든셋 구축 — 구현 계획

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

**Tier:** C · **Notion:** #75 · **설계:** `docs/plans/75-1110-design-golden-set.md` (먼저 읽을 것 — 라벨을 무엇의 참값으로 보는지(§3.1), 라벨이 맞았는지 재는 세 가지(§3.7)가 거기 있다)

**흐름:** 끝까지 도는 흐름은 이미 있다(#71~#85). 이 티켓은 흐름을 고치지 않고, 흐름 밖에 정답 파일을 만든다. 그 파일을 흐름에 대 보는 것은 #76이다.
판정·검색·API·웹 코드를 고치지 않는다.

## jw 기준

골든셋 구축이 이루어진다, 요건별 정답 라벨이 제대로 붙고 정답 근거 조문이 정확히 파악된다

## 통과 기준

1. `runs/75/golden.jsonl`에 문항 50줄이 있고, 공고는 서로 다른 20건이다. 프로필 종류는 꽉 찬 20 · 일부 22 · 빈 8이다
2. 문항마다 그 공고에서 켜지는 하위 질의(`axes.plan` 결과, 특별공급 유형별 축은 유형마다 하나) 전부에 정답 라벨이 하나씩 있다. 라벨 없는 하위 질의 0, 켜지지 않은 축의 라벨 0
3. 정답 라벨 하나의 칸: `axis` · `query`(`axes.plan`의 하위 질의 문장 그대로) · `verdict`(판정값 5개 중 하나) · `reason`(한 문장) · `fields`(판정에 쓴 프로필 칸) ·
   `need`(`NEED_INFO`일 때 없는 정보, 아니면 빈 배열) · `citations`(정답 근거 조문 라벨, 1개 이상) · `article_quotes`(라벨마다 그 조문에서 옮긴 구절) ·
   `notice_evidence`(공고문 근거 `{page, quote}` 목록, 공고문에 기대지 않으면 빈 배열) · `rule`(따른 라벨 규칙 번호, 규칙으로 안 정해졌으면 null) · `rule_note`(null일 때 이유)
4. 문항 한 줄의 칸: `id`(`g01`~`g50`) · `house_manage_no` · `pblanc_no` · `notice_name` · `as_of`(모집공고일) · `profile_kind`(`full`·`partial`·`empty`) · `profile`(#77 `Profile` 15칸, 빈 칸은 null) · `labels`
5. `profile`은 `cheongyak_rag.profile`로 읽혀 오류가 없다. 꽉 찬 프로필은 15칸 전부 값이 있고, 빈 프로필은 전부 null이다
6. `docs/75-label-rules.md`가 축 7개와 특별공급 유형 8개마다 볼 프로필 칸 · 공고문 사실 · 판정값 조건 · 정답 근거 조문을 적는다. 규칙마다 번호(`homeless-1` 꼴)가 있다
7. `runs/75/notices.json`에 고른 공고 20건, 고른 기준, 공고마다 공고문 사실(쪽수·구절), DB 규제 표시와 공고문이 어긋난 칸이 있다. 같은 명령을 다시 돌리면 같은 20건이 나온다
8. `uv run python -m cheongyak_rag.golden.check`가 통과 기준 1~5와 글자 대조(실패 징후 2)를 검사하고, 어긋난 것을 줄마다 출력하고, 하나라도 있으면 exit 1이다
9. `uv run python -m cheongyak_rag.golden.report`가 `docs/75-golden.md`를 쓴다. 첫 줄은 결론 한 문장. 그 아래 공고 20건 표, 프로필 종류별 문항 수, 축별·판정값별 라벨 수,
   글자 대조 결과, 따로 붙인 라벨 일치율과 어긋난 것마다의 처리, 공고문·DB 어긋남, 규칙으로 안 정해진 라벨 목록
10. `runs/75/review-sample.md`에 jw 표본 검토용 정답 라벨 20개 — 판정값 5개에서 고르게(있는 만큼), `INELIGIBLE` 5개 이상, 시드 고정 무작위. 항목마다 문항 id · 공고명 · 프로필 · 하위 질의 ·
    정답 라벨 · 이유 · 정답 근거 조문 구절 · 공고문 근거 구절과 쪽수, 그리고 jw가 적을 빈 칸(맞음/틀림, 메모)
11. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 정답 라벨이 제대로 붙었나 (따로 붙인 라벨과의 일치).** 측정값은 두 개다. 둘 다 고치기 전, 처음 맞춰 본 값이다
   - 판정값 불일치 비율 = 따로 붙인 라벨과 판정값이 다른 정답 라벨 수 / 전체 정답 라벨 수
   - 정답 근거 조문 불일치 비율 = 따로 붙인 라벨과 조 라벨이 하나도 겹치지 않는 정답 라벨 수 / 전체 정답 라벨 수
   - 둘 다 5% 이하 → 통과. 어긋난 라벨마다 원문을 다시 읽고 어느 쪽이 맞는지와 이유를 리포트에 적고, 첫 라벨이 틀렸으면 고친다
   - 하나라도 5% 초과 15% 이하 → 다시 잰다. 위 처리를 한 뒤, 어긋난 라벨이 몰린 축의 라벨 규칙을 고치고, 그 축의 라벨을 새 하위 에이전트로 다시 따로 붙여 두 번째 비율을 잰다. 처음 값과 두 번째 값을 다 적는다
   - 하나라도 15% 초과 → 미완. 라벨 규칙 문서를 다시 쓰고, 첫 라벨을 다시 붙이고, 따로 붙인 라벨을 처음부터 다시 만든다. 세 번째로 재지는 않는다 — 두 번째 값이 어느 구간이든 적고 끝낸다
   - 한계를 리포트에 적는다: 두 쪽 다 Claude라 같은 잘못을 같이 할 수 있어 일치율이 높아도 맞았다는 증거는 아니다. 사람의 확인은 게이트의 jw 표본 검토(통과 기준 10)다
2. **jw 기준 — 정답 근거 조문이 정확히 파악됐나 (글자 대조).** 측정값은 어긋난 구절 수다
   - 정답 근거 조문 구절: MST 286965 `chunks`의 그 조문 본문에 공백만 합쳐 비교해서 없는 구절
   - 공고문 근거 구절: 그 PDF 그 쪽의 pymupdf 글자에 공백만 합쳐 비교해서 없는 구절
   - 존재하지 않는 조 라벨(MST 286965 `chunks`에 없는 `제N조`)도 어긋난 것으로 센다
   - 0 → 통과
   - 1~10 → 구절을 원문에서 다시 옮겨 고치고 다시 대조한다. 처음 값과 고친 뒤 값을 다 적는다
   - 11 이상 → 옮기는 방식(쪽 글자 뽑기, 공백 처리)을 먼저 의심하고 고친 뒤 전부 다시 대조한다. 처음 값과 고친 뒤 값을 다 적는다
3. **`INELIGIBLE` 정답 라벨이 모자라다.** 치명오답률의 분모다. 30개 이상이고 4개 이상의 축에 걸쳐 있으면 통과. 아니면 프로필을 다시 짜(문항 수·프로필 종류 수는 그대로) 채운다. 그래도 안 되면 값을 적고 끝낸다
4. **규칙으로 안 정해진 라벨(`rule`이 null)이 많다.** 전체의 10% 이하 → 통과. 넘으면 라벨 규칙에 그 경우를 더하고 다시 붙인다. 다시 붙인 뒤 값을 적는다
5. **공고문·DB 규제 표시 어긋남.** 판정 대상이 아니다. 공고 수와 칸만 리포트에 적는다(baseline 없음 — 첫 측정)
6. **판정값 분포.** 판정값 5개 각각의 라벨 수를 적는다. `CONDITIONAL`·`UNVERIFIABLE`이 0이면 0이라고 적는다. 억지로 만들지 않는다

## 범위 밖

- 판정 흐름을 골든셋에 돌려 정확도·치명오답률 측정 — #76
- 공고문 PDF 청킹·색인, `chunks` 적재 — L3 청킹 티켓
- LH 10건(공고문 없음), FAQ 정답 근거, 가점 정답값
- 프로필에 없는 사실(거주 지역·소득 등)을 문항에 넣기 — 설계 §5 열린 질문 2, 기본값은 넣지 않는다
- 켜지는 축 조건·판정 프롬프트·guard 고치기. 공고문·DB 어긋남은 적기만 한다
- DB 테이블·마이그레이션, Vercel·Neon 배포

## Task

1. **PDF 쪽 글자와 대조 함수** — `src/cheongyak_rag/golden/__init__.py`, `src/cheongyak_rag/golden/text.py`: `pdf_pages(path) -> list[str]`(pymupdf, 쪽마다 글자),
   `norm(s) -> str`(공백 묶음을 한 칸으로), `quote_in(quote, text) -> bool`, `article_text(engine, mst, label) -> str | None`(`chunks`에서 그 조 본문). 테스트 먼저(작은 PDF는 테스트 안에서 pymupdf로 만든다)
2. **공고 고르기** — `src/cheongyak_rag/golden/select.py`: 설계 §3.5 기준을 순수 함수 `select(candidates, fixed) -> list`로 쓰고 테스트한다(같은 입력이면 같은 결과, 고정 5건 포함, 축 조합·유형 8개·지역 조건). <!-- style-exempt -->
   CLI `python -m cheongyak_rag.golden.select`가 DB(SELECT만)와 `data/raw/notices/manifest.jsonl`을 읽어 `runs/75/notices.json`에 20건과 기준을 쓴다
3. **공고문 사실 뽑기** — 고른 20건의 PDF 글자를 읽고(`pdf_pages`), 공고마다 라벨에 쓸 사실을 쪽수·구절과 함께 `runs/75/notices.json`에 더한다:
   규제 지역 표시(투기과열지구·청약과열지역·분양가상한제·공공택지), 거주 요건(지역·기간·우선공급), 청약통장 1순위 가입 기간·예치금, 세대주 요건, 재당첨 제한, 공급하는 특별공급 유형과 유형별 자격 문장. <!-- style-exempt -->
   DB 규제 표시와 다르면 어긋난 칸에 적는다. 이 Task는 사람처럼 읽는 일이라 코드 대신 루프가 직접 읽고 쓴다. 쓴 뒤 `check`로 구절 대조를 돌린다
4. **라벨 규칙** — `docs/75-label-rules.md`. 규칙 조문은 `chunks`(MST 286965)에서 읽는다. 설계 §3.1의 원칙(프로필 15칸 + 공고문 + 규칙의 참값, 갈래가 여럿이면 `NEED_INFO`)을 첫 절에 적고,
   축마다 규칙을 번호와 함께 쓴다. 청약통장 축은 1순위 자격을 본다는 것처럼 축의 뜻을 정하는 약속도 여기 적는다
5. **프로필 짜기와 첫 라벨** — 설계 §3.6대로 문항 50개의 프로필을 짜고, 문항마다 켜진 하위 질의 목록을 `axes.plan`(DB SELECT만)으로 받아, 라벨 규칙대로 정답 라벨을 붙여 `runs/75/golden.jsonl`에 쓴다.
   `src/cheongyak_rag/golden/check.py`(통과 기준 1~5 + 글자 대조 + 실패 징후 3·4 값)를 먼저 테스트와 함께 만들고, 다 쓴 뒤 돌려 0이 될 때까지 고친다. 실패 징후 2·3·4 구간대로 처리한다
6. **따로 붙인 라벨** — Agent 도구로 하위 에이전트를 띄운다(문항 10개씩 5번). 하위 에이전트에게 주는 것: `docs/75-label-rules.md` 경로, 문항의 공고문 PDF 경로·`runs/75/notices.json`의 그 공고 사실, 프로필, 하위 질의 목록, `runs/75/golden.jsonl`과 같은 칸 형식.
   주지 않는 것: `runs/75/golden.jsonl`, 첫 라벨의 어떤 값도. 프롬프트에 「`runs/75/golden.jsonl`을 열지 말 것」을 적는다. 결과를 `runs/75/second.jsonl`에 쓰고,
   `check.py`에 일치율 계산(실패 징후 1의 두 비율, 축마다 나눈 값)을 더해 잰다. 실패 징후 1 구간대로 처리하고, 어긋난 라벨마다 처리(어느 쪽이 맞나·이유·고쳤나)를 `runs/75/disagreements.jsonl`에 쓴다
7. **표본·리포트·문서** — `runs/75/review-sample.md`(통과 기준 10), `src/cheongyak_rag/golden/report.py` → `docs/75-golden.md`(통과 기준 9). `docs/concepts.md`에 개념 표 「프로필 종류 3개」(`full`·`partial`·`empty`, 뜻, 정의한 파일 —
   `runs/75/golden.jsonl`과 `runs/80/profiles/`, 만든 티켓 #80·#75)를 더한다. README에 골든셋 한 줄과 `check`·`report` 실행 명령을 더한다

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
>    - 이 repo 파이썬 쪽은 `pydantic_settings`다. `config.py`에 새 칸을 더했으면 적고 `.env.example`과 대조한다. 더하지 않았으면 「새 환경 변수 없음」
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill.
>    - 이 repo: `(timeout 60 uv run uvicorn cheongyak_rag.main:app --port 8175 &) ; sleep 8 ; curl -sf http://127.0.0.1:8175/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8175'`
>    - 웹(`web/`)은 고치지 않으므로 `npm run build`는 돌리지 않는다. 고쳤다면 돌린다
> 3. Full test suite green (show pass/fail).
>    - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check` · `uv run python -m cheongyak_rag.golden.check`(exit 0)
>
> Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다.
>
> 내장 `/code-review`를 여기 쓰지 말 것 — 헤드리스 세션에는 없다.

## 환경

- Postgres는 메인 repo의 `cheongyak-db` 컨테이너(포트 5433)다. 워크트리에서 `docker compose up` 하지 않는다. 컨테이너가 꺼져 있으면 `docker start cheongyak-db`
- `.env`·`.venv`·`data/raw`·`data/cache`·`data/processed`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `.env`를 고치지 않는다
- 공고문 PDF는 `data/raw/notices/`에 있다(읽기만). `data/raw/`와 `data/cache`의 파일을 지우거나 다시 쓰지 않는다. PDF 글자를 파일로 남기려면 `data/processed/notices-text/`에 새로 쓴다(gitignore 대상)
- 실제 DB는 읽기만 한다. `notices`·`notice_models`·`chunks`·`law_versions`·`notice_law_versions`·`traces`·`verdict_daily_count`에 쓰지 않는다. 마이그레이션을 더하지 않는다
- 테스트는 네트워크·실제 DB를 쓰지 않는다. DB가 필요한 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다
- **OpenAI를 부르지 않는다.** 판정 흐름(`cheongyak_rag.generate.verdict`·API의 판정 엔드포인트)을 돌리지 않는다
- **라벨을 붙이는 동안(Task 3~6) 시스템 판정 출력을 읽지 않는다** — `data/cache/verdict-*.jsonl`, `runs/80/`~`runs/85/`의 판정·답 파일, `docs/80-axis-verdict.md`·`docs/81-answer.md`·`docs/84-web.md`·`docs/85-deploy.md`. 시스템 답을 정답으로 옮겨 적게 된다.
  공고 번호 목록(`runs/80/last_run.json`의 `notices`)과 `runs/80/profiles/`는 읽어도 된다
- 다른 세션이 8000 포트를 쓸 수 있다. Pre-PR은 8175를 쓰고 끝나면 끈다

## Done criteria

- 통과 기준 1~11이 전부 참이고, 실패 징후 1~6의 측정값과 구간이 `docs/75-golden.md`에 있다. 결과가 통과 구간이 아니어도 그 구간의 처리를 했으면 끝낸다
- `docs/concepts.md`에 개념 표 「프로필 종류 3개」를 더했다. `## 용어` 표에는 main 세션이 이미 넣은 행을 쓴다. 루프는 용어 행을 더하지 않는다
- plan·리포트·PR 본문은 `docs/concepts.md` `## 용어` 절의 말을 쓴다. 그 절의 「쓰지 말 말」을 쓰지 않는다. 새 이름이 필요하면 짓지 않고 풀어 쓴다
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지). 커밋 단위는 Task 하나
- `gh` 계정은 `jongwoo315`. `git push -u origin feat/75-golden-set`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#75] feature: 골든셋 — 공고 20건 50문항, 하위 질의별 정답 라벨과 정답 근거 조문`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(문항·공고·라벨 수, 실패 징후 1의 두 비율과 구간, 실패 징후 2의 어긋난 구절 수와 구간) + 「jw 표본 검토: `runs/75/review-sample.md`, 게이트에서 jw가 본다」. 그 아래 Summary / Changes / Notes
- PR을 만든 뒤 Notion #75 페이지(`3aa41e61-65c0-81b4-a75f-eac36c01f195`)의 `PR` 프로퍼티에 PR URL을 넣는다. `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81b4-a75f-eac36c01f195 -`에 stdin으로 `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
