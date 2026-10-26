# 77 리뷰 — PR #9

**대상:** `main...HEAD` — 리뷰 시작 시점 8 commits, 15 files, +8149 −0 (수정 커밋 11개가 얹혀 지금은 19 commits, 15 files, +8269 −0)
**plan:** docs/plans/77-1026-plan-profile-score.md

리뷰는 `pr-review-toolkit`의 에이전트 4개(코드 리뷰 · 테스트 분석 · 조용한 실패 점검 · 주석·타입 점검)로 했다.
각 지적은 에이전트가 파일을 읽거나 작은 입력을 돌려 확인한 것만 옮겼다. 한 줄 이름 아래 같은 처리인 것은 묶었다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/profile.py:327` | 세대주가 아니거나 소유자가 있으면 직계존속이 몇 명이든 0명으로 세는데도 `ascendants_3y`·`is_household_head`가 `missing`에 올라온다. #82가 필요 없는 질문을 하게 된다 | fix `a30b06e` |
| 2 | Important | `src/cheongyak_rag/profile_score.py:617` | `--report`가 FAQ 사례나 FAQ 170 기간 예시가 어긋나도 exit 0이다. 실패 징후 1(a)·4가 어긋나도 종료 코드에 안 드러난다. 같은 이유로 FAQ 리포트 불일치 경로를 CLI 테스트가 보지 않았다 | fix `7aa254a` |
| 3 | Important | `src/cheongyak_rag/profile_score.py:612` | `notice_law_versions`가 비어도 「공고 0건 × 샘플 3개, 0/0건 성공」으로 exit 0이다 | fix `9eb63c9` |
| 4 | Important | `src/cheongyak_rag/profile_score.py:253` | 문자열은 맞고 점수가 틀린 FAQ 170 행이 있어도 구간 문구가 「6/6 → 통과」로 찍힌다 | fix `ec752e6` |
| 5 | Important | `src/cheongyak_rag/profile_check.py:309` | tightness가 범위도 전수 대입도 한 값이면 두 값이 서로 달라도 건너뛴다. 틀린 한 값 범위가 측정에서 빠진다 | fix `0408e71` |
| 6 | Important | `src/cheongyak_rag/profile_score.py:641` | `--soundness-n -5`는 「-5건, 위반 0」으로 공허하게 통과하고 `0`은 `ZeroDivisionError`다. `--tightness-bases`도 같다 | fix `cd432d5` |
| 7 | Important | `src/cheongyak_rag/profile.py:366` | `Value`의 docstring이 `value`가 None인 이유를 입력 부족으로만 적었다. `homeless_now=False`의 해당 없음도 None이다 | fix `ab2b2fa` |
| 8 | Important | `src/cheongyak_rag/profile_score.py:300` | 리포트 본문이 `ever_married`가 비면 항상 `missing`에 오른다고 적었는데 코드는 배우자 없음 답 + 무주택일 수 있을 때만 올린다 | fix `5edd5ba` |
| 9 | Important | `tests/test_profile_cli.py:209` | 파서가 점수표 행을 빠뜨려도(`row_count_ok` 거짓) `--report`가 exit 1인지 보는 테스트가 없다. 해당 조건을 지워도 CLI 테스트가 전부 통과한다 | fix `21052a0` |
| 10 | Important | `src/cheongyak_rag/profile_score.py:192` | 계산 중 예외를 `kind: "error"` 실패로 세는 경로를 실행하는 테스트가 없다 | fix `bccda72` |
| 11 | Important | `tests/test_profile_score.py:195` | `homeless_now=False`일 때 ①만 확인하고 `homeless_start`·`homeless_period`가 비는지 안 본다. #79가 이 값을 읽는다 | fix `930c106` |
| 12 | Important | `src/cheongyak_rag/profile_score.py:595` | 검사가 실패한 실행도 `last_run.json`과 리포트를 덮어쓴 뒤에야 종료 코드를 정한다. 커밋된 파일이 실패 수치로 바뀔 수 있다 | push-back — plan 통과 기준 6이 정한 것은 종료 코드다. 실패한 실행의 리포트도 어디가 어긋났는지 읽는 재료라 쓰는 쪽이 낫다. 덮어쓴 파일은 `git diff`에 그대로 보인다 |
| 13 | Important | `src/cheongyak_rag/profile.py:273` | `homeless_since`가 생년월일보다 빠르거나 배우자 통장 가입일이 혼인신고일보다 빠른 입력을 오류 없이 받는다. `max()`가 가려서 점수는 안 바뀌지만 오타가 안 잡힌다 | defer — 입력 모순 검사를 더 하려면 어디까지 막을지 정해야 하고, 입력 모양은 #79가 값을 받을 때 확정한다. 지금 점수가 틀리지는 않는다 |
| 14 | Suggestion | `src/cheongyak_rag/profile_score.py:554` | `except (ValueError, OverflowError)`가 내부 `ValueError`도 「입력 오류」 exit 2로 보인다. 극단 날짜는 메시지가 암호 같다 | defer — 날짜 범위를 `_resolve`에서 먼저 검사하고 `ProfileError`만 exit 2로 받는 쪽이 맞다. 입력 검증(13번)과 같이 한다 |
| 15 | Suggestion | `src/cheongyak_rag/profile.py:521` | `homeless_now`를 모르는데 무주택기간 값이 확정된 것처럼 나오고 근거에 「모른다」가 없다. 같은 결과의 ① 범위는 0~32다 | defer — #79가 `values`와 `scores`를 같이 받으므로 범위로 불확실함은 드러난다. 값 쪽에 어떻게 표시할지는 #79 프롬프트를 짜면서 정한다 |
| 16 | Suggestion | `src/cheongyak_rag/profile.py:119` | 월말에 시작한 기간이 민법 제160조③으로 세면 하루 일찍 끝난다 (`2019-08-30 → 2020-02-28`이 6개월 0일, 민법으로는 2020-02-29에 6개월). 점수가 달라지는 날은 구간 경계에 걸리는 날뿐이다 | defer — FAQ 170과 설계 §6 어느 쪽도 이 경우를 정하지 않았다. 리포트 §7에 「루프가 정한 자리」로 적혀 있고 어느 해석을 쓸지는 jw가 정한다 |
| 17 | Suggestion | `tests/test_profile_range.py:60` | 범위 테스트가 일부 자리를 못 잡는다. `bases=3`이면 15칸 중 7칸을 못 재고, 이혼자 날짜 없음의 범위 값 · `spouse_has_savings=True`+가입일 모름의 하한 · 날짜 경계(2월 29일 · 30세 생일 당일)를 일부러 고르는 무작위가 없다. 한 줄 변형 약 60개 중 이 자리 몇 개가 테스트를 통과했다 | defer — 에이전트가 경계를 촘촘히 깐 5407개 프로필로 soundness를 돌려 위반 0건을 확인했다. 지금 코드에 버그가 없고 테스트를 강하게 하는 일이라 이번 PR 범위 밖이다 |
| 18 | Suggestion | `tests/test_profile_score.py:258` | 입력 검증 테스트가 경계에서 먼 값만 쓴다. 만 19세 · 혼인 만 18세 · 가입일 ≥ 출생 · 가입일 ≤ 공고일의 한계를 하루 옮겨도 통과한다 | defer — 17번과 같은 테스트 강화다. 검증 경계의 전날·당일 케이스를 한 번에 더하는 별도 정리로 한다 |
| 19 | Suggestion | `src/cheongyak_rag/profile.py:240` | `date.fromisoformat`이 `20261023`·`2026-W43-5`도 받는다. 중복 JSON 키(`{"married":true,"married":false}`)는 뒤 값이 경고 없이 쓰인다. `--report`가 `--profile`·`--as-of`를 조용히 무시한다. `default=str`이 직렬화 안 되는 값을 가린다. `calc_notices`의 `except Exception`이 프로그래밍 오류도 실패로 센다. 샘플 파일 모양이 틀리면 원시 traceback이다. DB 접속 오류가 「공고 없음」과 같은 exit 1이다. tightness가 후보별 `ProfileError`를 건너뛴다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/profile.py:201` | 타입 설계. `Profile`이 모순 상태(`married=True`·`ever_married=False` 등)를 직접 만들 수 있고 검사는 `_resolve`에 있다. `Range`에 `lo <= hi` 검사가 없고 `ProfileScore.total`이 항목 범위와 어긋날 수 있다. `_KINDS`가 필드와 따로 관리되는 표다. `Value.value: object`가 타입을 안 좁힌다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/profile.py:3` | 주석·docstring 사소한 부정확. 모듈 docstring이 `datetime.date`만 쓴다고 적었으나 `timedelta`·`calendar`도 쓴다. `_resolve` docstring이 채우는 칸을 일부만 적었다. `faq_cases` docstring이 튜플을 적었으나 dict를 돌려준다. `spouse_bonus` 근거는 이유를 안 붙인다. `tests/test_profile_score.py:93`·`tests/test_profile_faq.py:50`의 「이전 2년 + 이후 4년」 설명이 한 행에만 맞는다. `profile_check.py:242`의 `getattr` 진리값 검사가 `False`·`0` 칸을 「지운 칸」 목록에서 뺀다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/profile_score.py:42` | 리포트가 FAQ 170 행의 기대값 사본을 따로 들고 있어 `tests/test_profile_faq.py`와 갈라질 수 있다. 입력·FAQ 보기 테스트 몇 개(`from_dict` 개수 칸의 `true`·`1.5`·`"2"`, CLI의 파일 없음·잘못된 JSON·공고 0건 `--report`)가 비어 있다. 378bfd0에서 FAQ 151 입력에 `ever_married=False`가 늘었다(기대값은 그대로) | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1: `profile.py`에 `Profile`·판정용 값·항목 점수·부분 프로필 범위가 있고 LLM·네트워크 호출이 없다 | 예 | `src/cheongyak_rag/profile.py` (`Profile`·`score`·`Range`), import에 표준 라이브러리만, `pyproject.toml` 의존성 변경 없음 |
| 통과 기준 2: 별표 1 40행(16 · 7 · 17)이 코드 상수와 전부 같고 파서가 행 수도 확인한다 | 예 | `tests/test_profile_table.py` · 리포트 §2 어긋난 칸 0 · 행 수 16 · 7 · 17. 행 수가 틀리면 `--report`가 exit 1 (`21052a0`) |
| 통과 기준 3: FAQ q_no 11개 테스트 + FAQ 170 예시 6행, 테스트는 구현보다 먼저 커밋 | 예 | `tests/test_profile_faq.py` · 커밋 `b639329`가 구현 커밋 `fc64eaf`보다 앞 · 리포트 FAQ 11/11, 기간 6/6 |
| 통과 기준 4: 경계 테스트 (점수표 구간 시작일·전날, 제10조⑥, 배우자 가산 3점·③ 17점, 열린 질문 네 개) | 예 | `tests/test_profile_score.py`·`tests/test_profile_dates.py`의 `test_open_q1`~`q4` · 에이전트가 경계 5407개 프로필로 따로 확인 (위반 0) |
| 통과 기준 5: soundness 2000건 위반 0 · 완전이면 `lo == hi` · 빈 프로필 합계 6~84 · tightness가 같은 비율을 잰다 | 예 | `tests/test_profile_range.py` · 리포트 §4 위반 0/2000 · 빈 프로필 (6, 84). tightness는 아래 실패 징후 3 값 |
| 통과 기준 6: CLI `--as-of`·`--notice`·`--report`, `mst` 불일치 exit 1, 리포트 exit 규칙 | 예 | `tests/test_profile_cli.py` 27개 통과 · `--report` exit 0이고 첫 줄이 커밋된 리포트와 같다 · 어긋남·위반·FAQ 불일치·공고 0건에서 exit 1 (`7aa254a`·`9eb63c9`) |
| 통과 기준 7: 전체 테스트 · `ruff check` · `ruff format --check` | 예 | `uv run pytest -q` 710 passed (리뷰 전 697) · `ruff check` All checks passed · `ruff format --check` 116 files already formatted |
| 실패 징후 1: FAQ 일치 수 / 사례 수 · 점수표 어긋난 칸 · 계산 실패 수 (통과: 전부 일치 · 0 · 0) | 판정 불가 | 값: FAQ 11/11, 어긋난 칸 0, 계산 실패 0 (공고 84건 × 샘플 3개 252/252). 어느 구간인지는 jw가 읽는다 |
| 실패 징후 2: soundness 위반 건수 (통과: 0) | 판정 불가 | 값: 무작위 2000건 중 0건 (시드 77). `exact`가 같은 규칙 함수를 쓰므로 규칙 자체 오류는 못 잡는다는 점이 리포트 §4에 적혀 있다 |
| 실패 징후 3: tightness 같은 비율 (통과: 0.95 이상, baseline 없음 — 첫 측정) | 판정 불가 | 값: 131/131 = 1.000. 수정 후 `--report`를 다시 돌려도 같은 값이다. 5번 수정으로 범위와 전수 대입이 다른 한 값을 세게 됐으나 이 측정에서는 어긋난 쌍이 새로 안 나왔다 |
| 실패 징후 4: FAQ 170 기간 문자열 일치 행 (통과: 6/6) | 판정 불가 | 값: 6/6 |
| 실패 징후 5: 파싱한 행 수 16 · 7 · 17 | 예 | 리포트 §1: ① 16 · ② 7 · ③ 17 |

## 확인한 것과 못 한 것

- `uv run pytest -q`: 710 passed. `uv run ruff check`·`ruff format --check` 통과
- `uv run python -m cheongyak_rag.profile_score --report`: exit 0. 첫 줄이 커밋된 리포트와 같다. 실행 시각만 달라 파일은 되돌렸다
- 서버 기동(`uvicorn`)은 이 세션에서 다시 확인하지 않았다. 이 PR은 FastAPI 코드를 건드리지 않는다
- 인라인 코멘트는 12·13·14·15·16·17·18번에만 단다 (push-back · defer 행)
