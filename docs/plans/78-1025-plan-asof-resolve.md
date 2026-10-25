# #78 as-of 해소(B3) — 구현 계획

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

**Tier:** C · **Notion:** #78 · **설계:** `docs/plans/78-1025-design-asof-resolve.md` (먼저 읽을 것 — 착수 때 실측한 API 사실이 거기 있다)

## jw 기준

공고별로 유효한 법령 버전을 확인할 수 있다

## 통과 기준

1. `uv run alembic upgrade head`가 `law_versions` 테이블과 `notice_law_versions` view를 만든다(마이그레이션 `0003`).
   `alembic downgrade 0002` 뒤 다시 `upgrade head`가 된다
2. `uv run python -m cheongyak_rag.ingest.law_versions`가 법제처 `eflaw` 검색을 페이지 끝까지 읽어 「주택공급에 관한 규칙」
   시행일별 행을 `law_versions`에 upsert하고, 받은 행 수 · 페이지 수 · 넣은/고친 행 수 · 호출 수를 출력하고 exit 0
3. `notice_law_versions` view가 `notices` 한 행마다 한 행을 준다(행 수가 같다). 열: 공고 PK 두 개, `rcrit_pblanc_de`,
   고른 `mst`, `effective_date`, `promulgation_date`, `promulgation_no`. 고르는 규칙은 설계 §1 그대로다
4. `uv run python -m cheongyak_rag.asof`가 view를 읽고, view에 나온 서로 다른 (MST, 시행일)마다 법령 본문을 대조한 뒤
   `runs/78/last_run.json`과 `docs/78-asof.md`를 쓴다. 리포트 첫 줄은 결론 한 문장이다(버전이 정해진 공고 수 / 전체,
   고른 버전 수, 본문 대조 일치 수 / 대조 수). 본문 대조가 하나라도 어긋나면 exit 1
5. 규칙 테스트가 다섯 경우를 고정한다: 시행일 당일 · 시행일 전날 · 같은 MST의 단계 시행(두 시행일) ·
   같은 날 MST 둘(공포일이 늦은 쪽) · 가장 오래된 시행일보다 이른 날(NULL)
6. `LAW_OC` 값은 출력·예외·리포트·커밋 어디에도 나오지 않는다(테스트로 확인)
7. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 공고마다 버전을 확인할 수 있나.** 두 값을 같이 본다: 「버전이 안 정해진 공고 수」(view에서 `mst`가 NULL)와
   「본문 대조 불일치 수」(고른 버전의 본문을 `lawService.do?target=eflaw&MST=<mst>&efYd=<시행일>`로 받았을 때 `기본정보.시행일자`·
   `공포번호`가 `law_versions` 행과 다른 버전 수):
   - 두 값 모두 0 → 통과
   - 안 정해진 공고 1~3건이고 불일치 0 → 그 공고 목록과 모집공고일, 원인을 리포트에 적는다
   - 안 정해진 공고 4건 이상, 또는 불일치 1건 이상 → 미완. 규칙이나 목록 수집을 고치고 다시 잰다
   - 착수 실측(2026-10-25): 공고 84건의 모집공고일이 전부 2026-07-27 이후이고, 최신 시행일은 2026-06-15(MST 286965)다.
     **84건 전부 MST 286965로 정해지는 것이 정상이다.** 다른 MST가 하나라도 나오면 미완이다
2. **목록 완결성.** 법령명이 정확히 「주택공급에 관한 규칙」인 행 수:
   - 129행 → 통과 (착수 실측: 2페이지, MST 104개, 시행일 2005-03-09 ~ 2026-06-15)
   - 130행 이상 → 그 사이 개정이 나온 것이다. 늘어난 행 목록을 리포트에 적는다
   - 128행 이하 → 미완. 페이지 넘김을 고친다
   - 그리고 (MST, 시행일) 중복이 1건이라도 있으면 미완
3. **같은 날 여러 MST.** 그런 시행일 수와 각 날짜에 view 규칙이 고를 MST를 리포트에 적는다. 판정 구간 없음 — 기록만.
   착수 실측: 7일(2024-07-01 · 2024-03-25 · 2023-04-01 · 2017-01-01 · 2015-02-27 · 2014-06-30 · 2008-01-01)
4. **호출.** 수집 한 번 + asof 한 번의 API 호출 수: 5 이하 정상(목록 2 + 본문 대조 1) / 6~10 재시도 원인을 리포트에 /
   11 이상 페이지 넘김·재시도 결함
5. **재실행.** 수집 명령 두 번째 실행 뒤 `law_versions` 행 수와 PK 집합이 그대로이고 새로 들어간 행이 0이어야 한다.
   하나라도 다르면 미완
6. **키 노출.** 테스트에서 가짜 OC 문자열이 출력·예외·리포트에 0회 나타나야 한다. 1회라도 나오면 버그

## 이번에 안 하는 것

- 과거 버전 조문 파싱·적재 — #79·#80. 본문은 대조만 하고 raw JSON으로 둔다
- 부칙 경과조치 — 모집공고일만 쓴다. 리포트 「한계」 절에 한 줄로 적는다
- 다른 법령 버전 — #135
- 주기적 갱신

## Tasks

각 Task는 TDD(실패하는 테스트 → 구현 → 통과)로 하고 Task 하나를 커밋 하나로 한다.

### Task 1 — 마이그레이션 `0003`

- `alembic/versions/0003_law_versions.py` (down_revision `0002`)
  - `law_versions`: `law_id text`, `mst text`, `effective_date date`, `promulgation_date date`, `promulgation_no text`,
    `law_name text`, `revision_kind text`(제개정구분명), `status text`(현행연혁코드), `raw jsonb`, `fetched_at timestamptz`.
    PK `(law_id, mst, effective_date)`. 인덱스 `(law_id, effective_date)`
  - view `notice_law_versions`: `notices` LEFT JOIN LATERAL로 `law_id = '008243'` 행 중 `effective_date <= n.rcrit_pblanc_de`를
    `ORDER BY effective_date DESC, promulgation_date DESC, mst DESC LIMIT 1`. 공고에 맞는 행이 없으면 버전 열이 NULL
  - downgrade: view → 테이블 순으로 지운다
- 테스트: upgrade 뒤 테이블·view 존재, downgrade 0002 뒤 둘 다 없음, 다시 upgrade
- 마이그레이션은 손으로 쓴다(autogenerate를 쓰지 않는다 — #71 리뷰 #12)

### Task 2 — 규칙 테스트 (view)

- 테스트 DB에 `notices` 행 몇 개와 `law_versions` 행을 직접 넣고 view를 읽는다. 통과 기준 5의 다섯 경우를 각각 한 테스트로
- 픽스처는 착수 실측 값을 쓴다: MST 265605(시행 2024-10-01·2024-11-01, 공포 2024-09-30), 같은 날 2024-07-01의 261483(공포
  2024-03-25)·257091(공포 2023-12-20), 최오래 2005-03-09

### Task 3 — 버전 목록 수집 `cheongyak_rag/ingest/law_versions.py`

- `fetch_versions(oc, client)`: `lawSearch.do` `target=eflaw` `query=주택공급에관한규칙` `display=100` `page=1..`. 한 페이지가 100행보다
  적으면 멈춘다. `법령명한글 == "주택공급에 관한 규칙"`만 남긴다. 결과가 하나면 dict로 온다(`law.py:61` 참고)
- HTTP·OC 처리는 `cheongyak_rag/ingest/law.py`의 `_require_oc` · `_get_json` · `_snippet` · `LawApiError`를 그대로 쓴다(새로 만들지 않는다)
- `upsert`: `ON CONFLICT (law_id, mst, effective_date) DO UPDATE`, 넣은/고친 수를 돌려준다. #71 `notice.upsert`의 방식을 참고하되
  한 트랜잭션으로 한다
- `main()`: 출력 + `runs/78/law_versions.json`(받은 행 수 · 페이지 · 넣은/고친 · 호출 · 같은 날 여러 MST 목록)
- 테스트: `httpx.MockTransport`로 2페이지 응답, 이름 필터, dict 단건 응답, 재실행 inserted 0, 가짜 OC 미노출

### Task 4 — 공고별 버전 확인 `cheongyak_rag/asof.py`

- view를 읽어 공고별 행을 모은다. 서로 다른 (MST, 시행일)마다 `lawService.do?target=eflaw&MST=..&efYd=YYYYMMDD&type=JSON`을
  받아 `법령.기본정보.시행일자`·`공포번호`를 `law_versions`와 대조한다. raw는 `data/raw/law-008243-<YYYYMMDD>.json`에 둔다 —
  **파일이 이미 있으면 받지 않고 그 파일로 대조한다**(현행 `law-008243-20260615.json`이 이미 있다. 이 경우 호출 0)
- `runs/78/last_run.json`: 공고 수, 정해진 수, NULL 공고 목록, 버전별 공고 수, 대조 결과, 호출 수, 실행 시각
- `docs/78-asof.md`: 첫 줄 결론 한 문장 → 실패 징후 1~6 측정값 표 → 버전별 공고 수 표 → 같은 날 여러 MST 표 →
  공고 표본 5건(공고명 · 모집공고일 · MST · 시행일) → 「한계」(부칙 경과조치) → 「다시 돌리는 법」
- 테스트: MockTransport로 대조 일치·불일치(exit 1), 파일 있을 때 호출 0, 가짜 OC 미노출

### Task 5 — 실제 실행과 리포트

1. `cheongyak-db`는 메인 repo(`/Users/jw/prv/cheongyak-rag`)에서 떠 있다. 이 워크트리에서 `docker compose up`을 하지 않는다.
   꺼져 있으면 `docker compose -f /Users/jw/prv/cheongyak-rag/docker-compose.yml up -d`
2. `uv run alembic upgrade head`
3. `uv run python -m cheongyak_rag.ingest.law_versions` 두 번(두 번째가 재실행 측정)
4. `uv run python -m cheongyak_rag.asof`
5. 실패 징후가 실패 구간이면 고치고 다시 잰다. 리포트와 `runs/78/*.json`을 커밋한다

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.asof` exit 0
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
   - `uv run pytest -q` · `uv run ruff check` · `uv run ruff format --check`

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).

내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만 **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.

커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~6의 측정값이 리포트에 있다 (실패 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/78-asof-resolve`로 push하고 PR을 만든다. base는 `main`
- PR 제목: `[#78] feature: 공고 모집공고일로 유효한 주택공급규칙 버전을 정한다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 두 값과 버전별
  공고 수). 그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / CLI 출력 / Notes
- PR을 만든 뒤 Notion #78 페이지(`3aa41e61-65c0-818f-9781-ce0607c2b440`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-818f-9781-ce0607c2b440 -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
