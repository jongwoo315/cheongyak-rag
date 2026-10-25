# #71 리뷰 — PR #7

**대상:** `main...HEAD` — 19 commits, 19 files, +2669 −2
**plan:** docs/plans/71-1022-plan-notice-ingest.md

리뷰는 `pr-review-toolkit:review-pr`의 에이전트 4개(code-reviewer · pr-test-analyzer · silent-failure-hunter ·
comment-analyzer)로 했다. type-design-analyzer는 새 타입이 `Converted` 데이터클래스 하나뿐이라 돌리지 않았다.
Critical은 없었다. Important는 전부 고쳤고 Suggestion은 `defer`·`기록만`으로 남겼다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/ingest/notice.py:499` | 받은 행 수와 테이블에 있는 수가 달라도(페이지 사이 같은 PK 중복) `main`이 exit 0을 돌려준다 | fix `c78ad48` |
| 2 | Important | `src/cheongyak_rag/ingest/notice_report.py:395` | 수집이 실패한 뒤 `last_run.json`이 이전 실행 것인데도 DB와 맞춰 보지 않고 리포트를 쓴다 | fix `d881af0` |
| 3 | Important | `src/cheongyak_rag/ingest/notice_report.py:379` | 키가 비어 있거나 앞뒤 공백이 붙으면 키 노출 검사가 아무것도 찾지 못한 채 통과하고 리포트는 「0회」를 적는다 | fix `6d4f35a` |
| 4 | Important | `src/cheongyak_rag/ingest/notice.py:32` | `RECHECK_LIMIT` 주석이 「최대 건수」라고 하지만 재조회에 성공한 공고는 세지 않는다 | fix `c2b80cd` |
| 5 | Important | `tests/test_notice_cli.py:146` | 받는 도중(두 번째 공고의 주택형 호출 500) 실패해도 DB와 요약이 그대로인지 보는 테스트가 없다 | fix `29f8013` |
| 6 | Important | `tests/test_notice_cli.py:58` | 재시도가 `calls.total`·`calls.retries`에 잡히는지 보는 테스트가 없다 (실패 징후 6의 근거) | fix `9b255ef` |
| 7 | Important | `tests/test_notice_upsert.py:62` | `CHUNK` 500 초과 적재와 한 묶음 안 PK 중복 합치기를 보는 테스트가 없다 | fix `a42cd17` |
| 8 | Important | `tests/test_notice_cli.py:60` | `extra`와 PK 집합 해시가 달라지는 경우(통과 기준 4가 잡으려는 것)를 실제 데이터로 만드는 테스트가 없다 | fix `1396269` |
| 9 | Suggestion | `src/cheongyak_rag/ingest/notice.py:372` | 공고와 주택형 upsert가 서로 다른 트랜잭션이라, 주택형 쪽이 실패하면 `notices`만 갱신되고 `last_run.json`은 이전 값으로 남는다 | defer — 다시 실행하면 같은 PK로 덮어써 복구되고 데이터를 잃지 않는다. `upsert`가 `Connection`을 받게 바꾸는 일이라 이 PR 범위 밖이다. 후속 티켓에서 다룬다 |
| 10 | Suggestion | `src/cheongyak_rag/ingest/notice.py:367` | 받은 공고 전부에 주택형이 없으면 무조건 exit 1이라, 기간을 아주 짧게 잡으면 실패 징후 4의 1~3건 구간(리포트에 적는다)에 못 간다 | defer — 기본 3개월은 공고 84건이라 안 걸린다. matchCount 0 방어와 같은 이유로 둔 보호이며 좁히면 2026-10-23 사고를 다시 열 수 있다 |
| 11 | Suggestion | `src/cheongyak_rag/ingest/notice_report.py:97` | 재실행 비교가 이전 실행과 `since`·`months`가 같은지 보지 않는다. 날짜가 다른 두 실행도 통과 기준 4를 충족한 것으로 나온다 | defer — 리포트 문구를 바꾸는 일이라 리포트를 다시 쓰는 후속 티켓으로 넘긴다 |
| 12 | Suggestion | `src/cheongyak_rag/ingest/notice.py:243` | SQLAlchemy `Table` 정의에 `nullable=False`·FK·인덱스가 없고 alembic이 보는 `Base.metadata`에도 없다. `autogenerate`를 돌리면 두 테이블을 지우는 revision이 나온다 | defer — 지금은 insert에만 쓴다. 마이그레이션은 손으로 쓰는 방식이라 autogenerate를 안 쓴다는 점을 후속 티켓에서 문서화한다 |
| 13 | Suggestion | `src/cheongyak_rag/ingest/notice.py:441` | `_previous`가 깨진 이전 파일을 조용히 `None`으로 처리해 「이전 실행이 없다」로 보인다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/ingest/notice.py:217` | 빈 값이 된 타입 열을 열별로 세지 않아 한 열이 통째로 비어도 실패 징후 3이 0으로 나온다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/ingest/notice.py:213` | 필수 필드 오류가 어느 행인지 말하지 않고, 넓은 `except ValueError`가 다른 오류도 한 줄로 삼킨다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/ingest/notice.py:358` | 재조회로 복구된 공고가 어느 것인지 요약에 안 남는다 (`calls.recheck` 개수만 남는다) | 기록만 |
| 17 | Suggestion | `docs/71-notice-ingest.md:137` | 「이전 실행」 열이 이미 두 번째 실행이라 첫 적재(84/473 넣음) 숫자가 문서에 없다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/ingest/notice.py:56` | `_get` docstring이 반환 순서를 거꾸로 적었고 `NoticeApiError`·`upsert` docstring이 실제 범위보다 넓다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/ingest/notice.py:333` | 주석의 「상류」는 교정 표에 있는 말이다 (뜻은 odcloud API 서버) | 기록만 |
| 20 | Suggestion | `tests/test_notice_fetch.py:128` | 키 노출·재시도 테스트가 400/404 즉시 실패, 200인데 `matchCount`가 없는 본문, 재조회 최대 3건 제한을 안 본다 | 기록만 |
| 21 | Suggestion | `tests/conftest.py:54` | 테스트가 SIGKILL로 끝나면 `cheongyak_test_<pid>` DB가 남는다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/ingest/notice_report.py:211` | plan은 첫 줄을 「결론 한 문장」으로 정했는데 생성되는 첫 줄이 세 문장이다 | defer — 문장 수는 jw가 PR 게이트에서 볼 문제고, 세 문장 모두 plan이 요구한 세 숫자(적재율·재실행·주택형 없는 공고)다 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1: `alembic upgrade head`가 두 테이블을 만들고 `downgrade 0001` 뒤 다시 `upgrade head`가 된다 | 예 | `tests/test_notice_migration.py` 통과 · `alembic/versions/0002_notices.py` |
| 통과 기준 2: 수집 CLI가 최근 3개월 공고·주택형을 upsert하고 숫자를 출력하며 exit 0 | 예 | `tests/test_notice_cli.py` 통과 · `runs/71/last_run.json` (공고 84/84, 주택형 473/473, 호출 85회) |
| 통과 기준 3: 리포트가 `docs/71-notice-ingest.md`를 쓰고 첫 줄이 결론 한 문장 | 아니오 | 파일은 써진다(`tests/test_notice_report.py` 통과). 첫 줄이 한 문장이 아니라 세 문장이다 (지적 22, `src/cheongyak_rag/ingest/notice_report.py:211`) |
| 통과 기준 4: 같은 날 두 번째 실행 뒤 행 수·PK 집합 그대로, 새로 들어간 행 0 | 예 | `tests/test_notice_cli.py::test_second_run_adds_nothing` · `last_run.json`의 `inserted` 0, 해시 같음. 같은 날인지는 비교하지 않는다(지적 11) |
| 통과 기준 5: 서비스 키가 로그·예외·리포트·커밋 어디에도 없다 | 예 | `tests/test_notice_fetch.py` · `tests/test_notice_cli.py` · `tests/test_notice_report.py` 통과. 리뷰어가 실제 키의 인코딩·디코딩 두 꼴을 `git diff main...HEAD`·`git log -p main..HEAD`·산출물에서 찾아 0회 |
| 통과 기준 6: 전체 테스트, `ruff check`, `ruff format --check` 통과 | 예 | `514 passed` · `All checks passed!` · `90 files already formatted` (커밋 `a42cd17` 기준) |
| 실패 징후 1: 공고·주택형이 테이블에 다 들어갔나 | 판정 불가 | 값만 적는다: 공고 84/84, 주택형 473/473 (`runs/71/last_run.json`). 구간 판정은 사람이 한다 |
| 이번에 안 하는 것: APT 외 operation, PDF, 주기 갱신, 임베딩, `retrieval/`·`generate/` 변경 없음 | 예 | `git diff --stat main...HEAD`에 해당 파일 없음 |

재측정: 수정 뒤 실제 DB에 수집을 다시 돌리지는 않았다. 고친 것은 종료 코드·검사·테스트·주석이고 적재 로직은 안 바꿨다.
