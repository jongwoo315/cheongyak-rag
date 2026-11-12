# #138 리뷰 — PR #22

**대상:** `main...HEAD` — 14 commits(리뷰 파일 커밋 전), 12 files, +1913 −14
**plan:** docs/plans/138-1112-plan-search-text.md

리뷰는 `pr-review-toolkit:review-pr`의 하위 에이전트 네 개(code-reviewer · pr-test-analyzer · silent-failure-hunter · comment-analyzer)가 했다. type-design-analyzer와 code-simplifier는 돌리지 않았다(새 타입이 `Facts`·`AxisPlan`의 칸 하나뿐이다). 단어장 검사는 comment-analyzer가 `docs/concepts.md` `## 용어` 절의 「쓰지 말 말」을 diff 전체에서 찾았다(#13).

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `docs/concepts.md:8` | 이번 PR이 `axes.py` 위쪽에 23줄을 넣어 `AXES`가 78줄에서 101줄로 밀렸는데 개념 표의 줄 번호가 옛 값이다 | fix `8c7e880` |
| 2 | Important | `tests/test_eval_search_text_report.py:219` | `assert "통과" in md`는 범례에 「통과」가 항상 찍혀서 어떤 구간이어도 통과한다 | fix `840ccc9` |
| 3 | Important | `tests/test_eval_search_text_report.py:196` | metrics 고정값이 모든 지표를 평평한 `{value,num,den}`으로 두어서, 실제 `metrics.json`처럼 판정 정확도가 `total` 아래에 있는 경로(`search_text_report.py:200`)가 실행되지 않는다 | fix `cf49510` |
| 4 | Important | `tests/test_eval_search_text_report.py:211` | `render`가 조건부로 내는 표(못 든 줄·샌 줄·어긋난 줄·치명오답, `unmatched_system_queries` 줄, 비용 줄)가 테스트에서 한 번도 안 나온다 | fix `291aedf` |
| 5 | Important | `src/cheongyak_rag/eval/search_text_report.py:116` | 주택 구분이 비었거나 공고를 못 찾으면 `house.get`이 None을 돌려 그 줄을 세지 않는다. 그러면 실패 징후 3이 「어긋남 0 → 정상」으로 찍힌다(못 센 것이 통과로 읽힌다) | fix `1c2f945` |
| 6 | Important | `tests/test_eval_search_text_report.py:167-186` | `run_search_only` · `_search_only` · `house_by_id`에 테스트가 없다 | defer — 이 셋은 DB와 임베딩 호출이 필요해 `pg_engine` 고정값과 가짜 임베더를 새로 짜야 한다. `--search-only`는 plan Task 3의 일회성 사전 확인이었고 값은 `runs/138`의 실제 실행(통과 기준 4)으로 다시 쟀다. `house_by_id`는 이번 리포트 생성에서 실제 DB로 실행됐다(`1c2f945` 때 재생성, 주택 구분을 못 읽은 공고 0개) |
| 7 | Important | `src/cheongyak_rag/eval/search_text_report.py:102,122,135` | 실패 징후 2·3·4는 분모가 0이어도 「정상」을 낸다(실패 징후 1만 분모 0을 미완으로 처리) | defer — 실제 입력은 524줄·50문항이고 실패 징후 4는 분모(91)를 같이 찍는다. 빈 입력을 막으려면 세 징후에 분모 칸을 더하는 리포트 형식 변경이라 이 PR 범위 밖이다 |
| 8 | Important | `src/cheongyak_rag/eval/search_text_report.py:60-99` | #76과 이번 실행의 하위 질의 줄 집합이 같은지 확인하지 않는다. 이번 실행이 줄어도 `jw`의 분모만 줄어 통과가 될 수 있다 | push-back — 실패 징후 2 `leak()`는 #76에 있고 이번에 빠진 줄을 「샌 것」으로 센다. ①·②는 표가 #76의 분자·분모와 나란히 찍혀 분모가 줄면 바로 보인다. 리뷰 세션이 두 파일의 줄 키(공고·축·하위 질의)를 비교해 524개씩 정확히 같음을 확인했다 |
| 9 | Important | `src/cheongyak_rag/eval/search_text_report.py:404-406` | `except (OSError, ValueError, KeyError)`가 `render`까지 감싸서, 리포트 코드의 KeyError가 「읽기 실패」로 찍히고 traceback이 안 남는다 | defer — 일회성 CLI이고 지금 입력으로는 안 난다. 읽기 호출만 감싸도록 좁히는 일은 다음에 이 파일을 고칠 때 같이 한다 |
| 10 | Important | `src/cheongyak_rag/eval/search_text_report.py:212-352` | `metrics.json`의 무결성 칸(`search_incomplete` · `no_law_results` · `item_failures` · `verdict_errors` · `unmatched_labels`)을 이 리포트가 안 찍는다 | push-back — 같은 값이 `docs/138-eval.md:8,26,68`에 찍혀 있고(못 맞춘 라벨 0 · 판정 실패 0) 이 PR이 두 리포트를 같이 낸다. 이 리포트는 검색 문장 한 가지만 본다 |
| 11 | Important | `docs/138-eval.md:1` | `eval/report.py:211`이 제목과 jw 기준을 #76 것으로 고정해 둬서, #138 실행 리포트가 「#76 eval harness 리포트」라는 제목과 #76 기준을 달고 있다 | defer — `eval/report.py`는 plan이 고치지 않기로 한 harness 쪽이다(통과 기준 4: 명령 그대로 만든다). 이 파일을 다시 만들면 제목이 되돌아온다. 읽는 쪽은 `docs/138-search-text.md`부터 보면 된다 |
| 12 | Suggestion | `src/cheongyak_rag/eval/search_text_report.py:247-265` | plan은 jw 기준이 「다시 잰다」일 때 놓친 하위 질의를 주택 구분과 정답 근거 조문별로 나눈 표를 요구하는데, 코드는 줄을 하나씩 나열한다 | defer — 이번 결과가 통과라 이 표가 안 쓰인다. 「다시 잰다」가 나오는 후속 측정에서 만든다 |
| 13 | Suggestion | `docs/plans/138-1112-design-search-text.md:1,19,52` | 단어장 「쓰지 말 말」인 「정답 조문」이 제목과 표 머리 두 곳에 있다(jw 기준을 그대로 인용한 줄은 원문이라 뺐다) | fix `1640bcd` |
| 14 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:353,364-366` | 같은 하위 질의의 `search_text(...)`를 임베딩 목록을 만들 때와 반복문 안에서 두 번 계산하고, 줄 나눔 뒤 주석이 닫는 괄호 뒤에 붙었다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:61-62,332-345` | 주석이 「일 때만 아래 표의 문장」이라 모든 하위 질의에 걸리는 듯 읽히고(표는 청약통장·기관추천 둘뿐), `search()` docstring이 BM25·임베딩이 검색 문장을 받는다는 것을 안 적는다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/eval/search_text_report.py:109-123` | plan은 실패 징후 3을 「공고 수」로 세라는데 코드는 하위 질의 수를 센다. 공고마다 청약통장 하위 질의가 하나라 지금은 같다 | 기록만 |
| 17 | Suggestion | `tests/test_retrieval_axes.py:389-455` | 기관추천 BM25 경로·주택 구분 `03`이 BM25 테스트에 없고, `SEARCH_TEXTS[1][2]` 같은 위치 색인과 for 루프가 실패 위치를 흐린다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:79-81` | `search_text`가 주택 구분이 비었거나 표에 없을 때 조용히 하위 질의 문장을 쓴다. 로그도 리포트도 이 경우를 남기지 않는다(리포트는 `1c2f945`로 공고 수를 찍는다) | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/eval/search_text_report.py:41-46,81-87,142-152` | 기관추천 줄을 질의 문장 완전 일치로 가려내 다른 문장은 분모에서 조용히 빠지고, `leak`이 중복 키를 덮어쓰며, `--search-only`가 못 찾은 줄과 빈 결과를 둘 다 빈 목록으로 낸다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/eval/search_text_report.py:169-177,394-399` | 리포트를 만들 때 `runs/`만이 아니라 실제 DB(`notices`)가 떠 있어야 한다 | 기록만 |
| 21 | Suggestion | `docs/concepts.md:154`, `docs/138-search-text.md:3,22`, `search_text_report.py:7,222-223` | 「`_SEARCH_TEXTS`의 두 번째 열」(dict의 키 튜플 두 번째 값), 「이 파일의 코드가 센」(이 파일을 쓰는 코드), 정의 없는 「짝」, 실패 징후 1을 번호 없이 「jw 기준」으로 쓴 것, `--search-only`가 임베딩 캐시에 쓴다는 것이 빠진 설명 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1: 검색 문장이 설계 §3 표의 네 문장 그대로이고, 주택 구분이 `01`·`03`이 아니거나 비면 하위 질의 문장을 그대로 쓴다. 단위 테스트가 네 경우와 바뀌지 않는 경우를 고정한다 | 예 | 설계 §3 표 네 칸을 파싱해 `axes.py:65` `_SEARCH_TEXTS` 값과 비교해 4/4 같음(code-reviewer). 테스트 `tests/test_retrieval_axes.py:196-219`(네 문장 · `02` · 빈 값 · `None` · 다른 하위 질의 7개) |
| 통과 2: `AxisPlan.queries`·`QueryHits.query`는 하위 질의 문장 그대로이고 골든셋·`aggregate.py`·`eval/run.py`는 안 고친다. `unmatched_system_queries`가 #76과 같다 | 예 | `axes.py:375` `QueryHits(q, …)`. 세 파일 모두 `main...HEAD`에 없음. `docs/138-search-text.md`: #76 0, 이번 0. 테스트 `tests/test_retrieval_axes.py:409-429` |
| 통과 3: 검색 문장을 조문·FAQ 검색 둘 다에 쓴다(임베딩 한 번) | 예 | `axes.py:353`(임베딩 목록 한 번), `:364-374`(dense · `_law_top` · `_faq_top`이 `text`). 테스트 `tests/test_retrieval_axes.py:443-455` |
| 통과 4: harness를 `runs/138`로 돌려 `docs/138-eval.md`를 만들었고 `runs/76`·`docs/76-eval.md`는 그대로다 | 예 | `runs/138/run.jsonl` 524줄 · `metrics.json`, `docs/138-eval.md`. `runs/76/`·`docs/76-eval.md`는 `main...HEAD`에 없음 |
| 통과 5: `docs/138-search-text.md`에 jw 기준 측정값·구간, 실패 징후 2~4의 측정값·구간, 지표 7개 #76 대비 전후 표가 있다 | 예 | `docs/138-search-text.md`: jw 기준 50/50 · 42/42(#76 0/50 · 0/42), 실패 징후 2 0개 · 3 0개 · 4 2/91(#76 2/91), 지표 7개 표. comment-analyzer가 `runs/76`·`runs/138`을 다시 세어 jw 기준 · 실패 징후 2 · 4와 지표 7개의 분자·분모가 문서와 같음을 확인(실패 징후 3은 DB가 필요해 이 리뷰 세션이 `1c2f945` 때 리포트를 다시 만들며 0개를 확인) |
| 실패 징후 1(jw 기준): ①·② 모두 전부 들었으면 통과 | 판정 불가 | 값만 적는다: ① 청약통장 50/50, ② 기관추천 42/42, #76은 0/50 · 0/42. 문서는 구간을 **통과**로 적었고 판정은 사람 몫 |
| 실패 징후 2~4 | 판정 불가 | 값만 적는다: 다른 축으로 샌 하위 질의 0개(정상 0) · 주택 구분과 어긋난 정답 근거 조문 0개(정상 0, 주택 구분을 못 읽은 공고 0개) · 치명오답 2/91(정상 2 이하, #76 2/91) |
| Done: `docs/decisions.md`는 건드리지 않는다 | 예 | `main...HEAD`의 `docs/decisions.md` +1행은 Kickoff 커밋 `20dec04`에서 들어간 기준 칸 행이다. 루프의 커밋에는 없음 |
| Done: `docs/concepts.md` 개념 표 「주택 구분」을 더했고 `## 용어` 표는 루프가 안 건드린다 | 예 | `docs/concepts.md` 「주택 구분 2개」 절 추가. `## 용어` 표의 두 행(검색 문장 · 주택 구분)은 Kickoff 커밋 `20dec04`에서 들어간 것 |
| Pre-PR 3: 전체 테스트 · ruff | 예 | 리뷰 시작 시 `uv run pytest -q` 1298 passed · `ruff check` · `ruff format --check` 통과(아래 fix 전). fix 뒤 값은 맨 아래 |

## 단어장 검사

- 「쓰지 말 말」 칸의 말을 diff의 코드·주석·docstring·문서에서 찾았다. 나온 곳은 #13(설계 문서 세 곳)뿐이다
- jw 기준을 글자 그대로 인용한 곳(`docs/138-search-text.md:7`, `docs/decisions.md:30`, plan 38줄, `search_text_report.py:31`)은 원문이라 바꾸지 않았다

## 테스트

- fix 뒤 `uv run pytest -q` 1300 passed(리뷰 전 1298) · `uv run ruff check` 통과 · `uv run ruff format --check` 통과
- `docs/138-search-text.md`를 `uv run python -m cheongyak_rag.eval.search_text_report`로 다시 만들었다(실제 DB 읽기만). 달라진 곳은 `1c2f945`가 더한 한 줄뿐이다
