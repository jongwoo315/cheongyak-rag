# 80 리뷰 — PR #12

**대상:** `main...HEAD` — 9 commits(리뷰 fix 4개 포함), 12 files, +9007 −0
**plan:** docs/plans/80-1029-plan-axis-verdict.md

리뷰는 `pr-review-toolkit:review-pr` 하위 에이전트 넷(코드 · 테스트 · 조용한 실패 · 주석)으로 했다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/verdict_report.py:323` | 같은 프롬프트로 다시 돌린 실행의 호출 수가 첫 실행과 같거나 많으면 두 번째 실행이 아니라 새 첫 실행으로 덮여, 캐시 키가 흔들려도 징후 6이 「미측정」으로만 남는다 | fix `4d2d252` |
| 2 | Important | `src/cheongyak_rag/generate/verdict_report.py:319` | 판정을 못 낸 하위 질의(`verdict` 없음)가 있어도 완주한 첫 실행으로 기록돼, 일부 비용만 첫 실행 값이 된다. `attach_runs` docstring도 실제 조건보다 넓게 적혀 있었다 | fix `4d2d252` |
| 3 | Important | `src/cheongyak_rag/generate/verdict_report.py:172` | 측정 코드의 라벨 재조회(`_with_labels`)가 `try` 밖에 있어, 17번째 셀에서 DB 연결이 끊기면 앞 16개 셀의 리포트가 하나도 안 써진다 | fix `bbda673` |
| 4 | Important | `src/cheongyak_rag/generate/verdict_report.py:578` | `last_run.json`이 깨져 있으면 경고만 찍고 이어 가서, 비용을 쓴 뒤 첫 실행 기록을 덮어쓴다 | fix `a03a000` |
| 5 | Important | `tests/test_generate_verdict_report.py:196` | 측정 코드가 `chunks`를 따로 조회해 잡은 없는 라벨이 징후 1 구간과 exit code에 닿는 경로가 테스트에 없다. `_with_labels`가 빈 목록을 돌려줘도 통과한다 | fix `9150d7e` |
| 6 | Important | `tests/test_generate_verdict_report.py:163` | 징후 2~5의 분류 필터(프로필 · 축 · 판정값)가 개수로 고정돼 있지 않다. `empty` 필터가 `partial`을 세도 통과한다 | fix `9150d7e` (5와 같은 커밋) |
| 7 | Important | `src/cheongyak_rag/generate/verdict_report.py:176` | 한 셀의 `judge()`가 중간에 예외를 내면 이미 호출해 낸 비용이 `spent`와 `usage`에서 빠진다. `client.calls`는 세므로 두 숫자가 어긋난다 | defer — `judge()`가 목록을 한 번에 만들어 돌려주는 구조라 부분 결과를 돌려주려면 반환 형태를 바꿔야 한다. 이번 측정은 셀 오류 0건이고 총비용 $0.93이 상한 $3에 한참 못 미쳐 값은 안 틀린다. 다음에 `judge`를 건드릴 때 같이 한다 | <!-- style-exempt -->
| 8 | Important | `src/cheongyak_rag/generate/verdict.py:333` | `_call`이 `refusal`과 `finish_reason`을 버리고, `except Exception`이 코드 버그(`resp.usage`가 None 등)까지 하위 질의 하나의 오류 문자열로 바꾼다. 400·404처럼 매번 실패하는 오류도 질의마다 따로 실패한다 | defer — 이번 135개 호출에서 판정 없음이 0건이라 실제로 낸 적이 없다. 오류 문자열은 리포트 §6에 그대로 나와 숨겨지지는 않는다. 모델 비교(#143)에서 모델이 바뀌면 refusal이 처음 나올 수 있으니 그때 `finish_reason`을 기록한다 |
| 9 | Important | `src/cheongyak_rag/generate/verdict.py:52` | system 프롬프트의 조 제목이 DB와 다르다. 제10조는 「월납입금을 선납 또는 연체한 경우 등의 처리」이고 제34조는 「대규모 택지개발지구 등에서의 우선공급」인데 각각 「가입 및 납입조건」, 「해당 지역 거주자 우선공급」으로 적혀 있다(56행) | defer — 조 번호는 맞고, 제목을 고치면 `system_sha`가 바뀌어 캐시 135개와 측정($0.93)이 전부 무효가 된다. #143에서 프롬프트를 다시 재므로 그때 고친다 |
| 10 | Important | `src/cheongyak_rag/generate/verdict_report.py:658` | 실제 측정에서 징후 2(7개)와 3(18개)이 미완 구간인데 exit 0이다. exit 1은 징후 1 미완과 멈춤에만 걸린다 | push-back — plan 통과 기준 5와 Task 5가 「징후 1이 미완이면 exit 1」로 정했다. 징후 2·3이 미완인 사실은 리포트 표와 `PROMPT_NOTES`에 적혀 있고, 받아들일지는 PR 게이트에서 jw가 판정한다 |
| 11 | Suggestion | `tests/test_generate_verdict.py:268` | `format_verdict`의 분기(판정 실패 · 기각된 인용 · `forced` 표시 · 조건 · 필요한 정보)와 CLI exit 1·2 경로, FAQ 쪽 `chunks` 재조회, `mst=None` 공고, 예산 상한에서 캐시 판정 제외, 중간 `HardApiError`, 일시 오류 구간이 테스트에 없다 | 기록만 | <!-- style-exempt -->
| 12 | Suggestion | `src/cheongyak_rag/generate/verdict.py:322` | 캐시 행에 필드가 빠졌거나 모양이 다르면 `KeyError`·`TypeError`가 `judge_one` 밖으로 나가고, `cache.put`의 `OSError`는 낸 판정을 잃는다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:314` | 첫·두 번째 실행을 가를 때 프롬프트와 모델만 비교해, 프로필 파일이나 공고 표본을 고친 뒤 다시 돌려도 「같은 명령」으로 본다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:162` | 비용 상한이 실행마다 0에서 다시 센다. 멈춘 실행을 이어 돌리면 상한의 두 배까지 쓸 수 있다 | 기록만 | <!-- style-exempt -->
| 15 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:381` | 판정값 분포 표의 「합」은 판정 없음(`None`)까지 세므로 5값 칸의 합보다 클 수 있다. §6은 표본 10개만 싣고 「외 N개」가 없다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:58` | `PROMPT_NOTES`의 프롬프트 해시 `b9ccf0a6`·`5ea17eff`와 중간 측정값(징후 2·3 5/18, 6/15, 중간 비용 셋)은 저장소에 없다. 보고서 상단 「실행」 시각은 캐시만 읽은 두 번째 실행 시각이다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/generate/verdict.py:151` | 주석과 리포트의 「인용이 모두 기각돼」는 모델이 처음부터 인용을 하나도 안 낸 경우(`forced=True`)를 포함하지 않는다. `_plain` docstring은 개수만 남긴다고 적었으나 실제로는 `{notice, profile, axis}` 목록을 남긴다 | 기록만 |

7번은 비용 합계가 낮게 나올 수 있는 쪽이고, 위에서 `fix`로 처리한 1~6번은 리포트 숫자(`runs/80/last_run.json`)를 바꾸지 않아 실제 API를 다시 부르지 않았다. 5번과 6번은 테스트 두 개가 같은 커밋 `9150d7e`에 들어 있다(지적마다 커밋 하나 규칙을 어겼다).

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. `judge(...)`가 켜진 축의 하위 질의마다 `Verdict` 하나를 돌려주고, 꺼진 축은 LLM을 안 부른다 | 예 | `tests/test_generate_verdict.py:218-227`(꺼진 축 4개, 호출 3 = 판정 3) |
| 통과 2. `verdict`는 5값 중 하나이고 schema `strict: true`로 강제한다 | 예 | `src/cheongyak_rag/generate/verdict.py:125-136`, `:288` |
| 통과 3. guardrail 넷이 각각 가짜 클라이언트 테스트를 가진다 | 예 | `tests/test_generate_verdict.py:119-165` |
| 통과 4. CLI가 축 7개와 하위 질의마다 판정 · 이유 · 인용 · 기각된 인용을 출력한다 | 예 | `tests/test_generate_verdict.py:268-288`. 기각된 인용 · `forced` 출력 줄은 테스트가 안 본다(지적 11) |
| 통과 5. `--report`가 징후 1~6을 재고 md·json을 쓰고, 징후 1이 미완이면 exit 1이다 | 예 | `tests/test_generate_verdict_report.py:97-127` |
| 통과 6. 리포트 §표본에 공고 6건 × 프로필 3종 전부가 있다 | 예 | `docs/80-axis-verdict.md` §3, `runs/80/last_run.json` 판정 135개 |
| 통과 7. `uv run pytest -q` · `ruff check` · `ruff format --check` | 예 | `886 passed` · `All checks passed!` · `142 files already formatted`(fix 4개 뒤) |
| 징후 1. 판정 없음·5값 밖 0 · 꺼진 축 호출 0 · 인용 0개 판정 0 · 없는 라벨 0 | 예 | `docs/80-axis-verdict.md` 1절: 0 · 0 · 0 · 0 · 0 (켜진 하위 질의 135개). 꺼진 축 판정은 #79 `independent_on`이 같은 설계를 옮긴 것이라 같이 틀릴 수 있다 |
| 징후 2. `empty.json`의 `ELIGIBLE`·`INELIGIBLE`이 0 | 아니오 | 7개(통과 0, 다시 잰다 1~2, 미완 3 이상). 프롬프트를 세 번 고친 뒤 값이 5~10 사이를 오가 멈췄다(`PROMPT_NOTES`) |
| 징후 3. `full.json`에서 칸 없는 4개 축의 `ELIGIBLE`·`INELIGIBLE`이 0 | 아니오 | 18개(미완 3 이상). 이 중 `INELIGIBLE` 5개는 프로필에 실제 있는 값(미혼 자녀 수 1 · 혼인신고일 2012-05-20)에서 나왔다 |
| 징후 4. `homeless`·`account`에서 판정을 내린 비율 10/12 이상 | 예 | 10/12(`NEED_INFO` 없음, `UNVERIFIABLE` 2 — `account`) |
| 징후 5. `forced` 비율 20% 이하 | 예 | 0/135 (0.0%), 기각된 인용 라벨 0개 |
| 징후 6. 첫 실행 $3 이하 · 두 번째 실행 호출 0 | 예 | 첫 실행 호출 135 · $0.9313, 두 번째 실행 호출 0(캐시 135). 프롬프트를 고쳐 가며 측정한 네 번의 합은 $3.63이고 상한은 실행 하나에 건다 | <!-- style-exempt -->

## 확인한 것

- fix 4개 커밋 뒤 `uv run pytest -q` 886 passed, `ruff check` · `ruff format --check` 통과
- fix는 측정 코드(`verdict_report.py`)와 테스트만 바꿨다. `verdict.py`와 system 프롬프트는 그대로라 `system_sha 92f338a4`와 커밋된 측정값은 유효하다
- 이 세션은 실제 API를 부르지 않았다
