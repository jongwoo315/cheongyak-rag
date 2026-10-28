# 79 리뷰 — PR #11

**대상:** `main...HEAD` — 19 commits, 11 files, +4055 −10 (리뷰 중 고친 커밋 12개 포함)
**plan:** docs/plans/79-1029-plan-axis-search.md

리뷰는 `pr-review-toolkit`의 에이전트 5개(code-reviewer · pr-test-analyzer · silent-failure-hunter · comment-analyzer · type-design-analyzer)로 했다. Critical은 없다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/retrieval/index_db.py:163` | `law_mst`로 거른 `nearest`가 HNSW가 고른 후보 안에서만 남는다. 조문 200행(MST 둘)으로 재현하면 k=100에 51개만 돌아왔다. 지금은 MST가 하나고 전수 스캔이라 숫자에 안 드러난다 | fix `8e758ba` — 거를 때 `hnsw.iterative_scan = strict_order`를 켜고 같은 재현을 테스트로 넣었다 |
| 2 | Important | `src/cheongyak_rag/retrieval/axes.py:255` | `_doc_order`는 `article` 청킹에서만 `query.Index`의 문서 순서와 같다. `paragraph`·`item` 후보에서는 `제14조의2`가 `제14조제1항`보다 앞선다(BM25 동점 순서가 달라진다). 현재 후보(`article`)는 조문 88개·FAQ 480개 전부 일치를 확인했다 | defer — 청킹 후보를 바꾸는 일은 #139 범위다. 후보를 바꿀 때 `chunks`에 적재 순번 칸을 두고 그 순서로 읽는다 |
| 3 | Important | `src/cheongyak_rag/retrieval/axes_report.py:244` | 징후 4의 `0회`는 임베딩 캐시가 이미 차서 나온 값인데 표에는 그 말이 없다 | fix `504135d` — 서로 다른 하위 질의 수를 같은 칸에 적고 캐시에 있는 질의는 세지 않는다고 밝혔다 |
| 4 | Important | `src/cheongyak_rag/retrieval/axes.py:380` | `chunks`가 비어 검색 결과가 하나도 없어도 CLI가 빈 결과를 찍고 exit 0으로 끝난다 | fix `63582b6` — stderr에 이유를 쓰고 exit 2 |
| 5 | Important | `src/cheongyak_rag/retrieval/axes_report.py:614` | 직전 실행 기록 JSON이 깨져 있으면 고치기 전·후 표에만 쓰는 값 때문에 측정 전체가 중단된다 | fix `93b8da6` — 읽지 못하면 stderr 경고 후 직전 기록 없이 계속한다 |
| 6 | Important | `src/cheongyak_rag/retrieval/axes_report.py:622` | `main`이 잡지 않는 예외(OpenAI 오류, API 키 없음)는 traceback과 함께 exit 1로 끝나서 「징후 1 미완」의 exit 1과 겹친다 | defer — 자동으로 exit 코드를 읽는 곳이 아직 없다. 읽는 쪽이 생기면(#84 이후) 알 수 없는 예외에 별도 코드를 준다 |
| 7 | Important | `docs/79-axis-search.md:26` | 리포트가 `special_type` 기대 조를 「16개」, 「의N 포함」이라고 적었는데 코드는 15개이고 의N은 제35조의2·제35조의3 둘뿐이다(제47조의3은 특별공급 조가 아니라 뺐다) | fix `1a64edd` · `6727df3` — 문구를 15개로 고쳤다 |
| 8 | Important | `docs/79-axis-search.md:28` | 징후 1·3의 `통과`는 dense가 전수 스캔이고 MST가 하나라 필터가 행을 거르지 않은 상태에서 잰 값인데 리포트에 그 말이 없다 | fix `b328941` — 읽는 법에 적었다 |
| 9 | Important | `tests/test_retrieval_axes_report.py:152` | 예외 수집 경로(`errors`) 세 곳을 타는 테스트가 없다 | fix `27ccb7e` — 깨진 공고 하나가 `errors`에 모이고 나머지 공고는 끝까지 도는지 확인한다 |
| 10 | Important | `tests/test_retrieval_axes.py:346` | dense가 비거나 일부만 돌려주는 경우 `_law_top`이 조문 k개를 채우는지 확인하는 테스트가 없다 | fix `3717b39` |
| 11 | Important | `tests/test_retrieval_axes_report.py:152` | 적게 돌아온 원인 분류 4갈래 중 「행이 모자란다」만 테스트된다. 이 밖에 같은 조에 청크가 여럿일 때 `best_path` 동등성, `axes.main`의 DB 오류 exit 2, `--pblanc-no` 필터, null·빈 문자열 입력, `FakeEmbedder.api_calls`가 항상 0인 점이 비어 있다 | defer — 동작이 틀린 것이 아니라 확인이 빠진 것이다. #80이 이 경로를 쓰기 시작할 때 같이 채운다 |
| 12 | Important | `src/cheongyak_rag/retrieval/axes.py:252` | `Cache`는 한 번 읽은 스냅샷이고 키에 DB가 없다. 재색인이 도는 동안 측정하거나 다른 DB 두 개에 같은 dict를 넘기면 `KeyError`가 나거나 앞 DB의 청크가 쓰인다 | push-back — 캐시는 `search()` 한 번 또는 `--report` 한 번 동안만 만들어 쓴다. 문서에 그 수명만 적었다(`35e406e`) |
| 13 | Suggestion | `src/cheongyak_rag/retrieval/axes_report.py:220` | `sample_ok`의 앞 절(`len(samples) == len(kinds)`)은 항상 참이다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/retrieval/axes_report.py:69` | `zone_off`가 공고 수만으로 데이터가 바뀌었는지 판정한다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:290` | `rrf`의 k=60이 `query.Index` 쪽 `RRF_K`와 따로 적혀 있다(지금은 둘 다 60) | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:138` | `load_facts`가 `tuple[str, str, Facts]`가 아닌 `tuple`을 돌려준다. frozen dataclass의 `list`·`dict` 칸, `Facts` 부분 dict 입력, `search`가 `plans`와 공고 번호를 함께 받는 점, 비숫자 raw 값의 `::int` 오류 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/retrieval/axes_report.py:146` | MST가 둘 이상이면 징후 3은 첫 공고만 견주고 징후 5의 워밍업은 첫 MST만 미리 만든다. 지금은 MST가 하나다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/retrieval/axes_report.py:345` | 첫 줄의 「적게 돌아온 축 N개」는 실제로 (공고, 축) 쌍의 수다. 특별공급 세대수 합은 양수인데 유형별 합이 0인 공고 6건(신혼희망타운 등)의 이유 설명도 실제와 다르다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `nearest()`가 `law_mst` 조건을 받는다. 안 주면 기존과 같다 | 예 | `tests/test_retrieval_index_db.py` 27개 통과, `8e758ba`가 필터 경로만 바꿈 |
| 2. 축 7개가 설계 §2 표대로 있고 `plan()`이 켜짐·이유·하위 질의를 돌려준다 | 예 | `src/cheongyak_rag/retrieval/axes.py:78-107`, `tests/test_retrieval_axes.py` 30개 통과. 설계와 다른 곳(`householder` 켜는 조건)은 리포트 §5에 적혀 있다 |
| 3. `search()`가 켜진 축마다 조문 5개·FAQ 3개를 돌려준다 | 예 | 리포트 징후 1: 적게 돌아온 (공고, 축) 0개 |
| 4. CLI가 축 목록과 축마다 top-k를 출력한다 | 예 | `test_cli_prints_all_axis_names_and_hit_lines` 통과 |
| 5. `--report`가 84건을 돌려 징후 1~6을 재고 징후 1이 미완이면 exit 1 | 예 | `runs/79/last_run.json`, `test_report_exits_1_when_axis_list_differs` 통과 |
| 6. 표본: 켜진 축 목록 종류마다 공고 하나, 축마다 top-k 전체 | 예 | 리포트 §3 표본 6건 ↔ 종류 6가지 |
| 7. `uv run pytest -q` · `ruff check` · `ruff format --check` | 예 | `835 passed`, `All checks passed!`, `134 files already formatted` |
| 징후 1: 예외 0 · MST 못 정함 0 · 목록 다름 0 · 적게 돌아옴 0 · 표본 종류마다 1건 | 예(측정값) | 예외 0건 · 목록 다름 0건 · 적게 돌아온 0개 · 표본 6/6. dense는 전수 스캔이었다(#8) |
| 징후 2: 기대 조가 든 축 6~7개 | 판정 불가 | 값만 적는다: 7개 중 6개(`special_type` 8/9). 기대 조는 구현 전에 조 제목만 보고 정한 것이고 `special_type`의 기대 조가 15개라 들기 쉽다 |
| 징후 3: DB 경로와 메모리 검색이 같은 하위 질의 비율 0.98 이상 | 판정 불가 | 값만 적는다: 29/29. MST가 하나이고 dense가 전수 스캔이었다 |
| 징후 4: 임베딩 API 호출 50회 이하 | 판정 불가 | 값만 적는다: 0회(서로 다른 하위 질의 29개, 캐시가 찬 상태). 빈 캐시에서의 호출 수는 재지 않았다 |
| 징후 5: 중앙값 2초 이하 | 예 | 중앙값 0.078초 · 최댓값 0.158초 |
| 징후 6: 꺼진 축 수가 착수 실측과 같다 | 예 | 특별공급 축 둘이 꺼진 공고 5건 · 재당첨제한 축이 꺼진 공고 48건 |

## 확인

- 리뷰 중 고친 뒤 `uv run pytest -q`: 835 passed. `uv run ruff check` 통과, `uv run ruff format --check` 통과
- 실제 DB(5433)로 `--report`를 다시 돌려 리포트를 새로 만들었다(`43ea751`). 징후 1~6은 이전과 같은 구간이다
- 리뷰 에이전트가 직접 돌려 확인한 것: 1번의 재현(200행에서 k=100이 51개), 2번의 정렬 비교(`article`은 같고 `paragraph`·`item`은 다름), 리포트 숫자 일치(요약 줄 · 표 · JSON)
