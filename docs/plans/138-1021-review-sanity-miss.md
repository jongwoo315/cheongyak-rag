# 138 리뷰 — PR #5

**대상:** `main...HEAD` — 16 commits, 10 files, +2559 −1
**plan:** docs/plans/138-1020-plan-sanity-miss.md

리뷰 에이전트 4개(code · tests · comments · errors)가 같은 diff를 읽었다. type-design은 새 타입이 없어 뺐다.
Critical은 없다. Important 10건 중 8건을 고쳤고 2건은 미룬다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/retrieval/miss.py:165` | `cites_number`가 점수 하나만 부분 문자열로 찾아 사실상 항상 참이다(1위 점수·`item` 코사인은 안 보고, `132.0791` 안의 `32.079`도 통과) | fix `0d40dbe` |
| 2 | Important | `docs/138-sanity-miss.md:5` | 「질문은 … 자기 조 청크 안에 글자 그대로 있다」가 `article`에서만 20/20이다. `paragraph`·`item+head`에서는 순위를 정한 청크(예: 제14조제2항)에 질문이 없는 건이 있다 | fix `88a860c` |
| 3 | Important | `docs/138-sanity-miss.md:164` | 코사인 1.000이 「첫 문장이라서」만으로 설명돼 있다. 실제 조건은 조문 첫 줄이 한 문장뿐이라 `item` 청크와 질문이 글자까지 같은 경우다 | fix `467fac3` |
| 4 | Important | `src/cheongyak_rag/retrieval/miss.py:1` | 모듈 docstring이 읽지 않는 `runs/73/selected.json`을 읽는다고 쓰고, 묶음 B 기준 run(`runs/hybrid`)을 `runs/73`이라고 적었다 | fix `4086882` |
| 5 | Important | `docs/138-sanity-miss.md:41` | plan 실패 징후 1 B가 요구한 「plan을 쓰기 전에 값을 알았다」가 리포트에 없다 | fix `357169c` |
| 6 | Important | `src/cheongyak_rag/retrieval/miss.py:457` | BM25 원인이 0건이면 검산 줄이 「최대 0.0e+00」으로 찍혀 검산한 것처럼 보이고, NaN 차이는 `>=` 비교를 통과한다 | fix `c1c691d` |
| 7 | Important | `tests/test_retrieval_miss.py:410` | `main`의 실패 징후 3·4 종료 코드 경로를 건드리는 테스트가 없다(징후 2만 있다) | fix `b9c2d04` (징후 4는 `c1c691d`의 NaN 테스트가 함께 덮는다) |
| 8 | Important | `tests/test_retrieval_miss.py:341` | 결론 문장 테스트가 구간 이름 부분 문자열만 보고, 후보 넷이 같은 값을 가진 fixture라 후보끼리 값이 바뀌어도 통과한다 | fix `db6105c` |
| 9 | Important | `src/cheongyak_rag/retrieval/miss.py:177` | `build_causes`가 다시 계산한 점수·코사인과 점검 줄의 순위가 맞는지(1위 점수 ≥ 자기 조 점수) 확인하지 않는다 | defer — plan 실패 징후에 없는 추가 게이트다. 현재 run은 네 건 모두 1위 값이 더 크다(BM25 34.426 > 32.079, dense 0.686 > 0.679 · 0.741 > 0.724 · 0.699 > 0.590) |
| 10 | Important | `src/cheongyak_rag/retrieval/miss.py:512` | 놓친 건이 0건이거나 `article` F·L 기준선이 `runs/hybrid`와 어긋나도 `main`이 0을 낸다. 징후 2가 저장된 `runs/sanity`와의 일치는 이미 잡지만 `runs/73/article`과 `runs/hybrid`의 일치는 안 잡는다 | defer — 현재 `article` F = L = 0이고 점검 run 재현이 20/20이라 지금은 어긋나지 않았다. plan 실패 징후 밖의 게이트라 이번에 안 넣는다 |
| 11 | Suggestion | `src/cheongyak_rag/retrieval/miss.py:278` | `summarize_a`가 후보 간 질문을 줄 순서로만 짝짓고 라벨 일치를 확인하지 않는다. `article`이 후보에 없으면 `KeyError` | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/retrieval/miss.py:310` | `reproduce`가 `zip(strict=False)`라 한 줄이 빠지면 뒤 줄이 전부 밀려 비교되고, 두 쪽이 모두 비면 「0개 모두 같다」가 나온다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/retrieval/miss.py:512` | `main`이 `runs/138`과 리포트를 쓴 뒤에야 종료 코드를 정한다. 징후 2가 어긋나도 다른 후보 값까지 만들어 덮어쓴다(plan은 먼저 멈추라고 했다) | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/retrieval/miss.py:55` | `law:` + path라는 청크 id 형식을 `chunk.py`에서 손으로 복사했다 | 기록만 |
| 15 | Suggestion | `docs/138-sanity-miss.md:1` | 「놓친 4건」은 BM25·dense 건만 센다. 같은 `article`의 hybrid 놓침 2건은 4에 안 들어간다 | 기록만 |
| 16 | Suggestion | `docs/138-sanity-miss.md:172` | 낱말 기여 검산은 `bm25_terms`와 `BM25.scores`가 같은 식이라는 일치 확인이지 BM25 자체의 독립 검증이 아니다 | 기록만 |
| 17 | Suggestion | `tests/test_retrieval_miss.py:65` | 실경로 fixture에서 BM25 순위가 전부 1이라 `article` 재현 테스트가 사실상 dense만 본다 | 기록만 |
| 18 | Suggestion | `tests/test_retrieval_miss.py:174` | `bm25_terms` 손계산이 기본 k1·b만 쓰고 `_terms_text`의 상위 5개 자르기는 테스트가 없다 | 기록만 |
| 19 | Suggestion | `tests/test_retrieval_miss.py:321` | 테스트 docstring이 「L도 3 미만」이라고 쓰는데 L은 3이다(구간은 F − L로 정해진다). `GAP` 주석 「이 값 이하(음수)」도 부호가 헷갈린다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/retrieval/miss.py:68` | 구간이 F − L 값 하나만 본다. F = 3, L = 3이면 6문항이 뒤바뀌어도 「차이 없음」이다(표에는 F·L이 둘 다 나온다) | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1 — `uv run python -m cheongyak_rag.retrieval.miss`가 `runs/138/sanity.jsonl`(100줄) · `golden_misses.json` · `causes.json` · 리포트를 쓰고 exit 0 | 예 | 실행 exit 0, `runs/138/sanity.jsonl` 100줄, 파일 셋과 `docs/138-sanity-miss.md` 존재 |
| 통과 기준 2 — 리포트 첫 줄은 결론 한 문장, 실패 징후 1의 두 묶음 후보별 값과 구간 | 예 | `docs/138-sanity-miss.md:1`, `tests/test_retrieval_miss.py` `test_first_line_is_one_sentence_naming_all_four_candidates` · `test_conclusion_reads_each_candidates_own_values` |
| 통과 기준 3 — 두 번째 실행에서 OpenAI 호출 0회, `runs/138/`과 리포트 바이트 동일 | 예 | 리뷰 중 세 번 다시 실행: 「OpenAI 호출 0회」, `git status --porcelain`에 `runs/138` 변경 없음 |
| 통과 기준 4 — #131 리뷰 1차 #9 defer 테스트 둘 | 예 | `tests/test_retrieval_131_defer.py` 두 테스트 통과 |
| 통과 기준 5 — `runs/138/`과 리포트 커밋, `data/` 미커밋, `runs/73`·#131 run 불변 | 예 | `git diff main --stat -- runs/73 runs/bm25 runs/dense runs/hybrid runs/sanity` 출력 0줄 |
| 통과 기준 6 — 전체 테스트 통과, `ruff check` · `ruff format --check` 통과 | 아니오 | `385 passed, 1 failed`. 실패는 `tests/test_health.py::test_health_reports_db_and_pgvector`(DB 연결 `sqlalchemy` 오류)이고 이 PR이 건드린 파일이 아니다. `ruff check` · `ruff format --check` 통과 |
| 실패 징후 1 A — 후보별 놓쳤던 4건 중 1위가 된 건수 | 판정 불가 | 값만 적는다: `paragraph` 4 · `paragraph+head` 3 · `item` 4 · `item+head` 4 · `article` 0 (`docs/138-sanity-miss.md:19-25`). 구간 해석은 사람 몫 |
| 실패 징후 1 B — 후보별 F − L | 판정 불가 | 값만 적는다: `paragraph` 6 − 18 · `paragraph+head` 4 − 12 · `item` 8 − 10 · `item+head` 6 − 7 · `article` 0 − 0 (`docs/138-sanity-miss.md:43-49`) |
| 실패 징후 2 — `article` 점검 run이 `runs/sanity`와 질문마다 같다 | 예 | `docs/138-sanity-miss.md` §4 「질문 20개 모두 … 같다」, BM25 19/20 · dense 17/20 |
| 실패 징후 3 — 숫자 없는 원인 문장 0건 | 예 | `docs/138-sanity-miss.md` §3 「0건」. 검사를 `0d40dbe`에서 강화한 뒤에도 0건 |
| 실패 징후 4 — 낱말 기여 합과 `BM25.scores` 차이 1e-9 이내 | 예 | `docs/138-sanity-miss.md` §3 「최대 0.0e+00(기준 1e-09)」. 같은 식을 쓰는 일치 확인이다(#16) |

## 검증

- 고친 뒤 `uv run pytest`: 385 passed, 1 failed(위 `test_health`). `ruff check`·`ruff format --check` 통과.
- 고친 뒤 `miss` 재실행: exit 0, 「OpenAI 호출 0회」. `runs/138/` 파일은 바뀌지 않았고 리포트 문구만 바뀌었다(#2·#3·#5 커밋에 포함).
- `test_health`는 이 세션에서 DB에 연결되지 않아 실패했다. DB에 연결되는 환경에서 한 번 더 돌려야 통과 기준 6이 닫힌다.
