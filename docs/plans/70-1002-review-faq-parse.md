# 70 리뷰 — PR #1

**대상:** `main...HEAD` — 15 commits (구현 7 + 리뷰 처리 8), 15 files, +1169 −0 (이 리뷰 파일 제외)
**plan:** docs/plans/70-1001-plan-faq-parse.md

리뷰는 `pr-review-toolkit:review-pr` 에이전트 5개(code · tests · errors · comments · types)로 했다.
에이전트가 낸 수치 중 `ARTICLE` 정규식 문제(호의N 3건, 띄어쓰기 13건)는 실제 JSONL로 다시 확인했다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/ingest/faq_report.py:70` | 공백을 전부 뺀 비교로 불일치 0을 만들었다. plan의 「공백 정규화」를 공백 연속 합치기로 읽으면 32쌍(전부 `question`)이라 실패 징후 1은 「11 이상」 구간이다. PR 본문은 줄 안 공백 15쌍 안팎을 「PDF 인쇄 차이」라 했지만 글리프 간격(Q40 6.0pt, Q56 3.2pt, Q85 5.5pt)상 PDF에는 공백이 인쇄돼 있고 PyMuPDF가 문자로 안 낸 것이라 파서 쪽 원인이다 | defer — `rawdict` 글리프 간격으로 공백을 복원하고 `_collapse` 기준으로 다시 잰다. 답변 본문의 붙은 단어(약 95곳)도 같은 문제라 #73 전에 별도 티켓이 필요하다. 이 PR에서는 32쌍을 값으로 고정해 `355984f`로 조용히 늘지 않게만 했다. 기준 해석(0 통과 vs 32 실패)은 게이트에서 jw가 정한다 |
| 2 | Important | `src/cheongyak_rag/ingest/faq.py:327` | `main()`이 검증 결과와 무관하게 exit 0이고 JSONL을 먼저 덮어썼다 | fix `af2d736` |
| 3 | Important | `src/cheongyak_rag/ingest/faq.py:275` | 흰색 10pt 숫자는 번호 순서 확인 없이 새 쌍을 시작해, 비슷한 글자가 있으면 쌍이 쪼개지고 exit 0이었다 | fix `9b5d660` |
| 4 | Important | `src/cheongyak_rag/ingest/faq_report.py:104` | 0쌍이면 `q_no_ok`가 참(`[] == list(range(1, 1))`)이라 연속으로 보고됐다 | fix `d5dd274` |
| 5 | Important | `src/cheongyak_rag/ingest/faq.py:166` | `제2조제2호의3`이 `제2조제2호`로(Q14·Q288·Q479), `제23조 제4항`이 `제23조`로(13쌍) 잘려 `cited_articles`가 틀렸다. plan의 정규식 그대로라 plan의 빈틈이기도 하다 | fix `f47ab20` |
| 6 | Important | `src/cheongyak_rag/ingest/faq.py:36` | 캐시된 파일은 존재만 보고 썼다. 이전에 HTML이 캐시된 파일이 남아 있으면 계속 쓰이고 오류도 파서 쪽을 가리킨다 | fix `3c7eff9` |
| 7 | Important | `src/cheongyak_rag/ingest/faq.py:84,202` | `join_wrapped`와 쪽 번호·머리말 제거(`_is_noise`)를 직접 확인하는 테스트가 없었다 (쪽 번호 필터를 꺼도 통과) | fix `e068c18` |
| 8 | Important | `src/cheongyak_rag/ingest/faq.py:88` | `join_wrapped` 설명의 「질문 15건 안팎」이 실측(붙은 단어 25건 또는 13건, 측정마다 다름)과 안 맞았다 | fix `9704903` |
| 9 | Important | `src/cheongyak_rag/ingest/faq.py:268` | 회색(`0x262626`) 줄은 앞에 중분류 번호가 없으면 `commit_middle`에서 조용히 버려지고 `skipped_chars`에도 안 잡힌다 | defer — 이 PDF에서는 버려진 줄이 0건으로 확인됐다. 판본이 바뀔 때 걸리는 위험이라 PDF sha256 고정과 함께 다음 판본을 다루는 티켓에서 처리한다 |
| 10 | Suggestion | `src/cheongyak_rag/ingest/faq.py:146` | `parse_toc`의 `else: continue`가 줄을 세지 않고 버린다. 목차 첫 쪽이 표지면 빈 목차도 안 걸린다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/ingest/faq.py:277` | 여러 줄로 접힌 소분류 제목은 마지막 줄만 남는다 (이 PDF에는 0건). 질문 줄 판별이 `colors == {파랑}`만 본다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/ingest/faq.py:20` | PDF 크기·sha256을 코드에 고정하지 않아 다른 판본이 들어오면 일부만 파싱된다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/ingest/faq.py:190` | `cite_articles`가 줄바꿈을 지우고 이어 붙여, 다른 줄의 `제N항`이 앞 `제N조`에 붙은 인용을 만들 수 있다 (후보 8건) | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/ingest/faq_report.py:132` | 목차에만 있는 쌍은 `pNone`으로 찍힌다. 목차의 중복 `q_no`는 `by_q`에서 조용히 합쳐진다 (`main`은 이제 `pair_count != len(toc)`로 막는다) | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/ingest/faq.py:164` | `FaqPair`가 가변이고 `cur`가 문자열 키 `dict`, `Mismatch.field`·`Leak.kind`가 자유 문자열이라 오타가 멀리서 터진다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/ingest/faq.py:301` | `write_jsonl`이 `atomic`하지 않아 쓰는 도중 중단되면 일부만 남는다. 검증 실패 때 덮어쓰지 않는 것은 `af2d736`에서 막았다 | 기록만 |
| 17 | Suggestion | `tests/conftest.py:12` | PDF가 없을 때 31개 테스트가 같은 오류로 죽고 구하는 방법 안내가 없다 (조용한 skip 금지는 plan 요구) | 기록만 |
| 18 | Suggestion | `tests/test_faq_report.py` | `_leaks`의 다음 질문 판별이 답변 전체 부분 문자열이라 짧은 질문이 우연히 겹치는 경우, `count_warnings` 여러 줄 입력, `BodyStats` 값, `page_start`가 테스트에 없다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/ingest/faq_report.py:137` | 「전부 공백 차이다」가 고정 문구라 공백 차이가 0건이어도 출력된다. `skipped_chars`는 `가. 주요내용` 제목 줄 자체가 아니라 그 아래 본문만 센다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. CLI가 exit 0으로 끝나고 `data/processed/faq-20240529.jsonl`을 쓴다 | 예 | `python -m cheongyak_rag.ingest.faq` exit 0, `480쌍 → data/processed/faq-20240529.jsonl`. 검증 실패 때 exit 1은 `af2d736` |
| 통과 2. 쌍 수 480, `q_no` 1~480 빈틈·중복 없음 | 예 | `tests/test_faq_body.py::test_480_pairs_contiguous` |
| 통과 3. 섹션 대조 리포트가 실행 끝에 출력된다 | 예 | CLI 출력 `== FAQ 파싱 리포트 ==`, `test_main_writes_jsonl_and_exits_zero` |
| 통과 4. 모든 쌍의 `question`·`answer`가 비어 있지 않다 | 예 | `test_every_question_and_answer_is_non_empty` |
| 통과 5. PDF를 `data/raw/`에 캐시하고 있으면 다시 받지 않는다 | 예 | `tests/test_faq_fetch.py::test_cached_file_skips_network`. 두 번째 실행 로그의 「캐시 사용」은 파일 존재만 보여 주고 네트워크 미사용은 이 단위 테스트가 보인다 |
| 통과 6. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과 | 예 | `46 passed` (리뷰 처리 후, 처음 38), `All checks passed!`, `21 files already formatted` |
| 실패 1. 섹션 불일치 (0 통과 / 1~10 표 / 11 이상 재설계) | 판정 불가 | 공백을 전부 뺀 비교 0쌍, 공백 연속만 합친 비교 32쌍(전부 `question`, 대분류·중분류·소분류 0). 어느 값이 plan의 「공백 정규화」인지는 지적 1 |
| 실패 2. 에러 없이 (예외 0, exit 0, 경고는 건수만) | 예 | exit 0, PyMuPDF 경고 3건 |
| 실패 3. 답변 경계 새는 것 (0 통과 / 1~5 목록 / 6 이상 실패) | 예 | 새는 쌍 0건 (`test_sections_match_toc_and_answers_do_not_leak`) |
| 실패 4. 답변 길이 분포와 30자 미만·3000자 초과 목록 | 값만 | 최소 26 / 중앙값 214 / 최대 3021, 해당 2건(Q157 26자, Q325 3021자). 판정은 게이트 |
| 이번에 안 하는 것: alembic·DB 미접촉 | 예 | `git diff --name-only main...HEAD`에 alembic 0건, 새 환경변수 0건 |

## 확인한 것

- 테스트: 리뷰 처리 후 `46 passed`, `ruff check`·`ruff format --check` 통과.
- 리뷰 처리 후 실제 PDF로 CLI를 다시 돌렸다: 480쌍, exit 0, 섹션 불일치 0, 엄격 비교 32쌍, 새는 쌍 0.
