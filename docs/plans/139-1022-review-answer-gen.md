# 139 리뷰 — PR #6

**대상:** `main...HEAD` — 리뷰 시작 시점 8 commits, 18 files, +2151 −2 (리뷰 fix 8 commits 포함 시 16 commits, +2303 −2)
**plan:** docs/plans/139-1022-plan-answer-gen.md

리뷰 방식: `pr-review-toolkit:review-pr` 에이전트 5개(code-reviewer · pr-test-analyzer · silent-failure-hunter · comment-analyzer · type-design-analyzer). 중복 지적은 한 행으로 합쳤다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/evaluate.py:74` | 429만 재시도해서 5xx·연결 오류·시간 초과 한 번이 그대로 error 행이 되고, 실패 징후 1(4건 이상 미완)에 잡힌다. 재시도 수도 0으로 남는다 | fix `26ea5bf` |
| 2 | Important | `src/cheongyak_rag/generate/answer.py:187` | `resp.choices`·`resp.usage` 접근이 try 밖이라 응답 구조가 깨지면 일괄 실행이 죽고 지금까지의 행을 잃는다 | fix `0cc1257` |
| 3 | Important | `src/cheongyak_rag/generate/evaluate.py:131` | `index.search`(질문 임베딩 호출)가 실패하면 traceback으로 죽고 partial 파일이 안 남는다 | fix `adb78cf` |
| 4 | Important | `src/cheongyak_rag/generate/answer.py:190` | 가격 표에 없는 모델이면 유료 호출이 끝난 뒤 `cost_usd`가 KeyError를 내고, 그 응답은 캐시에도 안 남는다 | fix `1cdbb95` |
| 5 | Important | `src/cheongyak_rag/generate/evaluate.py:229` | 실패 행이 있던 결과를 이어 받는 실행은 답이 달라져 `first_run`을 덮어쓴다. 리포트 6a가 실제 첫 실행(약 133회)이 아니라 이어 받은 실행의 호출 수(예: 2회)를 "정상"으로 낸다 | fix `173ce0b` |
| 6 | Important | `tests/test_generate_answer.py` | `make_client`의 빈 키 점검과 CLI exit 1이 테스트에 없다 | fix `be0ead5` |
| 7 | Important | `tests/test_generate_evaluate.py` | `retrieval_hit`의 false 경우가 테스트에 없다. 리포트 §3과 hit@5 정밀도가 이 값에 기대고 있다 | fix `1609d96` |
| 8 | Important | `tests/test_generate_report.py` | `Q` 인용(FAQ) 렌더 경로가 테스트에 없다. 실제 데이터에는 FAQ 인용이 많다 | fix `f9cf7f6` |
| 9 | Important | `tests/test_generate_evaluate.py:summarize` | `latency_p50`·`latency_p95`·`usd_new`를 검증하는 테스트가 없다 (실패 징후 7이 읽는 값) | defer — 현재 데이터에서 값이 맞다는 것은 리포트 대조로 확인했다(p50 1.407 · p95 2.12). 지연 계산이 바뀌는 티켓에서 같이 넣는다 |
| 10 | Important | `tests/test_generate_report.py:render` | 표 6a~8 등의 구간 함수에 넘기는 인자가 뒤바뀌어도 잡는 테스트가 없다 (실패 데이터를 넣은 render 테스트 없음) | defer — 구간 함수 단위 테스트는 있고, 현재 리포트는 손으로 표와 `config.json`을 대조해 일치함을 확인했다. 후속에서 실패 데이터 render 테스트 추가 |
| 11 | Important | `tests/test_generate_answer.py:format_answer` | CLI 출력의 300자 자름, 문맥 밖 인용 줄, forced 표시 분기를 확인하는 `assert`가 없다 | defer — 통과 기준 1 내용은 happy path 테스트와 Task 5 실제 실행 출력으로 확인됨. 분기 `assert`는 후속 |
| 12 | Important | `src/cheongyak_rag/generate/report.py:139` | 모델이 답을 하고 유효 인용이 없어 코드가 abstain으로 바꾼 범위 밖 문항도 「범위 밖 abstain」에 센다 | push-back — 사용자에게 나가는 최종 결과가 abstain이라 plan의 「최종 abstain」과 같다. 바뀐 건수는 실패 징후 1에서 따로 센다(현재 0건) |
| 13 | Suggestion | `src/cheongyak_rag/generate/answer.py:94` | 캐시 키가 `SCHEMA`·`MAX_COMPLETION_TOKENS`를 안 담아서, 이 둘을 바꿔 다시 재도 캐시가 적중해 「호출 0회」로 나온다 | defer — plan이 키를 `sha256(model + system + user)`로 정했다. 이 둘을 바꾸는 후속 티켓에서 키에 넣는다 |
| 14 | Suggestion | `src/cheongyak_rag/generate/report.py:218` | `run["stopped"]` 분기는 `config.json`에 멈춘 실행이 안 써져서 도달할 수 없다. 멈춘 실행의 사실은 `config.partial.json`에만 있다 | defer — plan의 「config에 멈춘 사실」은 partial 파일로 충족. 리포트가 partial을 읽는 것은 후속 |
| 15 | Suggestion | `src/cheongyak_rag/generate/evaluate.py:229` | 실패가 있는 전체 실행도 `answers.jsonl`을 덮어쓰고 exit 0이다 | push-back — 실패 행이 리포트 §3 목록(실패 징후 1의 1~3건 구간)으로 읽혀야 해서 partial로 보내면 plan과 어긋난다. 이전 호출 수 손실은 #5에서 막았다 |
| 16 | Suggestion | `src/cheongyak_rag/generate/answer.py:73` | 오류 행의 `abstain`이 기본값 true라서 표본 절에서 실패 행이 「abstain: 예」로 보인다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/generate/answer.py:208` | forced abstain 행은 모델이 쓴 답 본문을 그대로 두어 §3 「모델이 쓴 이유」 열이 그 행에서는 부정확하다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/generate/report.py:208` | 7번 행 이름 「캐시 안 탄 값」인데 `summarize`는 캐시 행의 저장된 지연도 포함한다. 값 차이는 현재 데이터에서 없다(첫 실행 캐시 1건) | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/generate/report.py:7,70` | 「plan 문장 그대로」 문구가 `zone_failures`의 뒷절을 생략했고, `zone_usd`의 「$6에 이르면 멈춘다」는 코드(`>`, 캐시 제외)와 정확히 같지 않다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/generate/answer.py:134,181` | 모델이 거절하면 `content=None`이라 error가 「빈 응답」으로만 나온다. `message.refusal`을 안 남긴다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/generate/answer.py:105` | 깨진 줄 정리가 캐시 전체를 `write_text`로 바로 다시 쓴다. 쓰다 끊기면 캐시를 잃는다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/generate/report.py:289` | plan의 「$3~6 질문당 토큰」·「> 30초 원인」 구간 동작이 리포트에 없다 (현재 $0.76, p95 2.1초라 해당 없음) | 기록만 |
| 23 | Suggestion | `src/cheongyak_rag/generate/report.py:135` | 인용이 0건일 때 `outside_ratio`가 0.0, 답한 golden이 0건일 때 정밀도가 0.00으로 「측정 불가」 대신 값처럼 보인다 | 기록만 |
| 24 | Suggestion | `tests/test_generate_evaluate.py` | 연속 실패 카운터 리셋, 캐시 행이 예산에 안 잡히는 것, 입력 파일 누락 시 exit 1, `test_attempt_latency_excludes_backoff_sleep`(어떤 값이든 통과) 등 테스트 약점 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1: `answer` CLI가 답·abstain·인용 조 원문(앞 300자)·인용 FAQ·검색 상위 조 5개·토큰과 $를 출력하고 exit 0 | 예 | `answer.py:format_answer` · `tests/test_generate_answer.py` CLI 테스트 · PR 본문 Task 5-1 출력 |
| 통과 2: `evaluate`가 golden 123 + 범위 밖 10을 돌려 `answers.jsonl`·`config.json`을 쓴다 | 예 | `runs/139/answers.jsonl` 133줄 · `runs/139/config.json` `questions: 133` |
| 통과 3: `report`가 `docs/139-answer.md`를 쓰고 첫 줄이 결론 한 문장 | 예 | `docs/139-answer.md:1` · 리포트를 다시 만들어 커밋본과 바이트 동일 확인(fix 뒤에도) |
| 통과 4: 두 번째 `evaluate`에서 호출 0회, `answers.jsonl` 바이트 동일 | 예 | `config.json` `second_run.calls: 0`, `cache_hits: 133` · `test_second_run_makes_no_call_and_is_byte_identical` |
| 통과 5: `runs/139/`와 `docs/139-answer.md`를 커밋, `data/`는 커밋 안 함 | 예 | `git diff --stat main...HEAD`에 `runs/139/*`·`docs/139-answer.md`, `data/` 없음 |
| 통과 6: 전체 테스트 통과, `ruff check`·`ruff format --check` 통과 | 예 | `445 passed` · `All checks passed!` · `75 files already formatted` (fix 8 commits 뒤) |
| 실패 징후 1: 생성 실패 + 인용 없어 abstain으로 바꾼 답 — 0건 통과 / 표본 10문항 나란히 | 값만: 0 + 0 = 0건. 표본 10문항 있음 | `docs/139-answer.md` §1 · §2 |
| 실패 징후 2: 문맥 밖 인용 비율 ≤ 2% | 값만: 0.0% | `docs/139-answer.md` §1 · 유효 222건 무효 0건 |
| 실패 징후 3: golden 최종 abstain ≤ 10% | 값만: 3.3% (4/123), 4건 모두 retrieval_hit 참 | `docs/139-answer.md` §1 · §3 |
| 실패 징후 4: 범위 밖 abstain 9~10 정상 | 값만: 9/10 (ood-7이 답함) | `docs/139-answer.md` §4 |
| 실패 징후 5: 인용 정밀도 ≥ 0.6 정상 | 값만: 0.75 (문항 87), hit@5만 0.84 (문항 78) | `docs/139-answer.md` §1 |
| 실패 징후 6: 호출 ≤ 140, $ ≤ 3, 입력 토큰 평균 ≤ 8,000, 두 번째 실행 0회 | 값만: 132회 · $0.7567 · 6,729 · 0회 | `runs/139/config.json` |
| 실패 징후 7: 지연 p95 ≤ 15초 | 값만: p95 2.12초 | `runs/139/config.json` `first_run.latency_p95` |
| 실패 징후 8: 누수 0 | 예: 0 | `docs/139-answer.md` §1 |
| 이번에 안 하는 것: `retrieval/` 동작 변경 없음, k=5·faq_k=3 고정, golden 변경 없음, 새 의존성 없음 | 예 | `git diff --stat main...HEAD`에 `retrieval/`·`pyproject.toml`·`runs/golden.jsonl` 없음 |

## 처리 메모

- fix 8개는 지적마다 커밋 하나다. `evaluate.py`가 `openai.APIConnectionError`를 새로 import하는데 `openai`는 이미 의존성이다.
- fix 뒤에도 `runs/139/answers.jsonl`·`config.json`·`docs/139-answer.md`는 바뀌지 않았다 (리포트를 다시 만들어 `git status` 변화 없음 확인).
- 테스트 `445 passed`, `ruff check`·`ruff format --check` 통과.
