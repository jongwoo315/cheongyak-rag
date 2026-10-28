# 74 리뷰 — PR #10

**대상:** `main...HEAD` — 21 commits (이 리뷰의 fix·test 8개 포함), 14 files (리뷰 파일 포함), 리뷰 전 +1694 −5 (13 files)
**plan:** docs/plans/74-1027-plan-pg-index.md

리뷰는 `pr-review-toolkit:review-pr`의 에이전트 4개(code-reviewer · pr-test-analyzer · silent-failure-hunter · comment-analyzer)가 낸 지적을 모아 이 세션이 코드와 대조해 처리했다. 에이전트가 실제 DB로 확인한 것은 k > `ef_search` 재현 하나다. 나머지는 코드를 읽고 추론한 지적이다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/retrieval/index_db.py:141` | `nearest`가 k > `hnsw.ef_search`(기본 40)이면 인덱스 스캔이 40개에서 멈춰 k개보다 적게 돌아온다(실제 DB에서 FAQ k=50 → 40행 재현). #79가 후보를 50개 받으면 걸린다 | fix `666b719` |
| 2 | Important | `src/cheongyak_rag/retrieval/index_db.py:100` | `load`가 빈 `rows`에서도 `DELETE FROM chunks`를 커밋하고 `0행 적재`로 성공해 테이블이 조용히 비워진다 | fix `a6940e9` |
| 3 | Important | `tests/test_retrieval_index_db.py:167` | `nearest(force_index=True)`·`ef_search`가 실제로 `SET LOCAL`로 적용되는지 보는 테스트가 없어, `_session_settings` 호출을 빼도 전부 통과한다(리포트의 「HNSW 강제로 쟀다」가 근거 없어진다) | fix `c781b6d` |
| 4 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:67` | `measure_load`가 빠진 행·바뀐 `text`·없는 인덱스를 DB에서 실제로 세는지 보는 테스트가 없다(`zone_load`에 숫자를 직접 넣는 테스트뿐) | fix `e433377` |
| 5 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:158` | `measure_topk`의 `ef_search=100` 재측정 분기와 k개 미만 집계가 한 번도 실행되지 않는다. 키 이름이 어긋나면 실제 리포트 생성이 죽는데 테스트가 못 잡는다 | fix `bb2646e` |
| 6 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:224` | 빈 `tokens` 행을 `measure_tokens`가 잡는지 보는 테스트가 없다. `r[2] == ""` 비교가 틀리면 징후 6이 영원히 통과로 나온다 | fix `2c6311d` |
| 7 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:393` | 리포트의 「pgvector · kiwipiepy — `tokens`를 다시 만들어야 하는지 볼 때 쓰는 버전」은 pgvector에 맞지 않는다. `tokens`는 kiwipiepy만 만든다 | fix `cacfc21` |
| 8 | Important | `src/cheongyak_rag/retrieval/index_db.py:122` | `nearest_sql` 설명이 부분 인덱스 조건을 「글자 그대로 같아야 한다」고 적었다. planner가 증명하는 것은 함축이다 | fix `7465392` |
| 9 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:160` | 징후 2의 top-k 일치 비율이 인덱스 사용 여부를 안 본다. `enable_seqscan=off`가 seq scan을 막지는 않아서, 인덱스를 안 타면 전수 계산끼리 비교해 100%가 나온다 | push-back — plan이 그 경우를 징후 1의 「다시 잰다」(`enable_seqscan=off`에서도 인덱스를 안 탐 → 쿼리를 고쳐 다시 잰다)로 이미 정했다. 같은 표 1번 칸에 `부분 인덱스를 탄 쪽: law 예, faq 예`가 찍혀 읽는 사람이 함께 본다. 징후 2 구간에 새 값을 더하면 plan의 3구간 정의를 바꾼다 |
| 10 | Important | `src/cheongyak_rag/retrieval/index_db.py:218` | `OperationalError`만 잡아서 그 밖의 오류(`ProgrammingError`·`IntegrityError`·`DataError`·OpenAI 오류·깨진 `selected.json`)는 traceback과 Python 기본 종료 코드 1로 끝난다. 이 코드에서 1은 「징후 1 미완」이다. 연결 실패 → exit 2 경로를 보는 테스트도 없다 | defer — 호출하는 쪽이 지금은 사람(PR 게이트)이고 traceback이 stderr에 남는다. 자동으로 종료 코드를 읽는 쪽(CI 등)이 생길 때 별도 코드(예: 4)로 나누고 그 경로 테스트도 같이 둔다 |
| 11 | Important | `src/cheongyak_rag/retrieval/index_db.py:284` | 종료 코드 1이 징후 1이 미완일 때만 나온다. 징후 2·3·4·5·6이 미완이어도 exit 0이다 | push-back — plan 통과 기준 6과 Task 5가 「실패 징후 1이 미완이면 exit 1」로 정했다. 나머지 구간은 리포트 표와 `구간:` 출력 줄에 찍힌다 |
| 12 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:70` | 기대 행 수가 DB를 만든 것과 같은 함수(`law_chunks`·`faq_chunks`)에서 나온다. 입력이 같이 줄면 `rows == expected`가 그대로 통과한다. 568·123이 코드에 없다 | push-back — plan 징후 1이 대조 대상을 「메모리 계산이 쓰는 청크」로 정의했고 이 측정은 저장 과정에서 바뀌었는지를 본다. 568/568은 표 1번 칸에 값으로 찍혀 사람이 읽는다. 입력 데이터가 줄었는지는 #73·#135 쪽 문제다 |
| 13 | Important | `src/cheongyak_rag/retrieval/index_db.py:33` | `LAW_EFFECTIVE`가 하드코딩이라 법령 파일이 새 버전으로 바뀌고 이 값이 그대로면 옛 MST가 새 조문에 붙는다 | defer — 설계 §5-2가 「시행일 2026-06-15 행의 MST」로 정했고 법령 여러 버전은 plan이 이번에 안 하는 것(#135)으로 뺐다. 그 티켓에서 jsonl의 `mst`·`effective_date`와 대조한다 |
| 14 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:179` | 골든 질문의 캐시 미스는 징후 4 구간에 안 들어가서, 청크 미스가 0이면 질문 임베딩이 API를 불러도 통과다 | push-back — plan이 「골든 질문의 캐시 미스와 API 호출 수는 따로 적는다(판정에 안 쓴다)」로 정했고, 리포트 4번 칸에 두 값이 같이 찍힌다 |
| 15 | Important | `src/cheongyak_rag/retrieval/index_db_report.py:192` | `measure_rerun`을 순수 함수로 직접 검증하지 않는다. `ids_changed`가 채워지는 경우를 지나가는 테스트가 없다 | defer — 정상(0)과 드리프트 경로는 e2e가 지나가고 함수가 비교 한 줄이다. 값을 직접 넣는 단위 테스트는 위험이 낮아 이번 PR에서 뺀다 |
| 16 | Suggestion | `src/cheongyak_rag/retrieval/index_db_report.py:334` | 생성되는 리포트가 「프로세스를 따로 두 번 돌린 비교는 PR 본문에 있다」로 PR 본문을 가리킨다. PR 본문은 코드와 함께 옮겨지지 않는다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/retrieval/index_db.py:150` | `nearest` 설명의 「행이 568개면」「#79가 쓴다」는 행 수·티켓 상태가 바뀌면 코드와 안 맞게 된다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/retrieval/index_db_report.py:192` · `:158` | `measure_rerun` 설명에 `text`·`tokens`가 빠졌고, `measure_topk`의 반환 타입 표기가 `dict`인데 실제는 튜플이다 | 기록만 |
| 19 | Suggestion | `alembic/versions/0004_chunks.py:39` | 「인덱스 하나에 필터를 걸면 k개보다 적게 돌아온다」는 pgvector 0.8의 `iterative_scan`을 쓰지 않을 때의 동작이다. 전제가 안 적혀 있다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/retrieval/index_db.py:266` | 리포트 md와 json을 따로 쓴다. 중간에 실패하면 새 md에 옛 json이 남는다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/retrieval/index_db_report.py:142` | top-k 일치가 집합 비교라 같은 k개의 순서 어긋남을 못 본다 | 기록만 — plan 징후 2가 집합 비교로 정의 |
| 22 | Suggestion | `src/cheongyak_rag/retrieval/index_db.py:116` | `VECTOR_LITERAL`이 지수에 `+`가 든 꼴(`1e+20`)을 못 줄인다. 실제 임베딩은 `e-05` 꼴이다 | 기록만 |
| 23 | Suggestion | `tests/fakes.py:8` · `tests/test_retrieval_index_db_report.py` | `FakeEmbedder` 첫 줄 설명이 `dim > 16` 분기를 못 말한다. `zone_load`의 `extra` 단독 테스트가 없다. `np.isclose`로 정수를 비교한다 | 기록만 |
| 24 | Suggestion | `src/cheongyak_rag/retrieval/index_db.py:100` | 비우고 다시 넣을 때 HNSW 인덱스에 dead tuple이 남는다. 이미 PR 본문 Notes에 있다 | 기록만 — 568행이라 무시 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. alembic `0004`가 `chunks`와 인덱스 셋을 만들고 downgrade가 지운다. upgrade → downgrade → upgrade 통과 | 예 | `alembic/versions/0004_chunks.py` · `tests/test_chunks_migration.py` 4개 통과 |
| 2. 청크를 `query.Index`와 같은 함수로 만든다 | 예 | `index_db.py` `build_rows`가 `law_chunks`·`faq_chunks`만 호출 · `tests/test_retrieval_index_db.py` 첫 테스트 |
| 3. 한 트랜잭션에서 비우고 전부 넣는다. 두 번 돌려도 같다 | 예 | `test_load_twice_gives_the_same_rows` · `test_failed_load_keeps_previous_rows` · 이 리뷰에서 빈 입력 거절 추가(`a6940e9`) |
| 4. `tokens` = `to_tsvector('simple', 형태소 토큰)`. 빈 행 없음 | 예 | `test_row_fields_follow_the_design` · `test_load_has_no_empty_tokens` |
| 5. `nearest`가 `WHERE source = :source ORDER BY … LIMIT :k`. `enable_seqscan=off`에서 부분 인덱스 이름이 EXPLAIN에 보인다 | 예 | `test_explain_shows_the_partial_index_when_seqscan_is_off` · k > 40 보강(`666b719`) |
| 6. CLI. `--report`면 징후 1~6을 재서 두 파일에 쓴다. 징후 1 미완이면 쓴 뒤 exit 1 | 예 | `test_report_writes_markdown_and_json_with_all_six_measures` · `test_report_exits_1_after_writing_when_vectors_do_not_match_cache` · exit 2·3 테스트 |
| 7. 전체 테스트 · `ruff check` · `ruff format --check` 통과 | 예 | `uv run pytest -q` 763 passed(fix 후) · ruff 두 개 통과 |

| 실패 징후 | 리포트에 찍힌 값 (`docs/74-pg-index.md`, 실제 DB) |
| --- | --- |
| 1. 적재와 인덱스 | 행 568/568 · 집합 차이 0·0 · `text` 다른 행 0 · 벡터 다른 행 0 · 인덱스 3개 있음 · `enable_seqscan=off`에서 law·faq 모두 부분 인덱스 사용. 구간은 리포트가 「통과」로 찍음 |
| 2. HNSW top-k = 전수 top-k | 조문 123/123 · FAQ 123/123 |
| 3. k개 미만 문항 | 0 |
| 4. 캐시에 없던 청크 | 0 (골든 질문 미스 0 · API 호출 0회) |
| 5. 재실행 | 한 프로세스 두 번: 바뀐 chunk_id 0 · 내용이 바뀐 행 0. 별개 프로세스 두 번은 PR 본문에 sha256 같음(이 세션은 다시 재지 않음) |
| 6. 빈 `tokens` 행 | 0 |

위 값은 리포트가 찍은 값을 옮긴 것이다. 이 세션은 실제 DB에 `--report`를 다시 돌리지 않았다. 리뷰 fix는 코드·테스트·리포트 문구만 바꿨고 측정값은 그대로다. 리포트가 만든 `docs/74-pg-index.md` 79행은 문구만 손으로 고쳤다(`cacfc21`).

테스트는 fix 뒤에 `uv run pytest -q` 전체가 763 passed(리뷰 전 757)다.
