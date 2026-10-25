# 78 리뷰 — PR #8

**대상:** `main...HEAD` — 21 commits, 15 files, +2405 −2 (구현 7 commits + 리뷰 반영 14 commits)
**plan:** docs/plans/78-1025-plan-asof-resolve.md

## 지적

에이전트 4개(코드·테스트·에러 처리·주석)가 낸 지적을 합쳤다. Critical은 없다. 괄호 안은 낸 에이전트와 번호다.

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/asof.py:513` | 안 정해진 공고가 4건 이상이거나 하나도 못 정해도 exit 0이다. plan 징후 1은 이 구간을 미완으로 정한다 (에러 처리 1 · 코드 3) | fix `170c50a` |
| 2 | Important | `src/cheongyak_rag/asof.py:154` | 본문 응답이 JSON 객체가 아니면(`[]`) `AttributeError`로 중단돼 이미 비교한 버전의 결과와 리포트가 사라진다 (에러 처리 5) | fix `00bf1e3` |
| 3 | Important | `src/cheongyak_rag/asof.py:326` | 징후 2의 「법령명 일치 행 수」를 받은 행 수가 아니라 테이블 행 수로 쟀다. 수집이 옛 행을 지우지 않아 목록이 128행으로 줄어도 129행 통과로 보인다 (코드 2 · 에러 처리 6) | fix `d69a52f` |
| 4 | Important | `src/cheongyak_rag/asof.py:72` | 같은 날 여러 MST 표의 「view가 고를 MST」가 view 정렬 규칙을 SQL로 다시 적은 복제본이다. 테스트가 공포일이 다른 한 쌍만 대조한다 (코드 1 · 테스트 6) | fix `a92d80d` — 복제는 남기고 동률·공포일 NULL에서 view와 같은 값을 내는지 고정했다 |
| 5 | Important | `tests/test_asof.py` | `_band_rows`·`_band_versions`·`_band_calls`·`_rerun`의 구간 문구가 어느 테스트에도 없다 (테스트 1) | fix `0be0656` |
| 6 | Important | `tests/test_asof.py` | 버전이 둘인데 하나만 어긋나는 경우가 없다. `compare`가 약속한 「앞 결과를 남긴다」가 검증되지 않는다 (테스트 2) | fix `fc5596a` |
| 7 | Important | `tests/test_asof.py` | 연결 오류 메시지에 URL(OC 포함)이 담기는 경로의 키 노출 테스트가 없다 (테스트 3) | fix `2800c77` |
| 8 | Important | `tests/test_law_versions_migration.py:21` | downgrade 뒤 assert가 실패하면 세션 공용 DB가 0002에 남아 뒤 테스트가 연쇄로 실패한다 (테스트 4) | fix `8f657be` |
| 9 | Important | `tests/test_law_versions_rule.py` | view의 `promulgation_date`·`promulgation_no` 열 값을 보는 테스트가 없다 (테스트 5) | fix `1fed514` |
| 10 | Important | `src/cheongyak_rag/asof.py:452` | 빈 키 가드 주석이 「검사가 통과한다」고 적었지만 `'' in text`는 항상 참이라 매번 걸린다 (주석 1) | fix `fd20a6a` |
| 11 | Important | `src/cheongyak_rag/asof.py:8` | 모듈 docstring의 「구간 문구는 plan 문장 그대로다」가 거짓이다. 코드가 덧붙인 문구가 있다 (주석 2). 리포트 표 머리 「해당 구간 (plan 문구)」은 생성물이라 안 건드렸다 | fix `dec10e5` |
| 12 | Important | `src/cheongyak_rag/ingest/law_versions.py:209` | 옛 행이 남아도 asof 본문 대조가 잡는다는 주석이 과장이다. 어떤 공고도 그 행을 안 고르면 안 잡힌다 (주석 3) | fix `7d39ace` |
| 13 | Important | `tests/test_law_versions_ingest.py:178` | 「같은 MST의 단계 시행은 아니다」 주석이 사실과 반대다 (주석 4) | fix `982a272` (줄 길이는 `9519622`) |
| 14 | Important | `src/cheongyak_rag/asof.py:212` | 본문 대조 키가 시행일자·공포번호뿐이라 같은 날·같은 공포번호의 다른 MST를 못 가르고, 양쪽 공포번호가 None이면 무엇이든 일치한다 (에러 처리 3) | won't-fix — plan 징후 1이 본문 대조를 「시행일자·공포번호가 `law_versions` 행과 같은가」로 정의했다. 본문 `기본정보`에 MST 필드가 없어 더 비교할 키가 없다 |
| 15 | Important | `src/cheongyak_rag/asof.py:497` | 수집 실행 요약(`runs/78/law_versions.json`)을 못 읽거나 옛 파일이어도 말없이 `None`으로 넘어가 중복 검사 없이 「129행 통과」가 나올 수 있다 (에러 처리 4) | defer — 리포트 칸에 중복 `—`·「비교할 수 없다」가 찍혀 보이지만 파일 시각 검사는 없다. 수집을 다시 돌려 요약을 갱신하는 것이 #79 착수 전 순서다 |
| 16 | Important | `runs/78/last_run.json` | 커밋된 실행의 「본문 대조 1/1」이 `calls 0`, 캐시 대조라 `eflaw`+`MST`+`efYd` 호출이 실제 API로는 한 번도 안 돌았다 (에러 처리 2) | 기록만 — 리뷰 중 임시 경로로 캐시 없이 다시 돌렸다. API 호출 1회, `source: api`, 일치, exit 0. 리포트 내용은 커밋본과 같다 |
| 17 | Suggestion | `src/cheongyak_rag/ingest/law_versions.py:97` | 전체 건수가 100의 배수면 빈 페이지를 한 번 더 부른다. `seen >= total`이면 멈추는 쪽이 정확하다 (코드 4 · 에러 처리 9) | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/asof.py:148` | 본문 파일 이름에 시행일만 있어 같은 날 MST가 여럿인 날은 본문을 하나만 둔다. 지금은 공포번호 대조가 막는다 (코드 5 · 테스트 10) | 기록만 — #79·#80에서 과거 본문을 쓸 때 이름에 공포번호를 넣는다 |
| 19 | Suggestion | `src/cheongyak_rag/asof.py:322` | 본문을 못 읽은 버전도 「불일치」로 센다. 라벨이 plan의 불일치 정의보다 넓다 (주석 6) | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/ingest/law_versions.py:90` | `totalCnt`가 `None`이거나 `law`가 `None`이면 `LawApiError`가 아닌 `TypeError`로 중단된다. `_previous`는 깨진 요약을 조용히 `None`으로 바꾼다 (에러 처리 7·8·10) | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/asof.py:231` | 안 정해진 공고 1~3건일 때 plan이 요구한 「원인」(모집공고일이 NULL인지, 가장 오래된 시행일보다 이른지)을 따로 적지 않는다 (에러 처리 11) | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/asof.py:371` | 「늘어난 행」 목록이 시행일이 2026-06-15보다 늦은 행만 보여, 이른 시행일의 새 행은 행 수만 늘고 목록이 빈다 (주석 7) | 기록만 |
| 23 | Suggestion | `src/cheongyak_rag/asof.py:41` | 「새 공고가 나오면 구간 문구가 다르다를 낸다」가 틀렸다. 새 개정이 나올 때만 달라진다 (주석 5) | 기록만 |
| 24 | Suggestion | `src/cheongyak_rag/asof.py:261` · `:421` · `:397` | 재시도 코드가 없는데 「재시도 원인」 문구, 실측값 「호출 2회」 고정 문구, 「view가 고를 MST」 표 머리가 view를 읽은 값처럼 보이는 것 (주석 8·9·10) | 기록만 |
| 25 | Suggestion | `tests/test_asof.py:179` · `tests/test_law_versions_rule.py:1` · `tests/law_version_fakes.py:3` | 테스트 주석의 사실 오류 셋: 공고 번호가 겹쳐 공고가 늘지 않는 것, 「다섯 경우」가 열 개이고 값 일부는 지어낸 값인 것, eflaw에 대해 확인 안 된 사실을 실측이라 적은 것 (주석 11·12·13) | 기록만 |
| 26 | Suggestion | `tests/test_law_versions_ingest.py:154` 외 | 약한 assert(`"129" in shown`), 상수 `duplicates: 0` 검사, 가짜 서버가 `query`·`type`을 안 보는 것, 리포트 표본·늘어난 행 절 미렌더, 깨진 캐시 문구, `to_row` 누락 필드 (테스트 7~13) | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `alembic upgrade head`가 `law_versions`와 `notice_law_versions`를 만든다. `downgrade 0002` 뒤 다시 `upgrade head`가 된다 | 예 | `tests/test_law_versions_migration.py` 3 passed |
| 2. 수집 명령이 목록을 끝까지 읽어 upsert하고 받은 행 수·페이지 수·넣은/고친 수·호출 수를 출력하고 exit 0 | 예 | `tests/test_law_versions_ingest.py` · `runs/78/law_versions.json` (received 129, pages 2) |
| 3. view가 `notices` 한 행마다 한 행을 준다. 열은 공고 PK 두 개 · `rcrit_pblanc_de` · `mst` · `effective_date` · `promulgation_date` · `promulgation_no` | 예 | `tests/test_law_versions_rule.py::test_view_has_one_row_per_notice_even_without_versions` · 열 순서는 migration 테스트 · 값은 `1fed514` |
| 4. `asof`가 view를 읽고 (MST, 시행일)마다 본문을 대조해 `runs/78/last_run.json`·`docs/78-asof.md`를 쓴다. 첫 줄은 결론 한 문장. 어긋나면 exit 1 | 예 | `docs/78-asof.md:1` · `tests/test_asof.py` 26 passed · 리뷰 중 캐시 없이 실제 API로 다시 돌려 exit 0, 1회 호출, 일치 |
| 5. 규칙 테스트가 다섯 경우(당일 · 전날 · 같은 MST 단계 시행 · 같은 날 MST 둘 · 가장 오래된 시행일보다 이른 날)를 고정한다 | 예 | `tests/test_law_versions_rule.py:55-132` |
| 6. `LAW_OC` 값은 출력·예외·리포트·커밋 어디에도 나오지 않는다 | 예 | 테스트 `test_the_key_never_shows_up_anywhere` · `test_a_report_that_would_contain_the_key_is_not_written` · `2800c77` · 커밋된 `runs/78/*.json`·`docs/78-asof.md`에서 키 0건 (에러 처리 에이전트 확인) |
| 7. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과 | 예 | `uv run pytest -q` 569 passed (리뷰 반영 뒤) · ruff 두 개 통과 |
| 실패 징후 1: 안 정해진 공고 0건 · 불일치 0건 → 통과. 84건 전부 MST 286965 | 값만 적는다 | `docs/78-asof.md:11` — 안 정해진 공고 0건 · 불일치 0건 · 고른 버전 MST 286965 시행 2026-06-15 |
| 실패 징후 2: 법령명 일치 129행 → 통과, (MST, 시행일) 중복 0 | 값만 적는다 | `docs/78-asof.md:12` — 129행 · 중복 0건. 판정 기준을 받은 행 수로 바꿨다 (`d69a52f`) |
| 실패 징후 3: 같은 날 여러 MST는 기록만 | 예 | `docs/78-asof.md:32-40` — 7일 |
| 실패 징후 4: 호출 5 이하 정상 | 예 | `docs/78-asof.md:14` — 2회 (캐시 대조 0). 캐시 없이 다시 돌렸을 때 asof 1회 + 수집 2 = 3회 |
| 실패 징후 5: 재실행 뒤 행 수와 PK 집합이 그대로, 새로 들어간 행 0 | 예 | `docs/78-asof.md:15` · `tests/test_law_versions_ingest.py:157-170` |
| 실패 징후 6: 가짜 OC가 출력·예외·리포트에 0회 | 예 | 위 6번 기준과 같은 테스트 |

## 확인

- 리뷰 반영 뒤 `uv run pytest -q`: 569 passed (마지막 테스트 추가 전). 이후 `tests/test_asof.py` 26 passed, `ruff check` · `ruff format --check` 통과
- 리뷰 중 임시 경로(`--raw-dir`·`--run`·`--out`)로 asof를 실제 API에 한 번 돌렸다. 커밋된 `docs/78-asof.md`·`runs/78/last_run.json`·`data/raw`는 건드리지 않았다. 리포트 내용(실행 시각 제외)은 커밋본과 같다
