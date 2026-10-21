# #139 답 생성 — 구현 계획

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

**Tier:** B · **Notion:** #139 · **설계:** `docs/plans/139-1022-design-answer-gen.md` (먼저 읽을 것)

## jw 기준

질문에 대한 답이 생성되고 내가 확인이 가능하다

## 통과 기준

1. `uv run python -m cheongyak_rag.generate.answer "질문"`이 답 · abstain 여부 · 인용한 조의 원문(조 번호·제목·본문 앞
   300자) · 인용한 FAQ(Q번호·질문) · 검색 상위 조 5개 · 입력/출력 토큰과 $를 출력하고 exit 0
2. `uv run python -m cheongyak_rag.generate.evaluate`가 golden 123문항 + 범위 밖 10문항을 돌려
   `runs/139/answers.jsonl`(질문 한 줄)과 `runs/139/config.json`을 쓴다
3. `uv run python -m cheongyak_rag.generate.report`가 `docs/139-answer.md`를 쓴다. 첫 줄은 결론 한 문장
   (생성 실패 수, golden abstain 비율, 범위 밖 abstain 수, 인용 정밀도, 총 $)
4. 두 번째 `evaluate` 실행에서 OpenAI 호출 0회, `answers.jsonl`이 바이트 단위로 같다
5. `runs/139/`와 `docs/139-answer.md`를 커밋한다. `data/`는 커밋하지 않는다
6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과

## 실패 징후

1. **jw 기준 — 답이 생성되고 확인할 수 있나.** 133문항 일괄 실행에서
   「생성 실패(예외·JSON 파싱 실패)」 + 「`abstain=false`인데 유효 인용이 0개라 코드가 abstain으로 바꾼 답」 건수:
   - 0건 → 통과
   - 1~3건 → 문항 목록과 원인을 리포트에 적는다
   - 4건 이상 → 미완. 프롬프트나 파싱을 고치고 다시 잰다
   - 그리고 리포트에 표본 10문항(seed 0)이 질문 · 생성 답 · 인용 원문 · FAQ 공식 답 · 정답 조를 나란히 보여야 한다.
     빠지면 미완 (jw가 확인할 자리가 이것이다)
2. **문맥 밖 인용.** 문맥(조 5 + FAQ 3)에 없는 라벨을 인용한 비율: ≤ 2% 정상 / 2~5% 목록을 리포트에 / > 5% 프롬프트 결함으로 보고 고친다
3. **golden 부당 `abstain`.** golden 123 중 최종 abstain 비율: ≤ 10% 정상 / 10~25% 검색 hit@5 여부로 갈라 원인을 리포트에 /
   > 25% 실패 — 프롬프트가 너무 보수적이다. 고치고 다시 잰다
4. **범위 밖 `abstain`.** 10문항 중 abstain 수: 9~10 정상 / 7~8 답한 문항과 답을 리포트에 / ≤ 6 실패 — 근거 없는 답을 낸다
5. **인용 정밀도** (답한 문항, 조 인용이 있는 것만, 정답 조 대비). baseline 없음 — 첫 측정, 후속 provider 비교의 기준선:
   ≥ 0.6 정상 / 0.3~0.6 틀린 인용 목록을 리포트에 / < 0.3 인용 결함 의심, 원인을 찾는다. 검색 hit@5 문항만으로 한 값도 같이 적는다
6. **비용** (`gpt-5.4-mini`, 입력 $0.75 · 출력 $4.50 / 1M 토큰):
   - 첫 일괄 실행 호출 수: ≤ 140 정상 (133 + 재시도) / 141~170 재시도 원인을 리포트에 / > 170 재시도 루프 결함
   - 총 $: ≤ $3 정상 / $3~6 질문당 토큰을 리포트에 / $6에 이르면 실행이 멈춘다(예산 상한, 코드로 강제) <!-- style-exempt -->
   - 질문당 입력 토큰 평균: ≤ 8,000 정상 / 8,000~15,000 긴 문맥 문항 목록 / > 15,000 문맥 구성 결함
   - 두 번째 실행 호출 0회. 1회라도 있으면 캐시 결함
7. **지연** (첫 실행, 캐시 안 탄 호출): p95 ≤ 15초 정상 / 15~30초 기록 / > 30초 원인을 리포트에
8. **누수.** 일괄 실행에서 golden 질문 자기 FAQ 쌍이 문맥에 들어간 문항 수: 0이어야 한다. 1개라도 있으면 버그

## 이번에 안 하는 것

설계 §이번에 안 하는 것을 그대로 따른다. 특히 provider 2종 비교, `POST /ask`, LLM judge 채점, 검색 파라미터 변경
(k=5, faq_k=3 고정), golden set 변경은 하지 않는다. `retrieval/` 파일의 동작은 바꾸지 않는다.

## 작업 환경

- `.venv`는 이 워크트리 자체 것이다(이미 `uv sync` 했다). 메인 repo의 `.venv`를 쓰지 않는다
- `.env`는 메인 repo 것의 심볼릭 링크다. `.env`의 `OPENAI_API_KEY`는 비어 있고 **셸 환경변수에 있다**
  (pydantic-settings는 환경변수가 우선한다). 비어 있으면 HARD 오류로 멈춘다
- `data`는 메인 repo `data/`의 **심볼릭 링크**다. 법령·FAQ jsonl과 임베딩 캐시가 거기 있다. 다시 받지 않는다.
  `data`를 지우거나 그 안을 비우지 말 것. `git add`에 넣지 말 것(`.git/info/exclude`에 `/data`가 있다).
  새 응답 캐시 `data/cache/gen-gpt-5.4-mini.jsonl`도 거기 생긴다
- Postgres(`cheongyak-db`, 포트 5433)는 메인 repo에서 떠 있다. 워크트리에서 `docker compose up`하지 않는다
- 새 의존성 넣지 않는다. `openai` 2.x가 이미 있다
- **base 브랜치(main)를 작업 브랜치에 merge·rebase하지 않는다**
- `git add -A`·`git add .` 대신 파일을 지정해 add한다

## Tasks

Task 하나 = 커밋 하나. 각 Task는 테스트 먼저(TDD). OpenAI 클라이언트는 테스트에서 가짜로 바꾼다
(`tests/fakes.py`에 `FakeChat` 추가 — `client.chat.completions.create(**kw)`를 흉내 내고 호출을 기록한다).

### Task 1 — 설정

- `config.py`에 `openai_gen_model: str = "gpt-5.4-mini"` 추가. `.env.example`에 `OPENAI_GEN_MODEL=gpt-5.4-mini` 추가
- 가격 상수는 `generate/answer.py`에 둔다: `PRICE_PER_1M = {"gpt-5.4-mini": (0.75, 4.50)}` + 출처 주석
  (`developers.openai.com/api/docs/models/gpt-5.4-mini`, 2026-10-22 확인). 표에 없는 모델이면 $ 계산에서 오류를 낸다 —
  0으로 대신하지 않는다

### Task 2 — 답 생성 (`generate/answer.py`)

- `build_messages(question, result) -> list[dict]` — `result`는 `query.Index.search`가 돌려준 `{"law": [...], "faq": [...]}`.
  system 프롬프트(한국어): 문맥에 있는 내용으로만 답한다 · 답 문장 안에 근거를 `[제34조]` `[Q47]` 꼴로 단다 ·
  `citations`에 쓴 라벨을 전부 넣는다 · 문맥으로 답할 수 없으면 `abstain=true`, `answer`에는 왜 답할 수 없는지 한 문장.
  user 메시지는 질문과 문맥(조는 `[제N조] 제N조(제목)\n본문`, FAQ는 `[Q47] 질문\n답변`)
- `generate(question, result, client, model, cache) -> Answer` — `chat.completions.create`에
  `response_format={"type":"json_schema","json_schema":{"name":"answer","strict":true,"schema":{...}}}`,
  schema는 `{abstain: boolean, answer: string, citations: array of string}`, `max_completion_tokens=1500`.
  **`temperature`를 넣지 않는다**(지원 안 하는 모델이 있다)
- 사후 점검: 문맥 라벨 집합에 없는 인용은 `invalid_citations`로 옮긴다. `abstain=false`인데 유효 인용이 0개면
  `abstain=true`로 바꾸고 `forced_abstain=true`를 남긴다. JSON 파싱 실패는 `error`에 남긴다(예외를 무시하지 말고 기록)
- `Answer` 필드: `question, abstain, forced_abstain, answer, citations, invalid_citations, context_labels,
  input_tokens, output_tokens, usd, latency_s, cached, error`
- 응답 캐시: `data/cache/gen-<model>.jsonl`, 키 `sha256(model + "\n" + system + "\n" + user)`, 값은 원 응답 content ·
  usage · latency. `retrieval/embed.py`의 캐시 읽기(깨진 줄 처리 포함)를 따른다. 캐시 적중이면 호출하지 않고 `cached=true`
- CLI `main(argv)`: `python -m cheongyak_rag.generate.answer "질문" [-k 5] [--faq-k 3]`. 통과 기준 1의 내용을 출력한다.
  `exclude_same_question`은 CLI에서 끄고(실사용) 일괄 실행에서만 켠다
- 테스트: 정상 답 · 문맥 밖 인용 분리 · 유효 인용 0개 → forced_abstain · JSON 깨짐 → error · 캐시 적중 시 호출 0 ·
  $ 계산 · CLI 출력에 인용 원문과 토큰이 들어감

### Task 3 — 일괄 실행 (`generate/evaluate.py`)

- 질문: `runs/golden.jsonl` 123문항 + `runs/139/ood.jsonl` 10문항. `ood.jsonl`은 이 Task에서 아래 10줄 그대로 만든다
  (`{"qid": "ood-1", "question": ...}`):
  1. 자동차 보험료를 줄이는 방법은?
  2. 연말정산 의료비 세액공제 한도는 얼마인가요?
  3. 여권을 잃어버렸을 때 재발급 절차는?
  4. 국민연금 조기수령 나이는?
  5. 반려견 등록은 어디서 하나요?
  6. 운전면허 적성검사 기간은?
  7. 실업급여 수급 조건은?
  8. 주택담보대출 LTV 한도는 얼마인가요?
  9. 재산세 납부 기한은 언제인가요?
  10. 전월세 신고제의 신고 기한은?
- `Index`는 한 번만 만들고 질문마다 `search(q, 5, faq_k=3, exclude_same_question=True)`
- 예산: 누적 $가 `--budget-usd`(기본 6)를 넘으면 그 자리에서 멈추고 exit 2, 그때까지의 결과와 멈춘 사실을 config에 적는다
- 429는 지수 대기 후 재시도(최대 5회), 재시도 수를 센다. 401/403/insufficient_quota는 즉시 멈춘다
- `runs/139/answers.jsonl` 한 줄 = `Answer` 필드 + `qid, set(golden|ood), gold, retrieval_hit(정답 조가 문맥에 있나),
  self_faq_in_context`. 정렬은 qid 순서 고정. `latency_s`·`cached`처럼 실행마다 달라지는 값은 `answers.jsonl`에 넣지 않고
  `config.json`의 요약으로 뺀다 — 통과 기준 4(두 번째 실행 바이트 동일) 때문이다. 지연은 캐시 값에 저장된 첫 호출 지연을 쓴다
- `runs/139/config.json`: 모델 · k · faq_k · 질문 수 · 호출 수 · 재시도 수 · 캐시 적중 수 · 토큰 합 · $ · 지연 p50/p95 · 예산 상한 · 멈춤 여부 <!-- style-exempt -->
- 테스트: 가짜 클라이언트로 지표 계산 · 예산 초과 시 멈춤 · 두 번째 실행 호출 0 · 누수 0 확인

### Task 4 — 리포트 (`generate/report.py`)

- `docs/139-answer.md`. 첫 줄 결론 한 문장(통과 기준 3)
- §1 지표 표 — 실패 징후 1~8의 측정값과 해당 구간을 나란히. 구간 판정 문구는 plan 문장 그대로
- §2 표본 10문항(golden, `random.Random(0).sample`) — 질문 · 생성 답 · 인용(조는 원문 앞 300자) · FAQ 공식 답(`faq-20240529.jsonl`) · 정답 조 · 검색 hit 여부
- §3 golden에서 abstain한 문항 전부 — qid · 질문 · 모델이 쓴 이유 · forced 여부 · retrieval_hit
- §4 범위 밖 10문항 — 답했는지와 답
- §5 문맥 밖 인용 목록, 틀린 인용 목록(인용 정밀도 0인 문항)
- §6 비용 — 호출 수 · 토큰 · $ · 지연

### Task 5 — 실제 실행

1. `uv run python -m cheongyak_rag.generate.answer "무주택세대구성원이란 무엇인가요?"`, 범위 밖 질문 1개, golden 질문 1개를 돌려 출력을 PR 본문에 붙인다
2. `uv run python -m cheongyak_rag.generate.evaluate` 첫 실행 → 실패 징후 1~8을 잰다. 1·3·4가 실패 구간이면
   프롬프트를 고치고 다시 잰다(재측정은 캐시 키가 바뀌어 다시 호출된다 — 예산 상한은 실행마다 6) <!-- style-exempt -->
3. 같은 명령 두 번째 실행 → 호출 0회, `answers.jsonl` `cmp`로 바이트 동일 확인
4. `uv run python -m cheongyak_rag.generate.report`

## Pre-PR checks

Pre-PR checks (all required — do not assume pass, show output):
1. New env vars: `git diff main...HEAD` added lines matching `os\.environ\.get|os\.getenv|process\.env\.` — log any found.
2. Server boots — detached-safe, NO interactive Ctrl+C (no TTY in orch). Background + timeout + curl the port + kill. Never bare `runserver` (hangs the loop till ORCH_STUCK_SECS). Django → `source <venv>/bin/activate && cd web && (timeout 20 python manage.py runserver 127.0.0.1:8000 --noreload &) ; sleep 8; curl -sf http://127.0.0.1:8000/ -o /dev/null && echo BOOT_OK ; pkill -f runserver`; CDK → `cdk synth` (no server); Zappa/Lambda Django → same background+timeout with `PYENV_VERSION=<env> --settings=<app>.settings.local`; CLI/library → smoke-run the entrypoint (it must self-terminate); else project-specific.
   - 이 repo: FastAPI → `(timeout 20 uv run uvicorn cheongyak_rag.main:app --port 8139 &) ; sleep 8; curl -sf http://127.0.0.1:8139/health && echo BOOT_OK ; pkill -f 'uvicorn cheongyak_rag.main:app --port 8139'`. 그리고 CLI smoke: `uv run python -m cheongyak_rag.generate.answer "무주택세대구성원이란 무엇인가요?"` exit 0
3. Full test suite green (show pass/fail). If no runner: state `no tests — skipped`, do not silently pass.
   - `uv run pytest -q` (`test_health`는 Postgres가 떠 있어야 통과한다 — 메인 repo에서 이미 띄웠다) · `uv run ruff check` · `uv run ruff format --check`

Then: completeness via `sc:reflect` vs plan; code review via `superpowers:requesting-code-review` (fix all Critical/Important); commit (`~/prv` repo면 `docs/plans/`도 포함); PR via `gh pr create --assignee @me` (personal title + Summary/Changes/Notes, then update the Notion PR property). **PR을 만들면 이 루프는 끝난다** — 여기서 `pr-review-toolkit:review-pr`을 돌리지 말 것. 그 리뷰는 Phase C의 별도 세션이 맡는다. 여기서 돌리면 (a) 자기가 쓴 코드를 같은 컨텍스트가 리뷰하고 (b) PR 생성 후에도 커밋이 계속 얹혀 `orch ls`의 `done`이 완료를 뜻하지 않게 된다 (실측: PR 후 8분 이상 지속).

내장 `/code-review`를 여기 쓰지 말 것. 품질은 더 낫지만 **사람이 직접 치는 커맨드라 available-skills에 없다** — 헤드리스 세션에서 확인함. ralph가 호출하면 없는 스킬을 찾다 끝난다.

커밋 전 `superpowers:requesting-code-review`는 그대로 둔다 — 그건 커밋하기 전 자기 점검이고, Phase C는 커밋된 diff 전체를 새 컨텍스트가 다시 보는 것이라 겹치지 않는다.

## Done criteria

- 통과 기준 1~6이 전부 참이고 실패 징후 1~8의 측정값이 리포트에 있다 (실패 구간이면 고쳐서 다시 잰 값)
- 커밋 메시지는 한국어, 접두사는 `feature:` `add:` `fix:` `docs:` `test:` `refactor:` `chore:` 중 하나 + `: ` (괄호 scope 금지)
- `gh` 계정은 `jongwoo315`. 브랜치를 push하고 PR을 만든다. base는 `main`
- PR 제목: `[#139] generate: 검색 결과로 인용 단 답 생성과 abstain — CLI`
- **PR 본문 맨 위에 `## 착수 전 기준 (jw)` 절** — plan의 `## jw 기준` 원문 + 그 기준으로 잰 결과(실패 징후 1의 건수와
  리포트 표본 위치). 그 아래 Summary / Changes / 실패 징후 1~8 측정값 표 / Task 5-1 CLI 출력 3개 / Notes
- PR을 만든 뒤 Notion #139 페이지(`3fe41e61-65c0-81fa-9fae-cb62e89c40a2`)의 `PR` 프로퍼티에 PR URL을 넣는다
  (`NOTION_API_KEY`, `PATCH /v1/pages/{id}`, `Notion-Version: 2022-06-28`). `상태`·`작업일`은 건드리지 않는다
- `docs/decisions.md`는 건드리지 않는다 — PR 게이트에서 main 세션이 채운다
