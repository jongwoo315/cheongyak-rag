# 80 리뷰 — PR #13

**대상:** `main...HEAD` — 17 commits(리뷰 fix 11개 포함), 17 files, +10300 −0 (PR #12 코드를 가져온 것이 대부분이라 리뷰는 PR #12 마지막 커밋 `1c06665` 이후 변경에 맞췄다)
**plan:** docs/plans/80-1030-plan-eligible-guard.md

리뷰는 `pr-review-toolkit:review-pr` 하위 에이전트 넷(코드 · 테스트 · 조용한 실패 · 주석)으로 했다. 리포트 숫자는 주석 점검 에이전트가 `runs/80/last_run.json`에서 다시 셌고 징후 1~6 값이 전부 맞았다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/verdict.py:131` | `account` 축은 `savings_join_date`만 있으면 ELIGIBLE이 남는데, 이 축의 하위 질의는 「가입 기간과 예치금 기준」이다. 프로필에 예치금·납입 칸이 없어서, 꽉 찬 프로필 `account` 판정의 이유에 「월납입금 2만원 이상 50만원 이하」「예치금 기준에 부합」이 적힌 채 ELIGIBLE로 남았다 | defer — 필요한 칸 표는 설계 §무엇을 바꾸나가 정했고 코드는 그 표대로다. 징후 1의 B가 칸 없는 4개 축만 세고 징후 2가 `account`를 안 바뀌어야 하는 축으로 정해서 리포트는 통과로 나온다. 고치려면 `account`를 칸 없는 축으로 옮겨야 하고 그러면 징후 2·3의 정의와 측정이 바뀐다. 이 PR이 jw 기준을 `account`에서 얼마나 채우는지는 PR 게이트에서 jw가 판정한다. 예치금 칸은 #82에서 프로필에 더할 때 같이 넣는다 |
| 2 | Important | `src/cheongyak_rag/generate/verdict_report.py:827` | 종료 코드 주석이 「징후 1·2 미완이면 exit 1」인데 코드는 징후 4 미완과 실행 멈춤에도 exit 1이다 | fix `6daa35e` |
| 3 | Important | `docs/80-axis-verdict.md` §5 1번 | 「유형 판정이 전부 같게 나온 것은 5쌍」을 guard 뒤 판정으로 셌다. 모델이 낸 판정으로 세면 1쌍이고, 나머지는 guard가 같은 값으로 맞춘 것이다 | fix `fa96bbc` |
| 4 | Important | `docs/80-axis-verdict.md` §5 2번 | `NEED_INFO` 94개를 system 프롬프트 규칙의 결과처럼 적었다. 모델이 낸 판정은 62개이고 32개는 guard가 바꾼 것이다 | fix `27ac2ea` |
| 5 | Important | `src/cheongyak_rag/generate/verdict.py:329` | `REQUIRED_FIELDS`·`NEED_INFO_TEXT`의 키가 `axes`의 축 목록과 같다는 테스트가 없다. 축을 더하고 표를 안 고치면 모델이 ELIGIBLE을 낸 순간 `KeyError`로 그 공고의 판정이 전부 사라진다 | fix `5b06526` |
| 6 | Important | `src/cheongyak_rag/generate/verdict.py:330` | 칸 이름이 틀리거나 `Profile` 칸 이름이 바뀌면 `.get`이 None을 돌려줘 그 축의 ELIGIBLE이 전부 조용히 `NEED_INFO`가 된다 | fix `033a29f` |
| 7 | Important | `tests/test_generate_verdict_report.py:220` | 징후 1을 A만 1 이상 / B만 1 이상으로 따로 보는 테스트가 없다. `zone_jw`에 `len(nofield)`를 0으로 넘겨도 통과한다 | fix `07b2855` |
| 8 | Important | `tests/test_generate_verdict_report.py:220` | 징후 1의 「다시 잰다」(판정 없음 1~2개)와 `partial` 판정 없음이 구간에 안 닿는 것을 `symptoms()`로 확인하는 테스트가 없다 | fix `6bae585` |
| 9 | Important | `src/cheongyak_rag/generate/verdict_report.py:411` | `attach_runs`가 guard 전 분포가 PR #12와 다를 때(`dist_same=False`) 징후 5를 미완으로 만드는지 테스트가 없다. 인자를 `True`로 바꿔도 통과한다 | fix `73e4b51` |
| 10 | Important | `tests/test_generate_verdict_report.py:220` | 징후 3이 ELIGIBLE·INELIGIBLE·CONDITIONAL만 세고 `NEED_INFO`·`UNVERIFIABLE`·칸 없는 축은 안 센다는 것을 `symptoms()`로 고정한 테스트가 없다 | fix `e28c5fd` |
| 11 | Important | `tests/test_generate_verdict.py:216` | guard가 모델의 `need_info`를 바꾸는지(덧붙이지 않는지)와 이유·조건이 남는지 확인하는 테스트가 없다. 기본 응답의 `need_info`가 비어 있어서 `+=`로 바꿔도 통과한다 | fix `f0c0e7f` |
| 12 | Important | `tests/test_generate_verdict.py:216` | 테스트가 `vd.NEED_INFO_TEXT[axis_id]`와 비교해서, 표의 문구끼리 바꿔 적어도 통과한다 | fix `13891f4` |
| 13 | Important | `src/cheongyak_rag/generate/verdict_report.py:350` | 「같은 응답을 읽었다」를 guard 전 분포가 칸마다 같은지만으로 판정한다. baseline에 공고 id·모델이 없고, 같은 칸 안에서 응답 둘이 바뀌어도 분포는 같다. 리포트가 「첫 실행 호출 0」이 PR #12가 채운 캐시 덕이라는 설명 없이 첫 실행 값으로 적는다 | push-back — plan 징후 5가 「guard 전 분포가 PR #12와 칸마다 같음」을 기준으로 정했고 코드가 그대로다. 호출 0·캐시 135 적중은 캐시 키(모델 + 메시지 해시)가 PR #12와 같다는 뜻이라 같은 모델·같은 메시지의 응답을 읽은 것은 별도로 확인된다. 첫 실행 비용 $0.9313은 baseline 파일에 있다 |
| 14 | Important | `src/cheongyak_rag/generate/verdict_report.py:827` | 종료 코드가 징후 3·5 미완을 안 본다. 표본이나 `--model`이 바뀌어 징후 5가 미완이어도 exit 0이다 | push-back — plan 통과 기준 5가 exit 1을 징후 1·2로만 정했고 코드는 징후 4와 멈춤까지 더 엄격하다. 징후 3·5 미완은 리포트 표에 그대로 나온다 |
| 15 | Important | `src/cheongyak_rag/generate/verdict_report.py:356` | 징후 3은 분모(`backed_n`)가 12가 아니어도 10 이상이면 통과로 적고, 징후 2는 센 대상 수를 안 보인다. 예산으로 멈추면 「10/10 통과」처럼 나온다 | push-back — 멈춘 실행과 셀 오류는 징후 4를 미완으로 만들고 exit 1이다(`stop`이면 징후 1·2도 미완). 리포트는 쓰이고 징후 4 미완이 표에 찍힌다 |
| 16 | Suggestion | `src/cheongyak_rag/generate/verdict.py:130` | `homeless`는 `homeless_now`만 보는데 이 축은 무주택 기간도 판정하고, `ever_owned`·`homeless_since`가 비어도 `homeless_now=true`면 ELIGIBLE이 남는다. 표본의 세 프로필에는 이 모양이 없다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/generate/verdict.py:392` | guard가 값이 있는지만 보고 일관성은 안 본다. `homeless_now=false`인데 모델이 `homeless` ELIGIBLE을 내도 남는다. 바뀐 판정에 모델의 `conditions`가 그대로 붙는다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:811` | 측정이 끝나고 리포트·JSON을 쓰는 중에 예외가 나면 이미 쓴 비용이 `last_run.json`에 안 남아, 다음 실행이 호출 0을 첫 실행으로 적는다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:222` | 셀 안에서 `KeyError` 같은 예외가 나면 그 셀의 비용이 예산 계산에서 빠진다(PR #12 리뷰 지적 7과 같은 뿌리) | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:186` | 판정 없음(`None`)과 5값 밖 판정이 분포 표 칸에는 없고 「합」에만 들어간다. guard 전→후 비교가 그 행에서는 안 보인다 | 기록만 |
| 21 | Suggestion | `docs/80-axis-verdict.md` §5 `PROMPT_NOTES` | 「칸이 없는 축 18개 중 INELIGIBLE 5개」의 18은 ELIGIBLE+INELIGIBLE이다. 칸 없는 축 판정은 31개다. 같은 노트의 「징후 3은 이 5개도 센다」는 PR #12 번호로 적혀 이 리포트의 징후 3(`homeless`·`account`만)과 다르다. 「남은 문제는 지어내는 것이다」는 이 PR의 guard가 가린다는 말이 없다 | 기록만 |
| 22 | Suggestion | `docs/80-axis-verdict.md` 상단 | 「첫 실행 호출 0 · $0」과 처리 시간 0.1초는 캐시만 읽은 실행의 값이다. PR #12 첫 실행(호출 135 · $0.9313)과 LLM 호출 시간이 아니라는 말이 리포트에 없다. `#82가 맡는다`는 문장과 설계의 「프로필 칸 추가 — #82」 설명도 어긋난다 | 기록만 |
| 23 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:101` | `zone_jw` docstring이 세 조건을 같이 만족해야 미완으로 읽힌다(실제는 하나라도). 모듈 docstring이 구간 이름에 `미측정`을 빼고, `_plain` docstring이 「개수만 남긴다」고 적었으나 실제로는 사례 목록을 남긴다 | 기록만 |
| 24 | Suggestion | `tests/test_generate_verdict_report.py:100` | 징후 1 「다시 잰다」가 exit 0, 징후 3·5 미완이 exit 0인 경계, `usd == 3.0` 경계, 표 여섯 행의 구간 값, `forced`·`invalid_labels`, 꽉 찬 프로필 CLI 한 줄(`ELIGIBLE` 유지), 이유 앞 「(모델)」이 guard가 아닌 행에 안 붙는 것은 테스트가 없다 | 기록만 |

7번~12번은 테스트만 더했고 `verdict.py`·`verdict_report.py` 동작은 바꾸지 않았다. 2·3·4번은 코드 주석과 열린 질문 문장(생성 코드와 `docs/80-axis-verdict.md`를 같은 문구로 고쳤다)만 바꿨고 징후 1~6 값과 `runs/80/last_run.json`은 그대로다. 실제 API는 부르지 않았다. 지적마다 커밋 하나다.

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. PR #12의 판정 모듈·측정 코드·테스트·프로필 3종을 가져오고 가져온 직후 `uv run pytest -q`가 통과한다 | 예 | 커밋 `4ae6449`(파일 7개). 지금 `944 passed` |
| 통과 2. `judge_one()`이 인용 guardrail 다음에 ELIGIBLE guard를 적용하고, 필요한 칸 중 하나라도 `None`이면(또는 칸 없는 축이면) `ELIGIBLE` → `NEED_INFO`, `guarded=True`, `original_verdict="ELIGIBLE"`, `need_info`에 설계 표 문구, 인용은 그대로 | 예 | `src/cheongyak_rag/generate/verdict.py:325-331`(`eligible_guard`), `:391-396`. 문구는 `13891f4` 테스트가 설계 표 글자로 고정 |
| 통과 3. guard 테스트(칸 없는 4축 · `account` · `homeless` · `householder` 두 경우, 다른 판정 4개 불변, `forced` 불변) | 예 | `tests/test_generate_verdict.py:215-290` |
| 통과 4. CLI 출력에 guard가 바꾼 판정이 원래 판정과 함께 표시된다 | 예 | `src/cheongyak_rag/generate/verdict.py:470-477`, `tests/test_generate_verdict.py`의 `format_verdict` guard 테스트 |
| 통과 5. `--report`가 징후 1~6을 재고 리포트·JSON을 쓰고, 징후 1 또는 2가 미완이면 exit 1 | 예 | `tests/test_generate_verdict_report.py:150-165`. 종료 코드는 징후 4 미완·멈춤에도 1이다(지적 2·14) |
| 통과 6. `SYSTEM`·user 메시지 조립을 바꾸지 않고 `system_sha`가 PR #12와 같은 `92f338a4`다 | 예 | `docs/80-axis-verdict.md` 상단 `프롬프트 92f338a4 (PR #12 92f338a4)`, 캐시 135 적중 |
| 통과 7. `uv run pytest -q` · `ruff check` · `ruff format --check` | 예 | `944 passed` · `All checks passed!` · `144 files already formatted`(fix 11개 뒤) |
| 징후 1. 통과: 빈 프로필 ELIGIBLE(A) 0 · 꽉 찬 프로필 칸 없는 4개 축 ELIGIBLE(B) 0 | 예 | A 0(guard 전 7) · B 0(guard 전 13) · 판정 없음 0. `account`의 예치금은 이 수치가 안 본다(지적 1) |
| 징후 2. 통과: `full`의 `homeless`·`account`·`householder`에서 guard가 바꾼 수 0 | 예 | 0개 |
| 징후 3. 통과: `full`의 `homeless`·`account` 12개 중 ELIGIBLE·INELIGIBLE·CONDITIONAL 10/12 이상 | 예 | 10/12(PR #12 10/12) |
| 징후 4. 통과: 판정 없음·5값 밖·꺼진 축 호출·인용 0개 판정·없는 라벨 전부 0 | 예 | 전부 0(켜진 하위 질의 135개). 꺼진 축 목록은 `axes.plan`을 옮긴 것이라 같이 틀릴 수 있다 |
| 징후 5. 통과: 첫 실행 호출 0 · 두 번째 실행 호출 0 · guard 전 분포가 PR #12와 칸마다 같음 | 예 | 호출 0 · 0, 분포 같음. 첫 실행 0은 PR #12가 채운 캐시를 읽은 값이다(지적 13) |
| 징후 6. 값만 적는다 | 판정 불가 | guard가 바꾼 판정 32/135, `forced` 0/135, 칸 없는 축 `INELIGIBLE` 5, `partial` 칸 없는 축 ELIGIBLE 0(guard 전 12) |

## 확인한 것

- fix 커밋 11개 뒤 `uv run pytest -q` 944 passed(리뷰 시작 때 935), `ruff check` · `ruff format --check` 통과
- `verdict.py`와 system 프롬프트는 안 바꿨다. `system_sha 92f338a4`와 커밋된 측정값은 그대로 유효하다
- 이 세션은 실제 API를 부르지 않았다. 리포트 상단 문구는 같은 내용으로 생성 코드와 `docs/80-axis-verdict.md`를 같이 고쳤고 재측정은 하지 않았다
