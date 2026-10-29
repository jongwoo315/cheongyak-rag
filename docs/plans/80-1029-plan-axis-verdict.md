# #80 축별 판정과 guardrail — 구현 계획

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

**Tier:** C · **Notion:** #80 · **설계:** `docs/plans/80-1029-design-axis-verdict.md` (먼저 읽을 것 — 판정 흐름, 판정값 5개, 설계 결정 표, 프로필에 없는 칸, 측정 표본, 이번에 안 하는 것이 거기 있다)

## jw 기준

7축에서 필요한 것만 골라 검색을 하고 5가지 판정값 중 하나로 결과를 보여준다, 그리고 판정의 근거가 있는지도 확인하다

## 통과 기준

1. `generate/verdict.py`의 `judge(...)`가 공고 하나와 프로필 하나로 켜진 축의 하위 질의마다 `Verdict` 하나를 돌려준다. 꺼진 축은 LLM을 부르지 않고 「꺼짐 — 이유」로 남는다
2. `Verdict.verdict`는 `ELIGIBLE`·`INELIGIBLE`·`CONDITIONAL`·`NEED_INFO`·`UNVERIFIABLE` 중 하나다. JSON schema `strict: true`로 강제한다
3. guardrail 넷이 설계 흐름대로 동작한다. 각각 가짜 클라이언트 테스트가 있다
   - 근거 0개 → LLM 호출 없이 `UNVERIFIABLE`
   - 문맥에 없는 라벨 인용 → `invalid_citations`로 옮긴다
   - 문맥에는 있지만 `chunks`에서 다시 조회해 없는 라벨 → `invalid_citations`로 옮긴다(테스트 DB에서 행을 빼서 재현)
   - `UNVERIFIABLE`이 아닌데 남은 인용 0개 → `UNVERIFIABLE`로 바꾸고 `forced=True`
4. CLI `python -m cheongyak_rag.generate.verdict <house_manage_no> --profile <json>`이 축 7개(켜짐/꺼짐 · 이유)와 하위 질의마다 판정값 · 이유(또는 조건·필요한 정보) · 인용(라벨과 제목) · 기각된 인용을 출력한다
5. `--report`가 설계 §측정 표본(공고 6건 × 프로필 3종)을 돌려 실패 징후 1~6을 재고 `docs/80-axis-verdict.md`·`runs/80/last_run.json`을 쓴다. 징후 1이 미완이면 exit 1
6. 리포트 §표본: 공고 6건 × 프로필 3종 전부를 싣는다 — 하위 질의마다 판정값 · 이유 · 인용 라벨 · 기각된 인용
7. `uv run pytest -q` 전체 통과 · `uv run ruff check` · `uv run ruff format --check`

## 실패 징후

baseline 없음 — 이번이 첫 측정이다. 각 값은 #81·#143의 기준선이 된다.

### 1. jw 기준 — 켜진 축만 판정하고, 판정값이 5개 중 하나이고, 남은 인용이 실제로 있다

- 잴 것: 공고 6건 × 프로필 3종 전부에 대해
  - 켜진 하위 질의 중 판정이 없거나(API 오류·파싱 실패) 5값 밖인 수
  - 꺼진 축에 LLM을 부른 수
  - `UNVERIFIABLE`이 아닌 판정 중 guardrail을 거친 뒤 남은 인용이 0개인 수
  - 남은 인용을 측정 코드가 `chunks`에서 따로 다시 조회해 없는 라벨 수(측정 코드는 `verdict.py`의 대조 함수를 부르지 않고 SQL을 직접 쓴다)
- 통과: 판정 없음·5값 밖 0 · 꺼진 축 호출 0 · 인용 0개인 판정 0 · 없는 라벨 0
- 다시 잰다: 나머지가 0이고 판정 없음이 1~2개이며 전부 일시 오류(429·타임아웃). 그 하위 질의만 다시 부르고 원인을 리포트에 적는다
- 미완: 5값 밖 1개 이상, 꺼진 축 호출 1개 이상, 인용 0개인 판정 1개 이상, 없는 라벨 1개 이상, 판정 없음 3개 이상 중 하나라도

### 2. 빈 프로필로 사실을 지어내는가

- 잴 것: `empty.json` 프로필의 판정 중 `ELIGIBLE`·`INELIGIBLE`인 수. 프로필이 비었는데 충족·미충족을 정했으면 근거 없이 판정한 것이다
- 통과: 0
- 다시 잰다: 1~2개. 사례를 읽고 공고 값만으로 정해지는 요건인지(예: 규제 지역이 아니라 해당 없음) 리포트에 적는다. 공고 값만으로 정해지면 통과로 본다
- 미완: 3개 이상

### 3. 프로필에 칸이 없는 축에서 사실을 지어내는가

- 잴 것: `full.json` 프로필에서 `residence`·`income_asset`·`rewin`·`special_type` 축의 판정 중 `ELIGIBLE`·`INELIGIBLE`인 수. #77 프로필에는 이 축의 칸이 없다(설계 §프로필에 없는 칸)
- 통과: 0
- 다시 잰다: 1~2개. 사례와 이유 문장을 리포트에 싣는다
- 미완: 3개 이상

### 4. 판정을 내리긴 하는가

- 잴 것: `full.json` 프로필에서 `homeless`·`account` 축(공고 6건 × 2축 = 12개)의 판정 중 `ELIGIBLE`·`INELIGIBLE`·`CONDITIONAL`인 비율. 이 두 축은 #77 프로필로 정할 수 있다
- 통과: 10/12 이상
- 다시 잰다: 6~9/12. `NEED_INFO`·`UNVERIFIABLE`이 나온 사례의 이유 문장을 읽고 system 프롬프트를 한 번 고쳐 다시 잰다. 고친 내용을 리포트에 적는다
- 미완: 5/12 이하

### 5. guardrail이 판정을 얼마나 바꿨나

- 잴 것: 전체 판정 중 근거 0개로 `UNVERIFIABLE`이 된 수, 인용이 기각돼 `UNVERIFIABLE`로 바뀐(`forced`) 수, 기각된 인용 라벨 수
- 통과: `forced` 비율 20% 이하
- 다시 잰다: 20% 초과 50% 이하. 기각된 라벨을 모아 원인(문맥에 없는 조를 인용, 라벨 꼴이 다름)을 리포트에 적고 프롬프트를 고쳐 다시 잰다
- 미완: 50% 초과

### 6. 호출 수와 비용

- 잴 것: 첫 실행의 LLM 호출 수·입력·출력 토큰·비용($), 같은 명령을 한 번 더 돌렸을 때 호출 수, 공고 하나 × 프로필 하나를 처리하는 시간
- 통과: 첫 실행 $3 이하 · 두 번째 실행 호출 0
- 다시 잰다: 두 번째 실행 호출 1~3. 캐시 키가 흔들리는 칸(시각·순서)을 찾아 고친다
- 미완: 첫 실행 $3 초과(비용 상한에서 멈춘다) 또는 두 번째 실행 호출 4 이상 <!-- style-exempt -->
- 처리 시간은 값만 적는다(baseline 없음)

## 이번에 안 하는 것

설계 §이번에 안 하는 것 그대로 — 전역 집계(#81), `NEED_INFO` 질문 페이로드와 순서(#82), 정답 대조(#75·#76), 인용이 판정을 뒷받침하는지 자동 판단, 프롬프트 캐시 적중률, 모델 비교(#143), trace 저장(#83), 프로필 칸 추가.

## Tasks

### Task 1 — `Verdict`와 schema, 프롬프트

- `generate/verdict.py`: `VERDICTS` 5값, `SCHEMA`(`verdict` enum · `reason` · `conditions[]` · `need_info[]` · `citations[]`, `additionalProperties: false`), `Verdict` dataclass(축 id·하위 질의·판정·이유·조건·필요한 정보·인용·기각된 인용·`forced`·`no_context`·토큰·비용·지연·`cached`·`error`)
- system 프롬프트: 판정값 5개의 뜻, `CONDITIONAL`과 `NEED_INFO`를 가르는 규칙(설계 §열린 질문 2), 인용은 문맥 라벨 그대로, `UNVERIFIABLE`이 아닌 판정은 인용 1개 이상, 프로필에 없는 정보는 지어내지 말고 `NEED_INFO`, 축 7개의 요건 정의(축마다 2~3문장 — `axes.AXES`의 이름·기대 조를 보고 쓴다)
- user 메시지: 축 이름·하위 질의 → 공고 값 → 프로필 원본과 `profile.score` 결과 → 문맥 `[라벨] 본문`. 순서를 고정한다
- 테스트: schema가 enum 5값을 가진다. 같은 입력이면 user 메시지가 바이트까지 같다

### Task 2 — 판정 호출 `judge_one()`과 guardrail

- `judge_one(axis, query_hits, notice, profile_payload, client, model, cache, engine)` → `Verdict`
- 근거 0개면 호출하지 않고 `UNVERIFIABLE`, `no_context=True`
- 캐시 `data/cache/verdict-<model>.jsonl` — `answer.GenCache`를 그대로 쓴다. 비용은 `answer.cost_usd`, 오류 분류는 `answer.HardApiError`·`generate.evaluate.RetryingClient`
- 인용 대조는 설계 표대로 두 단계(문맥 라벨 → `chunks` 재조회). `UNVERIFIABLE`이 아닌데 남은 인용 0개면 `UNVERIFIABLE`, `forced=True`
- 테스트(가짜 클라이언트, OpenAI 안 부름): guardrail 넷 각각, 캐시 두 번째 호출 0회, `HardApiError`는 위로 올라간다

### Task 3 — 공고 하나 `judge()`

- `judge(engine, embedder, client, model, house_manage_no, profile, pblanc_no=None, cache=None)` → (공고 정보, `AxisPlan` 목록, `Verdict` 목록)
- 공고일(`notices.rcrit_pblanc_de`)을 읽어 `profile.score(profile, 공고일)`을 부른다. `ProfileError`는 그대로 올린다(CLI가 exit 2)
- `axes.plan`·`axes.search`를 그대로 쓴다. 꺼진 축은 `search`에 넘기지 않는다
- 테스트: 꺼진 축에 대해 클라이언트 호출 0. `special_type`은 유형 수만큼 판정이 나온다

### Task 4 — CLI

- `python -m cheongyak_rag.generate.verdict <house_manage_no> --profile <json> [--pblanc-no N] [--model M]`
- 출력: 공고명·MST·공고일, 축 7개(켜짐/꺼짐 · 이유), 켜진 하위 질의마다 판정값 · 이유/조건/필요한 정보 · 인용(라벨과 조문 제목) · 기각된 인용 · `forced` 표시
- 테스트: 출력에 축 7개 이름과 켜진 하위 질의의 판정 줄이 있다

### Task 5 — `--report`

- `generate/verdict_report.py` (#79 `axes_report.py` 방식): 설계 §측정 표본으로 실패 징후 1~6 측정, `docs/80-axis-verdict.md`·`runs/80/last_run.json`
- 프로필 3종을 `runs/80/profiles/{full,partial,empty}.json`으로 만들어 커밋한다(설계 §측정 표본의 조건대로)
- 리포트 첫 줄: 징후 1 값을 한 문장으로(「공고 6건 × 프로필 3종, 켜진 하위 질의 N개 전부에 5값 중 하나가 나왔고, 꺼진 축 호출 0, 인용 없는 판정 0, DB에 없는 인용 0이다」 꼴)
- 리포트 절: 1. 징후 1~6 표(측정값·구간) · 2. 판정값 분포 표(프로필 × 축, 칸마다 5값 개수) · 3. 표본(공고 6건 × 프로필 3종 전부) · 4. guardrail이 바꾼 것(기각된 라벨과 원래 판정) · 5. 열린 질문에서 고른 것(설계 §열린 질문 1·2의 결과, 프롬프트를 고쳤으면 무엇을)
- 비용 상한 $3: 누적 비용이 넘으면 멈추고 리포트에 「비용 상한에서 멈춤」을 적고 exit 1 <!-- style-exempt -->
- 징후 1이 미완이면 리포트를 쓴 뒤 exit 1
- 테스트: 가짜 클라이언트와 테스트 DB로 md·json에 징후 6개가 다 있고, 꺼진 축 호출이 1개면 exit 1

### Task 6 — 실제 DB와 실제 API로 측정

- `uv run python -m cheongyak_rag.generate.verdict_report --report`를 실제 DB(5433)에 돌려 리포트를 커밋한다. 다시 잰다·미완 구간이면 각 징후에 적힌 대로 고쳐 다시 잰다
- 같은 명령을 한 번 더 돌려 징후 6의 두 번째 실행 호출 수를 잰다
- 실제 DB는 alembic `0004`다. 이 티켓은 마이그레이션을 만들지 않는다

### Task 7 — Pre-PR 그리고 PR

아래 Pre-PR checks와 Done criteria.

## Pre-PR checks

> Pre-PR checks (all required — do not assume pass, show output):
> 1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
> 2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
>    - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8171 &) ; sleep 8; curl -sf http://127.0.0.1:8171/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8171'`. 그리고 CLI smoke: 공고 하나와 `runs/80/profiles/full.json`으로 `uv run python -m cheongyak_rag.generate.verdict <house_manage_no> --profile runs/80/profiles/full.json` exit 0
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
- `.env`·`data`·`.venv`는 메인 repo로 가는 심볼릭 링크다. `.env` 값은 출력·커밋하지 않는다. `data/cache`의 임베딩 캐시·`gen-` 캐시 파일을 지우거나 다시 쓰지 않는다. 판정 캐시 `verdict-<model>.jsonl`은 새로 만들고 append만 한다
- 테스트는 `tests/conftest.py`의 `pg_test_url`·`pg_engine` 방식을 따른다. 테스트에서 OpenAI를 부르지 않는다(가짜 클라이언트)
- 실제 DB의 `chunks`·`notices`·`notice_models`를 쓰거나 지우지 않는다. 이 티켓은 읽기만 한다
- OpenAI 키는 `.env`에 있다. 측정(Task 6)만 실제 API를 부른다

## Done criteria

- 통과 기준 1~7이 전부 참이고 실패 징후 1~6의 측정값이 리포트에 있다 (다시 잰다·미완 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 `git push -u origin feat/80-axis-verdict`로 push하고 PR을 만든다. base는 `main`. main을 작업 브랜치에 merge·rebase하지 않는다
- PR 제목: `[#80] feature: 켜진 축의 하위 질의마다 판정값 5개 중 하나를 내고 인용 조문이 실제로 있는지 대조한다`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 값).
  그 아래 Summary / Changes / 실패 징후 1~6 측정값 표 / 판정값 분포 / 열린 질문에서 고른 것 / CLI 출력 예 / Notes
- PR을 만든 뒤 Notion #80 페이지(`3aa41e61-65c0-81c9-95bc-fab45529bc96`)의 `PR` 프로퍼티에 PR URL을 넣는다.
  `"$HOME/.claude/tools/notion-api/notion-api" PATCH /v1/pages/3aa41e61-65c0-81c9-95bc-fab45529bc96 -`에 stdin으로
  `{"properties":{"PR":{"url":"<PR URL>"}}}`. `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
