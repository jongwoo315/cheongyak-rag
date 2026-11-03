# 80 리뷰 — PR #14

**대상:** `main...HEAD` — 13 commits(리뷰 fix·test 7개 포함), 18 files, +10409 −0 (PR #13 코드를 가져온 것이 대부분이라 리뷰는 가져온 커밋 `a7fc466` 이후 변경에 맞췄다)
**plan:** docs/plans/80-1030-plan-eligible-reason.md

리뷰는 `pr-review-toolkit:review-pr` 하위 에이전트 넷(코드 · 테스트 · 조용한 실패 · 주석)으로 했다. 조용한 실패 에이전트가 `docs/80-axis-verdict.md`의 숫자를 `runs/80/last_run.json`에서 다시 세었고(최종 ELIGIBLE 8 · A 0 · guard 전 49 중 32 · guard가 바꾼 41 · 징후 3 6/6) PR #13 baseline도 `f42b690`에서 다시 세어 전부 맞았다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/verdict_report.py:639` | 이 리뷰 세션이 지적 2번을 고치다가 「읽는 법」을 「이유 문장을 보고 고르지 않았다」로 바꿨는데, 설계(`docs/plans/80-1030-design-eligible-reason.md:45`)는 「목록은 PR #12·#13 이유를 보고 정했다. 이 측정 데이터에 맞춘 목록이라 처음 보는 표현은 놓칠 수 있다」이다. 이번 실행은 목록을 만든 그 캐시 응답 135개를 그대로 읽으므로 A 0은 일부 목록에 맞춘 결과다 | fix `e03aacd` |
| 2 | Important | `src/cheongyak_rag/generate/verdict_report.py:639` | 「읽는 법」이 목록의 출처를 「이유를 보고 정했다」로만 적어 설계의 「프로필에 없는 사실에서 정한다」와 어긋난다고 주석 점검이 지적했다 | push-back — 설계가 두 문장을 다 적었다(단어는 프로필에 없는 사실에서 정하고, 목록은 PR #12·#13 이유를 보고 정했다). 한 문장만 남기면 위 1번이 된다. `c8772ae`로 한 번 고쳤다가 `e03aacd`로 되돌렸다 |
| 3 | Important | `docs/80-axis-verdict.md:30` | 처리 시간 「중앙값 0.1초 · 최댓값 2.6초」가 호출 0·캐시 135인 실행의 값인데 LLM 호출 시간과 못 비교한다는 말이 없었다 | fix `ed04db3` |
| 4 | Important | `docs/80-axis-verdict.md:13` | 통장 축 비교의 PR #13 값에 「guard 전」이라고 적었는데 baseline의 `account_full`은 PR #13 최종 값이다 | fix `8019723` |
| 5 | Important | `tests/test_generate_verdict_report.py:150` | 징후 1 표의 A·B 값, 6절 목록, 2절 「걸린 단어」 칸을 확인하는 테스트가 없다. 표의 A와 B를 바꾸거나 6절을 `eligible` 전체로 채워도 통과한다 | fix `e06079d` (A≠B가 되는 응답으로 6절 목록 변형이 실패하는 것까지 확인) |
| 6 | Important | `tests/test_generate_verdict_report.py:180` | 「공허하게 참」 문구가 최종 ELIGIBLE이 있거나 실행이 멈췄을 때 안 붙는 것을 확인하는 테스트가 없다 | fix `fcf9fc5` |
| 7 | Important | `src/cheongyak_rag/generate/verdict_report.py:413` | 리포트 첫 줄이 「프로필에 없는 값을 이유로 든 것 0」인데 실제로는 단어 여섯 개의 부분 문자열 일치다. 최종 ELIGIBLE 첫 행(더샵 분당하이스트 × full × `homeless`)은 「예외 사유에 해당한다는 정보가 없어 … 볼 수 있습니다」로 값이 없는 것을 근거로 들었는데 이것은 징후 6의 `no_value` 1로만 나오고 구간이 없다 | push-back — plan 징후 6이 「값만 적는다 · 구간 없음」으로 정했고 코드가 그대로다. 이 건은 리포트 1절 징후 6 칸과 2절 「정규식 걸림」 칸에 이유 원문과 함께 나온다. 이 사례를 jw 기준(「프로필에 없는 이유로 eligible 판정을 하지 않는다」)에서 어떻게 볼지는 PR 게이트에서 jw가 판정한다 |
| 8 | Important | `src/cheongyak_rag/generate/verdict_report.py:796` | 종료 코드가 징후 3(`decisive`)·5(`cost`) 미완을 안 본다. 캐시가 사라져 호출 135개가 나가거나 `dist_same`이 False여도 exit 0이다 | push-back — plan 통과 기준 4가 exit 1을 징후 1·2로만 정했고 코드는 징후 4와 멈춤까지 더 엄격하다. 징후 3·5 미완은 리포트 표에 그대로 나온다. PR #13 리뷰 14번과 같은 건이다 |
| 9 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:157` | 이유가 빈 ELIGIBLE은 단어가 안 걸려 A에 안 센다. 단어 목록은 부분 문자열이라 `납부`·`재산`·`예치`는 못 잡는다 | 기록만 (이번 표본의 최종 ELIGIBLE 8개는 이유가 전부 비어 있지 않다) |
| 10 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:328` | 징후 2가 `cell_errors`를 안 봐서, 셀이 오류로 비면 판정 0건이라 `통과`로 나온다 | 기록만 (징후 4가 셀 오류에서 미완이라 종료 코드는 1이다) |
| 11 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:56` | 징후 3의 분모(`backed_n`)와 5절 제목의 「공고 6건」을 확인하는 코드가 없다. 공고가 5건이면 5/5가 통과로 나온다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:144` | `load_baseline`이 키 유무만 보고 내용·`system_sha`를 안 본다. `distribution`이 비어 있으면 `dist_same`이 True가 된다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:207` | 셀 오류 뒤 `continue`로 예산 확인을 건너뛰고 그 셀에서 쓴 토큰이 `spent`에 안 들어간다(PR #13 리뷰 19번과 같은 뿌리) | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:275` | A는 최종 ELIGIBLE을 세는데 `REQUIRED_FIELDS`가 `None`인 축은 ELIGIBLE이 안 남아서 A 0은 guard 표 덕이 크다. 단어 목록 검사의 독립성은 guard 전 수(49 중 32)로만 보인다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/generate/verdict.py:127` | `REQUIRED_FIELDS` 주석 첫 줄이 「`None`은 #77에 대응하는 칸이 없는 축」인데 `account`는 `savings_join_date`가 있다. 모듈 docstring(7-8행)도 `None` 축을 말하지 않는다 | 기록만 |
| 16 | Suggestion | `tests/test_generate_verdict.py:229` | 테스트 docstring이 「#77에 칸이 없는 축」인데 `account`가 들어 있다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:86` | `zone_jw(0, 0, 1)`·`first_usd == 3.0` 경계·`pre_eligible_n` 값·`reason=None` ELIGIBLE·guard가 바꾼 `NEED_INFO`의 「인용 0개」 제외 여부를 확인하는 테스트가 없다 | 기록만 |

5·6번은 테스트만 더했고 `verdict.py`·`verdict_report.py` 동작은 바꾸지 않았다. 1·3·4번은 리포트에 찍히는 문구만 바꿨고 `docs/80-axis-verdict.md`의 같은 줄을 같이 고쳤다. 징후 1~6 값과 `runs/80/last_run.json`은 그대로다. 실제 API는 부르지 않았다. 지적마다 커밋 하나이고 `cf0fe41`은 5번 테스트의 `ruff format` 정리다(1번과 2번은 같은 줄이라 `c8772ae`로 고친 것을 `e03aacd`가 되돌렸다).

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. PR #13의 판정 모듈·측정 코드·테스트·프로필 3종·`pr12_baseline.json`을 가져오고 가져온 직후 `uv run pytest -q`가 통과한다 | 예 | 커밋 `a7fc466`. 지금 `948 passed` |
| 통과 2. `REQUIRED_FIELDS["account"]`가 `None`이고 `NEED_INFO_TEXT["account"]`가 「청약통장 예치금(민영주택) 또는 납입 횟수·금액(국민주택)」, 나머지 6개 축은 PR #13 그대로 | 예 | `src/cheongyak_rag/generate/verdict.py:130-146`. 커밋 `810a5b0` |
| 통과 3. `account`에서 `ELIGIBLE`은 `savings_join_date`가 있어도 없어도 `NEED_INFO`·`guarded`·`original_verdict="ELIGIBLE"`, `INELIGIBLE`은 안 바뀜, `homeless`·`householder`는 PR #13 그대로 | 예 | `tests/test_generate_verdict.py:229`(칸 없는 축 파라미터에 `account` 포함), `tests/test_generate_verdict_report.py:139` |
| 통과 4. `--report`가 징후 1~6을 재고 리포트·JSON을 쓰고 징후 1 또는 2가 미완이면 exit 1 | 예 | `tests/test_generate_verdict_report.py:150-175`. 종료 코드는 징후 4 미완·멈춤에도 1이다(지적 8) |
| 통과 5. 징후 1의 이유 문장 검사는 guard 표를 읽지 않고 단어 목록은 측정 코드에 따로 둔다 | 예 | `verdict_report.py:51`(`REASON_WORDS`), `tests/test_generate_verdict_report.py`의 `test_symptom_1_does_not_read_the_guard_table`(`9a3d63c`) |
| 통과 6. `SYSTEM`·user 메시지 조립을 바꾸지 않고 `system_sha`가 `92f338a4`다 | 예 | `git diff a7fc466..HEAD -- src`에서 `SYSTEM` 변경 없음. 리포트 상단 `프롬프트 92f338a4 (PR #13 92f338a4)`, 캐시 135 적중 |
| 통과 7. `uv run pytest -q` · `ruff check` · `ruff format --check` | 예 | `948 passed` · `All checks passed!` · `146 files already formatted`(fix·test 뒤) |
| 징후 1. 통과: A 0이고 B 1 이상 | 예 | A 0(guard 전 ELIGIBLE 49개 중 32) · B 8. 단어 목록이 이 측정 데이터에 맞춘 것이라는 점은 지적 1·14 |
| 징후 2. 통과: `full`의 `homeless`·`householder`에서 guard가 바꾼 수 0 | 예 | 0개 |
| 징후 3. 통과: `full`의 `homeless` 6개 중 ELIGIBLE·INELIGIBLE·CONDITIONAL 5/6 이상 | 예 | 6/6(PR #13 6/6). `account` 판정값 NEED_INFO 4 · UNVERIFIABLE 2 |
| 징후 4. 통과: 판정 없음·5값 밖·꺼진 축 호출·인용 0개 판정·없는 라벨 전부 0 | 예 | 전부 0(켜진 하위 질의 135개). 꺼진 축 목록은 `axes.plan`을 옮긴 것이라 같이 틀릴 수 있다 |
| 징후 5. 통과: 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 PR #13과 칸마다 같음 | 예 | 호출 0 · 0, 분포 같음. 호출 0은 PR #12가 채운 캐시를 읽은 값이다(PR #13 리뷰 13번과 같은 건) |
| 징후 6. 값만 적는다 | 판정 불가 | guard가 바꾼 판정 41/135(PR #13 32/135), `forced` 0/135, 값이 없는 것을 근거로 든 최종 ELIGIBLE 이유 1(PR #13 2) |

## 확인한 것

- fix·test 커밋 7개 뒤 `uv run pytest -q` 948 passed(리뷰 시작 때 947), `ruff check` · `ruff format --check` 통과
- `verdict.py` 동작과 system 프롬프트는 안 바꿨다. `system_sha 92f338a4`와 커밋된 측정값은 그대로 유효하다
- 이 세션은 실제 API를 부르지 않았다. 리포트에 찍히는 문구 두 곳은 같은 내용으로 생성 코드와 `docs/80-axis-verdict.md`를 같이 고쳤고 재측정은 하지 않았다
- 5번 테스트는 6절 목록을 `eligible` 전체로 채우는 변형을 일부러 넣어 실패하는 것까지 확인한 뒤 되돌렸다
