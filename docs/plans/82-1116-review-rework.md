# #82 재작업 리뷰 — PR #23

**대상:** `bab9c3a..HEAD` — 1차 게이트 반려 뒤 재작업 커밋(이 리뷰의 fix 2개 포함 6 commits), 10 files, +163 −83. 1차 리뷰 파일 `docs/plans/82-1114-review-missing-info.md`는 건드리지 않았다
**plan:** docs/plans/82-1114-plan-missing-info.md (「RESUME — 반려 뒤 재작업」 Task 9~12와 재작업 Done criteria), 설계 §7
**리뷰 방법:** `pr-review-toolkit:review-pr`는 쓰지 않고(재작업이 규칙 1개·테스트·생성 문서 정도라 하위 에이전트 5개를 띄울 크기가 아니다) 직접 읽었다. `mutation` 확인(규칙을 뺀 채 테스트 실행)과 생성물 재현(harness·리포트를 다시 돌려 같은 값이 나오는지)으로 근거를 확인했다. 단어장 검사는 걸린 곳 없음(`docs/concepts.md` `## 용어`의 「쓰지 말 말」을 재작업 diff의 코드·주석·문서에서 찾았다)

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `tests/test_generate_questions.py:169` | 재작업이 더한 테스트 `test_private_notice_newlywed_lists_empty_married_as_a_rule_out_cell`이 `newlywed-3`을 `RULES`에서 빼도 통과했다(`mutation`으로 확인: 규칙을 뺀 채 `01`·`03` 둘 다 `can_rule_out`이 `['homeless_now', 'married', 'marriage_date', 'savings_join_date']`로 같다). 칸 `married`는 `newlywed-2`도 보기 때문이다. plan Task 9가 요구한 테스트가 실제로는 규칙을 안 가렸다 | fix `67d4705` — 규칙 결과를 판정으로 옮겨 질문 만들기까지 잇는 테스트로 바꿨다: `01`이면 `marriage_status`를 안 묻고 `03`이면 묻는다. 규칙을 뺀 채 실행하면 `01` 줄이 깨지는 것을 확인했다 |
| 2 | Important | `docs/82-eval.md:67` · `runs/82/metrics.json` | harness를 다시 돌리자 직전 `runs/82/metrics.json`이 있어 이번 실행이 「두 번째 실행」으로 잡혔다. 그 결과 eval 리포트의 실패 징후 5(재현성)가 「두 번째 실행 호출 0회, 지표 다름 → 다시 잰다」로 나왔다. 두 실행의 지표가 다른 이유는 코드가 바뀐 것(`newlywed-3`)이지 같은 실행이 달라진 것이 아닌데, 리포트는 재현성 실패처럼 적었다. 실행 기록에도 「지표 값 다름」이 원인 없이 남았다 | fix `77b644a` — 직전 `metrics.json`을 지우고 같은 명령으로 다시 돌려 첫 실행으로 만들었다(`run.jsonl`은 바이트까지 같고 판정 정확도 421/524도 같다). 징후 5는 1차 게이트 때와 같은 「두 번째 실행이 없다 → 미측정」이 됐다. `docs/82-missing-info.md`는 다시 만들어도 달라지지 않았다. 반려 전 값(420/524)은 git 기록과 `docs/82-missing-info.md`의 「1차 값」 열에 남아 있다 |
| 3 | Important | `src/cheongyak_rag/generate/rules.py:99` | `newlywed-3`은 「민영(`01`) 공고에는 예비신혼부부·한부모 갈래가 없다」를 규칙으로 쓴다. 근거는 골든셋 신혼부부 공고 18건 중 갈래가 있는 것이 국민주택 1건(`2026000373`)뿐이라는 것이고, 그 18건에 규칙을 만든 계기인 g21의 공고가 들어 있어, 규칙을 만든 데이터와 재는 데이터가 같다. 민영 공고문이 갈래를 적은 공고에서 `married=false`를 입력하면, 모델 판정이 무엇이든 INELIGIBLE이 나가고 그 경로의 질문도 닫힌다. 실패 징후 3의 「어긋남 0개」는 정답 라벨도 같은 `label_facts`로 붙였기 때문에 골든셋 안에서는 거의 정의상 0이다 | defer — 공고문 텍스트는 DB에 없어(`chunks`는 법령·FAQ뿐) 코드가 공고문의 갈래를 읽을 수 없다. 설계 §7이 한계로 적었고(`docs/concepts.md:200`, PR 본문 Notes의 「같이 틀릴 수 있다」), 공고문 PDF를 읽는 안은 「안 고른 것」에 있다. 골든셋 밖 민영 공고 몇 건으로 갈래 유무를 확인할지는 jw가 정한다 |
| 4 | Suggestion | `src/cheongyak_rag/generate/questions_report.py:35` | `NOT_PORTED`가 한 원소 튜플인데 줄이 세 줄로 갈라지고 주석이 닫는 괄호 뒤에 붙었다(포매터 결과). 읽을 때 주석이 가리키는 대상이 흐리다 | 기록만 |
| 5 | Suggestion | `src/cheongyak_rag/generate/questions_report.py:38` | `FIRST_ROUND`(378·1·24·87)가 코드에 박혀 있다. 골든셋이나 규칙이 또 바뀌면 「1차 값」 열이 그대로 남지만 그건 맞는 동작이다(1차 값은 고정). 다만 테스트가 `"378/"`·`"87개"` 문자열만 보고, 새 값(88개)이 같이 나오는지는 안 본다 | 기록만 |
| 6 | Suggestion | `docs/concepts.md:167` | 규칙 표의 `rules.py:NNN` 줄 번호 24개가 손으로 관리된다. 이 재작업이 `newlywed-3`을 끼워 넣어 뒤쪽 줄이 전부 밀렸고 이번엔 맞게 고쳐져 있다(`RULES`=128 · `newlywed-3`=146 · `youth-4`=177을 파일에서 확인). 다음에 규칙을 더하면 또 어긋난다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| Task 9: `rules.py` 표에 `newlywed-2`와 `newlywed-4` 사이로 `newlywed-3`을 더한다. 조건은 `married` = false이고 `facts.house_dtl_secd`가 `01`. `03`·`None`·그 밖이면 안 건다 | 예 | `rules.py:146` · `tests/test_generate_rules.py` `test_newlywed_3_fires_only_on_private_housing_notice_with_married_false`(`01` 걸림, `03`·`None`·`02` 안 걸림) · `test_newlywed_3_sits_between_newlywed_2_and_newlywed_4_and_loses_to_newlywed_1` |
| Task 9: `married` 비었거나 true면 안 걸린다 | 예 | `test_newlywed_3_does_not_fire_when_married_is_empty_or_true` |
| Task 9: 이유 문장이 plan의 문장(「민영주택 공고라 … 혼인기간 요건을 채울 수 없다(제41조)」)이다 | 예 | `rules.py:99-104` · `test_newlywed_3_reason_names_the_cause_and_article` |
| Task 9: 모듈 docstring의 「옮기지 않은 규칙 둘」을 고친다 | 예 | `rules.py:5-8` |
| Task 9: `01` 공고의 신혼부부 하위 질의에서 `married`가 비었으면 불가 판정을 낼 수 있는 빈 칸 목록에 든다는 테스트 | 예 (고친 뒤) | 원래 테스트는 규칙 없이도 통과(지적 1). `67d4705`가 규칙 결과에서 질문까지 잇는 테스트로 바꿨다 |
| Task 10: `runs/82`·`docs/82-eval.md`를 같은 명령으로 다시 만든다. `runs/138`은 그대로다 | 예 | `runs/82/metrics.json` 판정 정확도 421/524 · `run.jsonl` 같은 명령으로 다시 돌려도 바이트까지 같음 · `git diff --stat bab9c3a..HEAD -- runs/138` 비어 있음. 재현성 칸은 지적 2에서 바로잡음 |
| Task 11: `docs/82-missing-info.md` 맨 위 표에 「1차(`0f68afe`) 값」 열을 더한다: ① 378/378 · ② 1문항(g21) · 빠진 질문 24문항 · 규칙이 걸린 하위 질의 87개 | 예 | `docs/82-missing-info.md` 표 · 실패 징후 2·3 문장. 이번 값은 ① 378/378 · ② 0 · 빠진 질문 24문항 · 규칙이 걸린 하위 질의 88개 |
| Task 11: 실패 징후 3(규칙이 정답과 어긋난 수)은 `newlywed-3`을 넣은 뒤 값이다 | 예 | `docs/82-missing-info.md` 실패 징후 3: 88개 중 어긋난 것 0개 |
| Task 12: `docs/concepts.md` 「프로필 불가 규칙」 표에 `newlywed-3` 행을 더하고 「옮기지 않은 규칙 둘」을 `referral-1` 하나로 고친다 | 예 | `docs/concepts.md:179` · `:199` · 표 제목 「24개」 |
| 실패 징후 1~4의 구간 정의를 바꾸지 않는다 | 예 | `git diff bab9c3a..HEAD -- src/cheongyak_rag/generate/questions_report.py`가 `band_*` 함수를 건드리지 않는다(상수·표 열·문장만 바뀜) |
| 새 PR을 만들지 않고 PR #23 본문 맨 위 `## 착수 전 기준 (jw)` 절을 새 값으로 고친다. 그 아래 「1차 게이트 반려 — jw 원문」 한 줄과 바꾼 것 한 줄을 더한다 | 예 | `gh pr view 23`의 본문: 통과 구간·0문항·88개 값, 반려 원문, 바꾼 것 |
| 1차 리뷰 파일을 건드리지 않는다 | 예 | `git diff bab9c3a..HEAD -- docs/plans/82-1114-review-missing-info.md` 비어 있음 |
| main을 작업 브랜치에 merge·rebase하지 않는다 | 예 | `git log --merges main..HEAD` 비어 있음 |
| `uv run pytest -q` · `ruff check` · `ruff format --check` · `golden.check` · `eval.report` exit 0 | 예 | 이 리뷰의 fix 전 `1437 passed` · ruff 통과 · 243 files already formatted · golden.check 어긋난 구절 0개 · `eval.report` 다시 생성. fix 뒤 `tests/test_generate_questions.py` 45 passed, ruff 통과 |
| 실패 징후 1·2·3·4의 값과 구간 | 판정 불가 (값만 적는다) | ① 378/378 · ② 0문항(비교값 32) · 빠진 질문 24문항(비교값 24) · 규칙이 정답과 어긋난 것 0/88 · 치명오답 0/91(`runs/138`은 2/91). 구간 이름은 리포트가 계산해 적었고 판정은 jw가 한다 |
