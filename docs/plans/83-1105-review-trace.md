# 83 리뷰 — PR #16

**대상:** `main...HEAD` — 12 commits, 18 files, +3987 −6 (리뷰 fix 커밋 3개 포함, 이 리뷰 파일 제외)
**plan:** docs/plans/83-1105-plan-trace.md

단어장: `docs/concepts.md` `## 용어` 절의 「쓰지 말 말」(요청·쿼리·셀·로그·trace 레코드·프로필 ID·마스킹·비식별화)을 diff의 코드·주석·docstring·문서에서 찾았다. 0건(법령 원문 인용 1곳은 해당 없음).

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `docs/concepts.md:85` | 일반공급 경로가 「켜진 일반 축 5개」를 합친다고 적었지만 `aggregate`는 일반 축 5개 중 켜진 것만 합친다. 공고에 따라 3개일 수 있다 | fix `38a842f` |
| 2 | Important | `tests/test_trace.py` (`run_traced`의 `cache` 전달·`steps()`의 `fresh` 걸러내기) | 캐시를 읽는 두 번째 실행의 호출 0과 `total.llm_calls` 0을 검사하는 테스트가 없었다. `cache` 인자를 빠뜨려도 테스트가 통과한다 | fix `a2b8b34` |
| 3 | Important | `tests/test_generate_trace_report.py:44` | `zone_calls`의 경계 1·3(「다시 잰다」)이 검사되지 않았다. `>`를 `>=`로 바꿔도 통과한다 | fix `9ee224b` |
| 4 | Important | `src/cheongyak_rag/trace.py:57` | `mask`가 프로필 날짜와 같은 글자를 구조 칸(`steps.as_of`·`answer.as_of`·`law_effective_date`)에서도 바꾼다. 프로필 날짜가 공고일과 같으면 저장된 `as_of`가 `[프로필 값]`이 되고, 공고일은 `house_manage_no`로 찾을 수 있어 가린 값이 드러난다. 측정의 `hide`(`trace_report.py:91`)가 `mask`를 그대로 옮긴 것이라 B가 이걸 못 잡는다 | defer — plan 통과 기준 4가 「저장하는 모든 글자」를 가린다고 정했다. 구조 칸을 빼는 것은 가리기 범위를 바꾸는 설계 결정이라 jw가 정한다 |
| 5 | Important | `src/cheongyak_rag/generate/trace_report.py:230` | 징후 1의 B가 `error` 행을 질의가 실패했으면 기대값으로 센다. 흐름 버그로 20건이 전부 `error` 행이 되어도 A 0·B 0·C 0·D 0·E 0이고 exit 0이다. 징후 3만 미완이 되는데 exit 코드는 징후 1·2만 본다. `EXPECTED_STATUS`(`:48`)는 출력만 한다 | defer — plan이 status 분포를 「같이 적는 값」으로 두었고 B의 정의가 그대로 구현됐다. 분포를 구간에 넣으려면 plan 기준을 바꿔야 한다 |
| 6 | Important | `src/cheongyak_rag/generate/verdict.py:280` | `ValueError(f"스키마 위반: {content[:120]}")`가 LLM 응답을 120자에서 잘라 오류 글자에 넣는다. 잘린 자리가 프로필 날짜 안이면 일부(`"2012-05-2`)가 `steps.queries[].error`에 저장되는데 `mask`도 C 검사도 전체 10자만 찾아서 놓친다 | defer — 이 줄은 PR이 바꾼 줄이 아니다(#80 코드). 저장하는 쪽(`trace.mask`)에서 오류 글자를 어떻게 다룰지 정해야 해서 별도 티켓 |
| 7 | Suggestion | `src/cheongyak_rag/trace.py:186` | 응답을 만든 뒤의 `except Exception`이 `mask`·`steps`·`asdict`의 코드 오류까지 `trace_error` 글자 하나로 줄인다. 같은 코드 오류가 모든 CLI 실행에서 「trace 행을 못 썼다」로 나오고 traceback이 없다 | 기록만 |
| 8 | Suggestion | `src/cheongyak_rag/trace.py:170` | `error` 행 쓰기에서 `SQLAlchemyError`가 아닌 예외가 나면 원래 흐름 예외 대신 그 예외가 올라간다. `HardApiError`가 바뀌면 `measure`가 멈춤 처리를 못 한다 | 기록만 |
| 9 | Suggestion | `src/cheongyak_rag/trace.py:187` | `trace_error` 글자는 `mask`를 거치지 않고 stderr와 `runs/83/last_run.json`에 들어간다 | 기록만 |
| 10 | Suggestion | `src/cheongyak_rag/trace.py:160` | `error` 행이 `steps`를 빈 객체로, `pblanc_no`를 인자 그대로(주지 않았으면 null) 쓴다. `judge`가 성공한 뒤 `build_answer`가 실패하거나 공고를 찾은 뒤 `ProfileError`가 나면 이미 쓴 호출 수·비용과 찾은 `pblanc_no`가 행에서 빠진다. 설계는 `pblanc_no`를 「공고를 못 찾으면」만 null이라고 적었다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/trace.py:48` | HMAC 입력이 `to_dict()` 전체라 `Profile`에 칸이 하나 늘면 모든 해시가 바뀐다. 전후 행을 같은 프로필로 묶을 수 없다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/generate/trace_report.py:273` | `DERIVED` 파생값이 `zone_hide`에 들어가지 않는다 | 기록만 — 설계 §이번에 안 하는 것이 판정하지 않는다고 정했다 |
| 13 | Suggestion | `src/cheongyak_rag/generate/trace_report.py:236` | B의 「steps 하위 질의 수 = 체크리스트 수」는 같은 `verdicts`에서 만든 두 목록을 비교해 항상 같다. `verdict` 칸과 `answer.verdict`, `pblanc_no`는 비교하지 않는다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/generate/trace_report.py:429` | 표 라벨 「질의 수와 새 행 수의 차이」가 낡았다. A는 `expected`(20)와 새 행 수의 차이다. `docs/83-trace.md`에도 같은 라벨이 있어 리포트를 다시 돌려야 맞는다 | 기록만 |
| 15 | Suggestion | `alembic/versions/0005_traces.py:28` | `pblanc_no` 주석 「공고를 못 찾으면 null」이 부족하다. 호출자가 `pblanc_no`를 안 준 `error` 행이면 공고를 찾았어도 null이다(설계 문서 52행도 같다) | 기록만 |
| 16 | Suggestion | `docs/concepts.md:101`, `src/cheongyak_rag/trace.py:144` | 「행 쓰기가 실패해도 응답을 돌려준다」는 흐름이 성공한 질의에만 맞다. `error` 행 쓰기가 실패하면 예외가 그대로 올라가고 `trace_error`는 없다. `run_traced` docstring도 행을 만드는 단계의 실패를 빼먹었다 | 기록만 |
| 17 | Suggestion | `docs/concepts.md:42`, `:53`, `:57` | 이 PR이 안 건드린 줄의 인용이 어긋났다(`verdict.py:41`→42, `:130`→131, `profile.py:214`→201) | 기록만 — PR 범위 밖 |
| 18 | Suggestion | `tests/test_generate_trace_report.py:290` | 두 번째 실행 호출 0과 `zones["calls"]` 통과를 검사하는 `main` 테스트가 없다(`world`의 baseline `cells`가 비어 분포가 항상 다르다). `HardApiError` 멈춤 경로, `attach_runs`의 다른 분기(다른 `system_sha`·멈춘 첫 실행), 준비 실패 exit 2·3도 검사가 없다 | 기록만 |
| 19 | Suggestion | `tests/test_trace.py:98` | `Profile.to_dict()`의 글자 값이 전부 ISO 날짜임을 검사하는 테스트가 없다. 짧은 글자 칸이 생기면 `mask`가 저장된 모든 행의 글자를 조각낸다. HMAC 입력 형식을 고정하는 테스트도 없어 `plain_sha`와 `profile_hash`가 어긋나도 E가 안 걸린다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `0005_traces.py`가 설계 `traces` 칸 그대로 테이블과 인덱스 3개를 만들고 downgrade가 지운다 | 예 | `alembic/versions/0005_traces.py:20-45`, `tests/test_traces_migration.py` 통과 |
| 2. `run_traced`가 `judge` → `build_answer` → 행 쓰기. 중간 예외에도 `error` 행 + 다시 올림. 행 쓰기 실패면 응답과 실패 사실을 같이 돌려줌 | 예 | `src/cheongyak_rag/trace.py:129-188`, `tests/test_trace.py` 25개 통과 |
| 3. `profile_hash`는 HMAC-SHA256 16진수. 키는 `Settings.trace_hash_key`, `.env.example`에 빈 값. 키가 비면 흐름 전에 예외 | 예 | `trace.py:44-49`·`:147`, `config.py` 신규 칸, `.env.example` 신규 줄 |
| 4. 저장하는 모든 글자에서 프로필 문자열 값을 `[프로필 값]`으로 바꾸고 반환 응답은 그대로 | 예 | `trace.py:52-72`·`:182-183`, `tests/test_trace.py:114`. 구조 칸까지 바뀌는 점은 지적 4 |
| 5. CLI가 `run_traced`를 부르고 출력은 그대로. 키 없으면 exit 2. 행 쓰기 실패면 응답 출력 뒤 stderr + exit 1 | 예 | `verdict.py` `main()` diff, `tests/test_trace.py:241`·`:275` |
| 6. `--report`가 징후 1~3을 재고 `docs/83-trace.md`·`runs/83/last_run.json`을 쓴다. 징후 1 또는 2가 미완이면 exit 1 | 예 | `trace_report.py:732-736`, `tests/test_generate_trace_report.py`(A·C·D 미완 exit 1). 측정값 자체의 판정은 하지 않는다 |
| 7. `SYSTEM`·user 메시지 조립·`REQUIRED_FIELDS`·B8 규칙·B9 응답 칸을 안 바꾸고 `system_sha`가 `92f338a4` | 예 | `git diff main...HEAD -- src/cheongyak_rag/generate/verdict.py`는 `main()`만 바뀜. `docs/83-trace.md:6` 프롬프트 `92f338a4` |
| 8. `docs/concepts.md`에 경로·trace 상태 2개 절. `## 용어`는 안 고침 | 예 | `docs/concepts.md:79-102`. 인용 줄 `aggregate.py:71`·`:29`, `trace.py:27` 확인(지적 1·16은 문구) |
| 9. `uv run pytest -q` 전체 통과 · `ruff check` · `ruff format --check` | 예 | 리뷰 fix 3개 뒤 `uv run pytest -q` 1034 passed · `ruff check` 통과 · `ruff format --check` 166 files already formatted |

실패 징후 1~3의 측정값(`docs/83-trace.md` 첫 줄: 징후 1 A 0·B 0 통과, 징후 2 C 0·D 0·E 0 통과)은 판정하지 않는다. 지적 4·5는 그 통과가 무엇을 재는지에 관한 것이다. 4는 측정이 구현의 가리기를 그대로 옮겨 같이 틀릴 수 있다는 점이고, 5는 `error` 행이 많아도 구간이 안 바뀐다는 점이다.

## 게시 메모

- 지적 6(`verdict.py:280`)은 이 PR이 바꾼 줄이 아니라 diff에 없어서 인라인 스레드를 달 수 없다. 요약 코멘트의 표에만 남긴다
