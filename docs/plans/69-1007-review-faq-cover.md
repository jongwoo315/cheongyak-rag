# 69 리뷰 (2차) — PR #2

**대상:** `e411b84..HEAD` (반려 뒤 Task 6 이후) — 4 commits (구현 1, 이 리뷰의 처리 3, 이 리뷰 파일 제외), 3 files, +172 −52. 전체 `main...HEAD`는 31 commits, 12 files, +2746 −2
**plan:** docs/plans/69-1005-plan-law-parse.md (§실패 징후 4, Task 6)
**앞선 리뷰:** docs/plans/69-1005-review-law-parse.md (e411b84 이전 커밋 — 지적 28건 처리)

리뷰는 `pr-review-toolkit:review-pr` 에이전트 4개(code · tests · comments · types)로 했다. 바뀐 곳에 `try/except`가 없어 errors 에이전트는 돌리지 않았다.
code 에이전트가 `faq_cross`를 실제 FAQ JSONL(480쌍)과 현행 법령 JSONL로 직접 돌려 plan 사전 측정과 대조했다. 값은 아래 `plan 대조`에 있다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/ingest/law_report.py:500` | 리포트 문구에 「jw가 고른 A안」이 있다. 사람 이름과 B안이 무엇이었는지 정의 없는 이름이라 리포트만 읽으면 뜻이 안 잡힌다. 이전 문구에 있던 「실제보다 클 수 있다」는 경고도 사라졌다. 실제 영향은 양방향이다 — 다른 법령 조가 규칙에 없으면 커버 안 됨이 늘고, 번호가 우연히 같으면 커버가 는다 | fix `5bf51d0` |
| 2 | Important | `tests/test_law_report.py:254` | `_text_before`가 답변에서 못 찾으면 질문에서 찾는 경로를 확인하는 테스트가 없다. 순서나 `.get` 기본값이 깨져도 실제 40쌍의 법령 이름이 빠질 뿐 아무것도 실패하지 않는다 | fix `a121e06` |
| 3 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:344,504` | 「앞 20자」가 `CONTEXT_CHARS`와 따로 글자로 적혀 있다. `before` 주석은 「FAQ 본문」이라 했지만 코드는 답변 다음 질문을 보고, 조가 맨 앞이어도 빈 문자열이 나온다는 말이 없다. (code·comments·types 에이전트 셋이 같은 곳을 짚었다) | fix `2cd1b32` |
| 4 | Suggestion | `tests/test_law_report.py:254` | `CONTEXT_CHARS`로 자르는 것과 공백·줄바꿈을 접는 것을 확인하는 테스트가 없다. 지금 테스트의 앞 글자는 11자라 20자 경계에 안 닿는다 | 기록만 |
| 5 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:403` | 커버 안 된 쌍이 인용한 개정 조(`제3조`)가 참고 줄 `covered_pairs_amended`·`amended_labels`에 안 섞이는지 확인하는 테스트가 없다. `if gone: continue` 위치가 바뀌어도 통과한다 | 기록만 |
| 6 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:491` | 인용 있는 쌍이 0이면 `커버 0 (0%)`로 찍혀 「전부 커버 안 됨」으로 오해할 수 있고, FAQ가 0쌍이면 참고 줄이 `커버된 쌍 중  뒤에`로 빈칸이 생긴다. 0으로 나누지는 않는다(직접 확인). 이 경우를 확인하는 테스트도 없다. 실제 데이터(인용 있는 쌍 182)에서는 일어나지 않는다 | 기록만 |
| 7 | Suggestion | `tests/test_law_report.py:204` | 커버 안 된 쌍이 6개 이상일 때 전부 나열되는지(plan: 40쌍 전부), 없을 때 「커버 안 된 쌍」 머리 줄이 안 나오는지, 같은 조를 한 쌍 안에서 두 번 인용해도 `Uncovered`가 하나인지 확인하는 테스트가 없다 | 기록만 |
| 8 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:504` | 머리 줄은 「커버 안 된 쌍」인데 줄은 쌍 × 없는 조 단위다. 실제 데이터에서 쌍 40개가 줄 46개로 나온다. 위쪽 「커버 안 됨 40」과 줄 수가 달라 보인다 | 기록만 |
| 9 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:518` | 참고 줄의 `제3조(2026-06-15)` 괄호 날짜는 그 조의 최근 개정일인데 설명이 없어 cutoff 뒤 첫 개정일로 읽힌다 | 기록만 |
| 10 | Suggestion | `src/cheongyak_rag/ingest/law.py:374`, `tests/test_law_report.py:328`, plan §실패 징후 3 참조 | 리포트 항목 이름이 「FAQ 인용 커버」로 바뀐 뒤에도 stderr 문구는 「FAQ 인용 대조」, 테스트 구역 제목은 「(b)」, plan Task 4·Done criteria는 「§실패 징후 3」으로 남았다. plan은 RESUME 절이 징후 4로 바뀐 것을 설명한다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:377` | `_text_before`는 같은 조가 본문에 여러 번 나와도 처음 나온 자리의 앞 글자만 가져온다. 실제 데이터에서 이런 쌍은 5개(Q141·Q367·Q429·Q432 등)이고 모두 법령 이름이 제대로 보인다 | won't-fix — 실제 5쌍이 전부 맞게 나온다. 한 답변 안에서 같은 번호를 다른 법령으로 인용하는 경우를 위해 여러 곳을 붙이면 줄이 길어져 읽기가 나빠진다 |
| 12 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:354,357` | `cited_labels`·`current_labels`는 개수(`int`)인데 `amended_labels`는 목록(`list[str]`)이라 접미사가 같고 타입이 다르다. `amended_labels`와 `latest_amendment`가 한 사실을 둘로 나눠, 리포트가 키를 맞춰 찾는다 | defer — 생성 지점이 `faq_cross` 하나라 지금은 어긋날 수 없다. 이름을 바꾸면 테스트 5곳과 리포트가 같이 바뀌는데 동작은 같다. #70이 이 구조체를 쓰기 시작할 때 같이 정리한다 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. CLI 실행, 캐시·JSONL 생성 | 판정 불가 | 이 리뷰에서 실제 API 호출을 다시 하지 않았다. `data/raw/law-008243-20260615.json`·`data/processed/law-008243-20260615.jsonl`이 있고, 호출 결과는 앞선 리뷰 파일과 PR 본문에 있다 |
| 통과 2. `LAW_OC`가 비면 exit 1 | 예 | `fce672b`의 테스트가 통과한다 |
| 통과 3. 대조 리포트가 실행 끝에 출력 | 예 | `test_faq_cross_is_in_report_when_faq_jsonl_exists`(`tests/test_law_cli.py`), `test_report_shows_faq_cross_values`(`tests/test_law_report.py`) 통과 |
| 통과 4~5. 현행 MST를 검색에서 고름, 캐시 있으면 본문 재다운로드 없음 | 예 | 이번 범위(`e411b84..HEAD`)가 건드리지 않았다. 앞선 리뷰에서 확인 |
| 통과 6. 전체 테스트, `ruff check` · `ruff format --check` | 예 | `154 passed`(처리 뒤, 처음 153), `All checks passed!`, `31 files already formatted` |
| 징후 4. 인용 있는 쌍 182 · 커버 142(78%) · 안 됨 40 | 예 (쌍 수 일치) | code 에이전트가 480쌍 JSONL에 직접 돌려 182 · 142 · 40을 얻었다. 사전 측정과 차이 0쌍이다. 판정은 PR 게이트에서 한다 |
| 징후 4. 인용된 조 72종 중 현행에 있는 것 58종 | 값만 적는다 | 실측은 72종 중 57종이다. 삭제된 `제29조` 하나를 사전 측정은 현행으로, 코드는 삭제 조문이라 현행 아님으로 세서 1 차이가 난다. 제29조를 인용한 쌍(Q61·Q129·Q141)은 현행에 없는 제74조도 같이 인용해 쌍 수는 어느 쪽으로 세도 같다. PR 본문이 이 이유를 이미 적고 있다 |
| 징후 4. 커버 안 된 쌍은 `q_no`·조·앞 20자를 전부 나열 | 예 | 줄 46개 모두 앞 글자가 비어 있지 않고 법령 이름이 보인다(code 에이전트 실행) |
| 징후 4. 개정일은 커버 판정에 쓰지 않는다 | 예 | `test_faq_cross_amendment_date_does_not_decide_coverage`(`tests/test_law_report.py:217`) 통과 |

## 마지막

- 테스트: 처리 뒤 `154 passed`, `ruff check`·`ruff format --check` 통과.
- `PYTHONPATH=src uv run --no-sync …`로 실행했다(plan RESUME 절의 지시).
