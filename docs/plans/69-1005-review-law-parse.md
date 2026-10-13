# 69 리뷰 — PR #2

**대상:** `main...HEAD` — 22 commits (구현 8 — 마지막 하나는 루프의 자체 리뷰 반영 — 과 이 리뷰의 처리 14, 이 리뷰 파일 제외), 11 files, +2528 −0
**plan:** docs/plans/69-1005-plan-law-parse.md

리뷰는 `pr-review-toolkit:review-pr` 에이전트 5개(code · tests · errors · comments · types)로 했다.
에이전트가 낸 주장 중 아래는 실제 코드와 데이터로 다시 확인했다: 항 단위 `amendments`·`mst`를 바꿔도 `check.ok`가 True,
FAQ 줄이 리스트면 `TypeError`, 별표구분이 `별지`면 별표·서식 개수 합이 제목 수와 안 맞음.
호가 다른 항 아래로 옮겨진 경우, 빈 응답, `TypeError`, 캐시 메시지는 고치기 전에 실패하는 테스트로 재현했다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/ingest/law_report.py:188` | 항·호·목 번호를 조문 안에서 일렬로 펼쳐 비교해, 호가 같은 조문의 다른 항 아래로 옮겨져도 `check.ok`가 True였다. design의 「계층을 잃지 않는다」를 대조로 못 보였다 | fix `c69d8c7` |
| 2 | Important | `src/cheongyak_rag/ingest/law.py:323` | `cached = raw.exists()`를 `fetch_law` 호출 전에 정해, `법령키`가 달라 본문을 다시 받아도 「본문: 캐시 사용」이라고 찍었다. plan Task 5가 이 문구로 다운로드 여부를 본다 | fix `d02dd23` |
| 3 | Important | `src/cheongyak_rag/ingest/law_report.py:36` | `조문단위: []`인 응답이 법령명 검사를 통과하고 개수가 0 == 0으로 맞아 `ok`가 되어 빈 JSONL을 썼다 | fix `030dfc0` |
| 4 | Important | `src/cheongyak_rag/ingest/law.py:353` | FAQ 대조 오류 격리가 어긋났다. `TypeError`는 안 잡혀 JSONL을 쓴 뒤 리포트 없이 죽었고, 빈 줄 하나로 FAQ 전체를 건너뛰었고, 깨진 파일인데 리포트는 「FAQ JSONL이 없어」라고 했다 | fix `988d2d2` |
| 5 | Important | `src/cheongyak_rag/ingest/law_report.py:206` | `article_no`·`branch_no`·`article_effective_date`·`law_id`·`effective_date`와 항 단위 `amendments`를 원본과 맞대지 않았다. 바꿔도 `ok`였고, 항 단위 값은 조문 합집합에 묻혀 보이지 않았다 | fix `bfbfaf1` |
| 6 | Important | `src/cheongyak_rag/ingest/law.py:69` | 검색 응답에 `공포번호`가 없으면 `version_key=None`이 되어 캐시 판본 확인이 경고 없이 꺼졌다 | fix `21a7273` |
| 7 | Important | `src/cheongyak_rag/ingest/law.py:168` | `_D` 주석이 부칙을 `2024. 12. 18.` 형식이라 했다. 부칙 태그는 공백 없는 형식이고(0건), 이 파일은 별표·부칙을 파싱하지도 않는다 | fix `afa34bd` |
| 8 | Important | `src/cheongyak_rag/ingest/law.py:163` | `Article.text` 주석이 「항이 있으면 머리만 든다」인데 항이 dict로 오는 14개 조문은 도입 문장과 `<개정 …>` 태그까지 든다. 「그대로」도 줄 공백을 떼므로 틀렸다 | fix `f85e655` |
| 9 | Important | `src/cheongyak_rag/ingest/law.py:357` | 본문에 `법령일련번호`가 없어 `mst`는 검색 응답 값을 그대로 찍는다. 대조할 근거가 없다 | won't-fix — 원본에 값이 없어 대조 불가. 캐시가 낡은 경우는 지적 2·6으로 드러나게 했다 |
| 10 | Important | `tests/test_law_report.py` | 호·목·항 번호, 제목, 절만 틀린 경우의 테스트가 없어 해당 대조를 지워도 통과했다 (변이 실험) | fix `961d66e` |
| 11 | Important | `tests/test_law_cli.py:53` | 성공 시 이전 JSONL을 새 내용으로 바꾸는 테스트가 없어 `and not out.exists()`로 바꿔도 통과했다 | fix `fd054f0` |
| 12 | Important | `tests/test_law_cli.py:79` | 빈 `LAW_OC`를 `oc=""`로만 시험했다. 실사용 경로인 `settings.law_oc == ""`는 안 탔다 | fix `fce672b` |
| 13 | Important | `tests/test_law_parse.py` | 호·목에만 붙은 개정 날짜가 조문 `amendments`에 합쳐지는 테스트가 없다. FAQ (b) 판정의 입력이다 | fix `ddc1be9` |
| 14 | Important | `tests/test_law_report.py` | 리포트의 `일치`/`불일치`, 기준값 비교, FAQ (b) 줄을 확인하지 않았고, 별표·서식 개수 테스트는 둘이 같은 값(2, 2)이라 바뀌어도 통과했다 | fix `7a04017` |
| 15 | Important | `tests/test_law_report.py` | 조문을 통째로 빠뜨리거나 두 번 넣은 출력의 테스트가 없다 (동작은 맞았다) | fix `ed49aa4` |
| 16 | Important | `tests/test_law_cli.py:143` | 깨진 FAQ 테스트는 빈 줄에서 먼저 `ValueError`가 나 `KeyError` 경로를 안 탔고, `"FAQ" in out`은 항상 참이었다 | fix `988d2d2` |
| 17 | Suggestion | `src/cheongyak_rag/ingest/law.py:216,255` · `law_report.py:76` | 텍스트 키의 값이 str·list가 아닌 모양(dict 등)이면 파서와 대조 코드가 둘 다 조용히 버려 일치로 나온다. 실데이터에는 없다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/ingest/law.py:63` | 검색 응답에 `시행일자`·`법령일련번호`·`법령ID`가 없으면 `KeyError` traceback으로 끝나 안내가 없다. `parse_articles`의 `ValueError`·`KeyError`도 같다. 현행이 여럿이어도 첫 건만 고른다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/ingest/law.py:64` · `law_report.py:333` | 날짜 형식 검증이 없다. `cutoff = max(as_of)`와 `d > cutoff`는 ISO 문자열 비교에 기댄다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/ingest/law.py:346` | 검증 실패 때 「쓰지 않았다」만 찍고 같은 이름의 이전 파일이 남아 있다는 말이 없다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/ingest/law.py:203` | 제10조 본문에 수식 이미지 `<img src="http://www.law.go.kr/flDownload.do?…">`가 그대로 들어 있다. 대조는 원문과 같아 통과한다 | defer — #73 청킹에서 정한다. 이번 범위는 계층 보존까지다 |
| 22 | Suggestion | `src/cheongyak_rag/ingest/law.py:260` | 장·절 제목에 `<신설 2021.11.16>`이 그대로 남아 `chapter`·`section` 값에 섞인다 | defer — #73이 이 값을 메타데이터로 쓸 때 정한다 |
| 23 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:274` | `Appendix`의 별표·서식 개수 합이 제목 수와 같음을 강제하지 않는다. `별표번호`가 정수가 아니면 `ValueError`로 리포트만 사라진다. 조문 없는 장은 `ok=False`만 나오고 원인이 안 보인다 | 기록만 |
| 24 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:326` | `제4조부터 제6조까지` 범위 인용은 5조를 못 세고 별표·부칙 인용은 세지 않는다. 빈 FAQ 파일은 「0쌍」을 경고 없이 낸다 | 기록만 |
| 25 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:428` | 「다른 법령 조문이 섞여 있다」는 (a)에만 달려 있는데 (b)도 같은 이유로 부풀 수 있다. (a)에는 삭제된 조도 들어간다 | 기록만 |
| 26 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:3` | 주석·문구 정확도: 「재귀로 훑는다」는 텍스트·개수만 맞고 소속·번호는 고정 경로로 읽는다. `LawApiError`의 「재시도로 풀리지 않는다」는 연결 오류에 안 맞는다. `_text` 독스트링은 `목내용`만 중첩이라는 말이 없다. 소속·속성 대조 헤더 문구가 이번에 늘어난 항목(식별 필드·항 개정)을 안 적는다. 테스트 섹션 제목의 「리뷰 지적:」과 plan 참조는 머지 뒤 낡는다 | 기록만 |
| 27 | Suggestion | `src/cheongyak_rag/ingest/law.py:156` | `label`이 `article_no`·`branch_no`에서 파생되는데 별도 필드로 저장한다. 지금은 `check`가 셋을 모두 대조해 어긋나지 않는다 | 기록만 |
| 28 | Suggestion | `tests/test_law_fetch.py` · `tests/test_law_cli.py` | 변이 실험에서 살아남은 것: `MST`·`OC` 쿼리 전달 미검증, `.strip()` 제거, HTTP 500·`result` 본문의 OC 마스킹, 캐시 파일의 법령명 오류, FAQ `max→min`, 삭제된 가지 조문 정규식, `test_fetch_..._and_query`가 `query`를 안 봄, 소스 문자열 grep 방식의 독립성 검사, 실제 90조문 응답으로 파서·대조 날짜 정규식이 갈라지는지 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. `python -m cheongyak_rag.ingest.law`가 `.env`의 `LAW_OC`로 검색·본문 두 호출을 하고 exit 0, 캐시 JSON과 JSONL을 쓴다 | 예 | 리뷰 후 두 번 실행 모두 `exit 0`, `90조문 → data/processed/law-008243-20260615.jsonl`, `data/raw/law-008243-20260615.json` 존재. 이 세션 두 번은 검색 호출만 했고 본문은 캐시를 썼다 |
| 통과 2. `LAW_OC`가 비면 `OC=test`로 대신하지 않고 exit 1, 원인 문구 | 예 | `tests/test_law_cli.py::test_empty_oc_exits_1_with_cause_and_calls_nothing`, 실사용 경로는 `test_empty_settings_law_oc_exits_1_…`(`fce672b`) |
| 통과 3. 대조 리포트가 실행 끝에 출력된다 | 예 | 실행 출력 `== 법령 수집 리포트 ==` |
| 통과 4. 현행은 검색 응답에서 고른다. MST `286965`를 코드에 박지 않는다 | 예 | `grep -rn 286965 src` 0건, `search_current`의 `현행연혁코드 == 현행` 필터 |
| 통과 5. 캐시가 있으면 본문을 다시 받지 않고, 검색은 매번 한다 | 예 | `test_second_run_searches_again_but_does_not_download_body_again` (`{"search": 2, "service": 1}`). 판본이 다를 때 메시지가 거짓이던 것은 지적 2 |
| 통과 6. 전체 테스트, `ruff check` · `ruff format --check` | 예 | `147 passed` (리뷰 처리 후, 처음 118), `All checks passed!`, `30 files already formatted` |
| 실패 1. 누락·중복 0, 개수(90·20·304·504·169) 일치 → 통과 / 1~5 표 / 6 이상 재설계 | 값만 | 누락 0 · 중복 0 · 바뀐 것 0, 소속 어긋남 0 · 속성 어긋남 0, 개수 5개 모두 원본 → 출력 일치, 원본 1073개 → 출력 1073개. 이번 리뷰에서 대조 항목이 늘었다(지적 1·5)는 점을 같이 적는다 |
| 실패 2. `LAW_OC`로 두 호출 HTTP 200, `법령명_한글 == 주택공급에 관한 규칙` | 판정 불가 | 이 세션에서 검색 호출은 두 번 모두 성공했다. 본문 호출은 캐시를 써 다시 부르지 않았다. 캐시 파일의 `법령명_한글`은 `fetch_law`가 쓰기 전에 검증한다 |
| 실패 3. FAQ 인용과 현행 법령 대조 (값만) | 값만 | (a) 현행에 없는 조를 인용한 쌍 40 (조 15종), (b) 2024-05-29 뒤 개정 날짜가 붙은 조를 인용한 쌍 132 (조 23종), FAQ 480쌍·인용 72종. (a)는 다른 법령 조문이 섞여 실제보다 클 수 있다 |
| 이번에 안 하는 것: 과거 버전·별표 본문·DB·alembic·스케줄러 | 예 | `git diff --name-only main...HEAD`에 alembic 0건, 새 환경변수 읽기 0건 |

## 확인한 것

- 테스트: 리뷰 처리 후 `147 passed`, `ruff check`·`ruff format --check` 통과.
- 리뷰 처리 후 실제 응답 캐시로 CLI를 두 번 다시 돌렸다: exit 0, 90조문, 개수 5개 일치, 누락·중복·소속·속성 0.
- 워크트리의 `.venv`는 메인 repo의 editable 설치를 가리켜 이 브랜치 코드가 안 잡힌다. 실행·테스트는 `PYTHONPATH=src`를 붙여 했다.
