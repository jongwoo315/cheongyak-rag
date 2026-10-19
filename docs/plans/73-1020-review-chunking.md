# #73 리뷰 — PR #4

**대상:** `main...HEAD` — 16 commits, 30 files, +4514 −0 (리뷰 fix 5건 포함)
**plan:** docs/plans/73-1020-plan-chunking.md

리뷰는 `pr-review-toolkit:review-pr`의 에이전트 5개(code · tests · errors · comments · types)로 했다. 아래 지적은 모두 코드를 읽거나 실행해 확인한 것만 적었다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/retrieval/chunk_report.py:138` | 고른 후보가 평균 차이 최대 후보와 다를 때, 첫 줄이 고른 후보 이름에 최대 후보의 평균·CI·p를 붙인다. 재현: `item` +0.06 [−0.01, +0.13], `paragraph` +0.05 [+0.01, +0.09]이면 `paragraph`를 고르면서 CI가 0을 포함하는 수치를 적는다 (통과 기준 3 위반). 지금 run은 `article`을 골라 영향 없음 | fix `9e23a53` |
| 2 | Important | `tests/test_retrieval_chunk_report.py:129` | 동률이면 청크 수가 적은 쪽을 고르는 규칙이 안 고정돼 있었다. `CANDIDATES` 순서에서 `paragraph`가 `item`보다 앞이라 `order()`에서 청크 수 항을 지워도 통과했다 | fix `d0e94aa` |
| 3 | Important | `tests/test_retrieval_chunk_report.py:111-138` | 평균이 가장 큰 후보의 CI 하한이 0 이하이고 평균이 더 작은 후보의 하한이 0 초과인 경우가 없었다. `min(winners)`를 `best`로 바꿔도 통과했다 | fix `9e23a53` |
| 4 | Important | `tests/test_retrieval_chunk_report.py:141-147` | 「모든 후보가 낮다」가 네 후보 전부 낮은 경우만 있었다. `all`을 `any`로 바꿔도 통과했다 | fix `d0e94aa` |
| 5 | Important | `src/cheongyak_rag/retrieval/chunk_spacing.py:52` | 목차 파싱이 실패해 공백만 다른 쌍이 0개면 `np.mean([])`가 nan이 되고 `band`가 「쌍별 값을 리포트에 목록」을 돌려줘 측정값처럼 `spacing.json`에 쓰인다 | fix `37fe0af` |
| 6 | Important | `tests/test_retrieval_chunk_eval.py:101-108` | `..._hand_computed_hybrid`가 같은 목록에서 나온 두 값을 비교하는 동어반복이다. 한 조에 청크가 여럿인 손계산이 없어, 조 순위끼리 RRF하는 순서가 안 고정돼 있었다 | fix `7883eff` |
| 7 | Important | `tests/test_retrieval_chunk_eval.py:111-118` | `best_path`(리포트 §4와 `query`가 보이는 path)가 순위를 통제한 입력으로 검증되지 않았다. bm25가 우연히 이기면 통과했다 | fix `7883eff` |
| 8 | Important | `tests/test_retrieval_chunk_eval.py:214-225` | `faq_hit`가 「cited가 gold를 전부 덮는다」로 바뀌어도 통과했다. plan은 「겹치면 1」이다 | fix `7883eff` |
| 9 | Important | `tests/test_retrieval_chunk_report.py:167-172` | 정답 조가 긴 문항 절 테스트가 `질문 5개`와 후보 이름만 본다. 절 3에 전체 문항을 넘겨도 통과했다 | fix `6e7d826` |
| 10 | Important | `src/cheongyak_rag/retrieval/chunk_report.py:482-498` | 리포트가 `runs/73/*/results.jsonl`을 golden qid로만 맞추고 `config.json`의 `chunk_count`·모델과 지금의 청킹을 대조하지 않는다. `chunk.py`를 고치고 run을 안 다시 돌리면 오래된 recall에 새 청크 통계·보존 검사가 붙는다. 이 PR의 run은 확인했다 — `15192cb`(chunk_eval 수정) 뒤 `--faq`를 다시 돌려 `results.jsonl`·`self_check.json`이 바이트까지 같았다 | defer — 실제 불일치는 없고(재실행으로 확인), 대조 장치는 #74 적재 전에 `config.json` 필드를 어떻게 쓸지 정한 뒤 넣는 편이 맞다 |
| 11 | Important | `src/cheongyak_rag/retrieval/chunk_report.py:534-538`, `chunk.py:246-250` | 보존 검사·#131 재현·자기 쌍 점검이 실패해도 종료 코드 0으로 `selected.json`을 쓴다. `query.py`와 #139가 그 파일을 기본 구조로 읽는다 | defer — 이 PR의 run은 전부 통과(보존 0/0, 재현 같음, leak 0)라 결함 후보가 선택되지 않았다. 실패 시 중단은 #139가 `selected.json`을 쓰기 시작할 때 같이 정한다 |
| 12 | Important | `runs/73/*/config.json` `commit` | `evaluate._commit()`이 untracked 파일을 안 봐서 모든 run의 `commit`이 `chunk_eval.py`가 생기기 전 `8fc7508`을 가리킨다. 출력은 현재 HEAD와 바이트까지 같다 | won't-fix — 출처 표기만 어긋나고 결과는 같다. 다시 돌려도 `-dirty` 판정이 같은 이유로 안 붙는다. `evaluate._commit`은 #131 파일이라 이 PR에서 안 건드린다 |
| 13 | Important | `tests/test_retrieval_chunk_eval.py:206-245` | FAQ dense·hybrid 순위에 독립 oracle이 없다. 문서 벡터 offset이 틀려도 「자기 쌍이 안 나온다」만 보면 통과한다 | defer — 실제 데이터에서 자기 쌍 1위 비율(dense 0.959)이 offset 오류를 잡는 사실상의 oracle이다. 독립 계산 비교 테스트는 FAQ 검색을 #139가 쓸 때 추가한다 |
| 14 | Important | `src/cheongyak_rag/retrieval/query.py:81-84` | #139가 부르는 공개 `search()`에 테스트가 없다. `selected.json`이 깨졌을 때 `JSONDecodeError`·`KeyError`가 힌트 없이 난다 | defer — `Index.search`는 테스트가 있고 CLI 통과 기준 5는 PR 본문 출력으로 확인했다. 공개 함수 계약은 #139가 호출 형태를 정할 때 같이 테스트한다 |
| 15 | Suggestion | `src/cheongyak_rag/retrieval/chunk_report.py:110-112` | 가장 높은 평균 후보가 「낮다」이고 모든 후보가 낮지는 않으면 구간을 「판정 불가」로 바꾸고, 첫 줄은 「신뢰구간이 0을 포함하고」라고 적는다. 그 경우 CI는 0을 포함하지 않는다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/retrieval/chunk_report.py:292` | 「FAQ 청크 480개」가 상수다. `chunk_count`는 `faq/config.json`에 있다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/retrieval/chunk_eval.py:238-242` | `leak_count`가 쓰는 `excluded`가 제외에 쓴 집합과 같은 것이라, 집합 계산이 틀리면 0으로 나온다. 독립 점검이 아니다 | 기록만 |
| 18 | Suggestion | `docs/73-chunking.md:205`, `chunk_spacing.py:38` | 붙은 단어 기준 문장에 「평균」이 없다. 같은 표의 Q384는 코사인 0.870으로 쌍별로 읽으면 반대 결론이다 | 기록만 |
| 19 | Suggestion | `docs/73-chunking.md:66` | §4 열 「가장 높이 오른 청크」는 hybrid 기준이 아니라 bm25·dense 중 그 조가 더 높이 오른 쪽의 청크다. 코드 docstring은 맞다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/retrieval/chunk.py:63`, `chunk_eval.py:185` | `_lines`의 「빈 줄은 없다」는 호·목에는 필터가 없다(현재 데이터는 0건). `_faq_rankings` docstring에 `q_no` 일치 제외가 안 적혀 있다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/retrieval/chunk.py:25-32`, `chunk_eval.py:35-39` | `Chunk`는 frozen인데 `meta`가 dict라 `hash()`가 `TypeError`. `_Doc.label`이 청크 id라 `Chunk.label`(조)과 이름만 같다 | 기록만 |
| 22 | Suggestion | `runs/73/`, `docs/73-chunking.md` §8 | `paragraph` 후보에 `④ 삭제` 같은 삭제 항 청크가 10개 들어 있다(짧은 청크 3.18%의 전부). 삭제 조문은 빼지만 삭제 항은 빼지 않는다 | 기록만 |
| 23 | Suggestion | 테스트 전반 | `chunk.main`·`write_chunks`, `check_preservation` 실패 메시지별, FAQ 표 값, `ZONE_ALL_LOW` 첫 줄 문구 등에 직접 assert가 없다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1 — `chunk`가 조문 후보 5개와 FAQ 청크를 jsonl로 쓰고 후보별 청크 수·글자 수 중앙값·최대를 출력한다 | 판정 불가 | 후보별 청크 수·중앙값·최대는 `docs/73-chunking.md` §2에 있다. `chunk.main`을 부르는 테스트는 없다(#23) |
| 통과 2 — `chunk_eval --candidate`가 `runs/73/<후보>/results.jsonl`·`config.json`을 쓰고 `--faq`가 `runs/73/faq/`를 쓴다 | 예 | `runs/73/{article,paragraph,paragraph+head,item,item+head,faq}/`, 줄 123개씩. `test_cli_article_on_real_data_writes_123_lines` |
| 통과 3 — `chunk_report`가 `docs/73-chunking.md`를 쓰고 첫 줄이 결론이다 | 예 | 첫 줄 「고른 후보는 `article`이다 — … −0.001 (95% CI [−0.057, +0.054], p=0.9899)」. #1은 fix 뒤 고른 후보가 `article`이 아닐 때의 첫 줄 |
| 통과 4 — 두 번째 실행에서 OpenAI 호출 0회, 같은 후보 `results.jsonl`이 바이트 단위로 같다 | 예 | `--faq` 재실행 `OpenAI 호출 0회 · 새로 임베딩한 텍스트 0개`, `runs/73/faq/results.jsonl`·`self_check.json` diff 없음. 코드 리뷰 에이전트가 `item+head`도 같다고 확인 |
| 통과 5 — `query "질문"`이 조문 5개·FAQ 3개를 출력하고 exit 0 | 예 | `query "무주택 세대구성원 기준이 뭔가요?"` → 구조 `article`, 조문 5개(제46조 · 제40조 · 제42조 · 제44조 · 제35조의3), FAQ 3개(Q47 · Q412 · Q50), exit 0. 공개 `search()` 테스트는 없다(#14) |
| 통과 6 — `runs/73/`과 `docs/73-chunking.md`를 커밋한다, `data/`는 커밋하지 않는다 | 예 | `git diff --name-only main...HEAD`에 `runs/73/*`·`docs/73-chunking.md`가 있고 `data/`는 없다 |
| 통과 7 — 전체 테스트 통과, `ruff check` · `ruff format --check` 통과 | 예 | `347 passed` · `All checks passed!` · `63 files already formatted` (fix 5건 뒤) |
| 실패 징후 1 — hybrid recall@5 `article` 대비 차이의 CI 구간 | 판정 불가 | 고른 후보 `article`. 평균 차이가 가장 큰 `item+head`: −0.001, 95% CI [−0.057, +0.054], p=0.9899, 폭의 절반 0.056 (`runs/73/selected.json`). `paragraph` −0.081 [−0.152, −0.011] 낮다. 판정은 사람 몫 |
| 실패 징후 2 — `article` recall@5가 #131과 소수 셋째 자리까지 같다 | 예 | bm25 0.680 · dense 0.545 · hybrid 0.722, `docs/73-chunking.md` §8. 코드 리뷰 에이전트가 문항별 `gold_rank`·hybrid `top5`까지 같음을 확인 |
| 실패 징후 3 — 청크 보존 누락 0·중복 0 | 예 | 후보 5개 전부 누락 0·중복 0, `docs/73-chunking.md` §8 |
| 실패 징후 4 — 10자 미만 청크 비율 | 판정 불가 | `article` 0.00% · `paragraph` 3.18% · `paragraph+head` 3.18% · `item` 4.96% · `item+head` 4.96% (2~5% 구간은 목록), `docs/73-chunking.md` §8 |
| 실패 징후 5 — 자기 쌍 1위 비율, leave-self-out 상위 5개에 자기·같은 질문 쌍 0개 | 판정 불가 | bm25 0.886 · dense 0.959 · hybrid 0.902 (0.85~0.95 구간은 놓친 것 목록, 31줄), 상위 5개의 자기·같은 질문 쌍 0개 (`runs/73/faq/self_check.json`) |
| 실패 징후 6 — 붙은 단어 32쌍의 Jaccard·코사인 평균 | 판정 불가 | 토큰 Jaccard 평균 1.000, 코사인 평균 0.986, 파일 `band`는 「영향 없음」 (`runs/73/spacing.json`). Q384는 코사인 0.870 (#18) |

## 확인한 것

- 전체 테스트 `347 passed`, `ruff check`·`ruff format --check` 통과 (fix 5건 뒤 마지막 실행).
- fix 5건은 리뷰 지적 #1~#9를 고친 커밋이다. #1·#3의 새 테스트는 고치기 전 코드에서 실패하는 것을 확인했다.
- `runs/73/`의 결과 파일은 이 리뷰에서 바꾸지 않았다. `chunk_report`의 비교 결과는 `article`을 고르므로 `docs/73-chunking.md`와 `selected.json`은 그대로다.
