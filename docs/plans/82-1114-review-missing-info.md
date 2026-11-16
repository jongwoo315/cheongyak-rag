# #82 리뷰 — PR #23

**대상:** `main...HEAD` — 구현 9 commits(리뷰 전), 22 files, +3117 −10. 리뷰가 고친 커밋 4개가 더 붙었다
**plan:** docs/plans/82-1114-plan-missing-info.md
**리뷰 방법:** `pr-review-toolkit:review-pr` 하위 에이전트 5개(code · tests · errors · comments · types)와 직접 읽기. 단어장 검사는 걸린 곳 없음(`docs/concepts.md` `## 용어`의 「쓰지 말 말」을 diff의 코드·주석·문서에서 찾았다)

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/verdict.py:402` | LLM 단계가 근거 0개(`no_context`)·API 오류·응답 해석 실패로 일찍 끝나면 프로필 불가 규칙이 적용되지 않는다. 예: `ever_owned=true`인데 생애최초 하위 질의가 조문을 못 찾으면 INELIGIBLE이 아니라 UNVERIFIABLE로 남고, 그 경로가 안 닫혀 소득·자산 질문이 나온다. `runs/82`에는 이런 줄이 0개다 | push-back — 설계 §5가 「규칙이 걸리면 LLM을 안 부르기」를 안 고른 이유가 근거 없는 INELIGIBLE이 화면에 나가는 것이고, plan Task 2가 규칙을 「호출이 성공했을 때」로 정했다. 일찍 끝나는 줄에도 규칙을 걸지는 jw가 정한다 |
| 2 | Important | `src/cheongyak_rag/generate/rules.py:122` | 규칙 `householder-1`이 세대주 축을 INELIGIBLE로 정하면, 규제 지역이 아니고 노부모 부양만 공급하는 공고에서도 세대주 축이 모든 경로에 들어가 일반공급과 전역 판정이 INELIGIBLE이 되고 질문이 0개가 된다. `aggregate.py:75`의 `ponytail:` 주석이 이미 적어 둔 단순화(#81)가 규칙 때문에 매번 걸린다 | defer — 경로 합치기(`aggregate.py`)는 #81 범위이고 정답 라벨도 같은 합치기로 센다. 세대주 축을 경로별로 나누는 일은 따로 티켓이 필요하다 |
| 3 | Important | `src/cheongyak_rag/generate/verdict.py:489` | `guarded`와 `ruled`가 같이 켜지면(`special_type` 하위 질의의 모델 ELIGIBLE이 이 경우다) CLI가 규칙의 이유를 「이유(모델)」로 적는다 | fix `d8eb3dd` |
| 4 | Important | `docs/concepts.md:42` | 이 PR이 `verdict.py`·`aggregate.py`에 줄을 더해 `VERDICTS`(→43)·시스템 프롬프트(→89~99줄)·`aggregate`(→72)·`GENERAL_AXES`(→30) 줄 번호가 어긋났다 | fix `e7d9947` |
| 5 | Important | `src/cheongyak_rag/generate/questions_report.py:366` | 리포트 문장이 「이 질문 N개 중 … N개」로 같은 값을 둘 다 적어 `docs/82-missing-info.md:22`가 「1개 중 1개」로 나왔다. 센 대상도 질문이 아니라 (질문 × 하위 질의) 줄이다 | fix `b52fade` |
| 6 | Important | `web/components/Result.tsx:27` | 웹 질문 목록(순서·「입력란 없음」·빈 목록의 「없음」)을 보는 e2e 테스트가 없다. plan Task 5는 `npm run build`만 요구한다 | defer — 이번 plan의 통과 기준 5는 build 통과다. 화면 테스트는 따로 티켓 |
| 7 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:211` | 모델 판정이 이미 INELIGIBLE인 하위 질의(규칙이 걸린 87개 중 11개)도 체크리스트 note가 「INELIGIBLE로 바꿈 (모델 판정 INELIGIBLE)」로 나왔다 | fix `cc6189a` |
| 8 | Suggestion | `src/cheongyak_rag/generate/questions.py:155` | 모델이 NEED_INFO를 냈는데 코드가 정보를 하나도 못 찾는 하위 질의(채워진 `homeless_now`, 유형 미상 특별공급)는 질문이 0개가 되고 모델의 `need_info` 문장은 버려진다 | 기록만 |
| 9 | Suggestion | `src/cheongyak_rag/trace.py:89` | trace는 `forced`·`guarded`만 남기고 `ruled`·`rule`은 안 남긴다. `model_verdict`와 `verdict`가 달라 바뀐 것은 알 수 있지만 규칙 번호는 모른다 | 기록만 |
| 10 | Suggestion | `src/cheongyak_rag/generate/questions_report.py:519` | `main()`이 `ValueError`·`KeyError`까지 「읽기 실패」로 적고 traceback을 숨긴다. `ORDER.index` 오류도 파일 읽기 실패처럼 보인다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/generate/questions.py:58` | `TYPE_INFO`·`AXIS_INFO`·`_info` 리터럴의 이름이 `TEXT`에 다 있는지 보는 테스트가 `Rule.fields`만큼 없다. 이름 오타는 `KeyError`로 크게 터지지만 테스트가 먼저 잡으면 좋다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/generate/rules.py:70` | `_is`가 `==`라 `0 == False`가 맞는다. `Profile.to_dict()`가 타입을 지켜서 지금은 안 걸린다 | 기록만 |
| 13 | Suggestion | `tests/test_generate_verdict.py:529` | `test_rule_applies_after_the_eligible_guard`는 가드가 안 걸리는 `householder`를 쓴다. 가드와 규칙이 같이 걸리는 `special_type`+ELIGIBLE, 캐시에서 읽은 응답+규칙, `no_context`+규칙 테스트가 없다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/eval/run.py:66` | `run.jsonl` 줄에 `ruled`·`rule`이 없어 리포트가 규칙을 다시 계산한다(`questions_report.py:196`). 줄에 남기면 재계산 없이 맞춰 볼 수 있다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/generate/questions_report.py:425` | 「`runs/138`은 N/91」의 91이 코드에 박혀 있다. 골든셋이 바뀌면 어긋난다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1 — 프로필 불가 규칙이 설계 §2.1의 번호 그대로 있고(`referral-1`·`newlywed-3` 제외) 규칙마다 걸리는·안 걸리는 단위 테스트가 있다 | 예 | `rules.py:117-165` 23개, `tests/test_generate_rules.py` |
| 통과 기준 2 — 걸리면 `INELIGIBLE`·`ruled`·`rule`·`original_verdict`, 체크리스트 `note`에 한 줄 | 예 | `verdict.py:402-407`, `aggregate.py:211`, `tests/test_generate_verdict.py:508-575` |
| 통과 기준 3 — 결손 분석이 없는 정보와 불가 판정을 낼 수 있는 빈 칸을 낸다. 이름은 17개 그대로 | 예 | `questions.py:22,104`, `tests/test_generate_questions.py` |
| 통과 기준 4 — `Answer.questions`가 설계 §2.3대로 채워지고 `render_text`가 순서대로 적는다 | 예 | `questions.py:134`, `aggregate.py:305-335` |
| 통과 기준 5 — 웹이 질문을 순서대로 보여 주고 `npm run build`가 통과한다 | 예 | `web/components/Result.tsx:27,148`, 이 세션에서 `npm run build` 통과 |
| 통과 기준 6 — `runs/82`·`docs/82-eval.md`를 만들었고 `runs/138`·`docs/138-eval.md`는 그대로다 | 예 | `git diff main...HEAD --stat`에 `runs/138`·`docs/138-eval.md` 없음. `eval.report`를 다시 돌려 `docs/82-eval.md`와 같음을 확인 |
| 통과 기준 7 — `docs/82-missing-info.md`에 jw 기준·실패 징후 2~4·지표 7개 전후·설계 §4 세 줄 | 예 | `docs/82-missing-info.md` |
| 실패 징후 1 — ① 378/378 이고 ② 0문항이면 통과 | 판정하지 않음 | ① 378/378, ② 1문항(g21 `marriage_status`, 정답 규칙 `newlywed-3`). 문서의 구간은 「다시 잰다」 |
| 실패 징후 2 — 빠진 질문 문항 수가 비교값 이하면 정상 | 판정하지 않음 | 24문항, 비교값 24문항 |
| 실패 징후 3 — 규칙이 INELIGIBLE로 정한 하위 질의 중 정답이 INELIGIBLE이 아닌 수 0이면 정상 | 판정하지 않음 | 87개 중 0개 |
| 실패 징후 4 — 치명오답 2 이하면 정상 | 판정하지 않음 | 0개(`runs/138`은 2/91) |
| Pre-PR — 전체 테스트 · ruff · golden check · 서버 부팅 | 예 | `pytest` 1431 passed(리뷰 fix 뒤), `ruff check`·`ruff format --check` 통과, `golden.check` exit 0, `/health` 응답 `BOOT_OK` |

## 처리 후 확인

- 고친 4건은 각각 한 커밋이다: `d8eb3dd` · `cc6189a` · `e7d9947` · `b52fade`
- `docs/82-missing-info.md`는 `b52fade`에서 같은 코드로 다시 만들었고 바뀐 줄은 지적 5의 문장 하나뿐이다
- 이 파일은 PR 게시 때 요약 코멘트로 올라가고, push-back·defer인 1·2·6번은 인라인 스레드가 달린다
