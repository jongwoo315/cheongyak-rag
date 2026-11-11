# #75 리뷰 — PR #20

**대상:** `main...HEAD` — 리뷰 전 10 commits, 리뷰 중 고친 commit 11개 더해 21 commits, 23 files, +4955 −0
**plan:** docs/plans/75-1110-plan-golden-set.md

리뷰 에이전트 4개(코드 · 테스트 · 조용한 실패 · 주석·문서)가 낸 지적을 겹치는 것끼리 합쳐 아래 표에 한 행으로 적었다.
단어장 검사: `docs/concepts.md` `## 용어`의 「쓰지 말 말」은 diff의 코드·주석·docstring·문서에서 1곳(`docs/concepts.md`의 「케이스」)이었고 #10으로 고쳤다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/golden/select.py:154` | `select`를 다시 돌리면 `notices.json`에서 `label_facts`·`db_silent`가 지워진다. 라벨 규칙이 `label_facts`를 기준으로 쓰는데 `check`는 이 칸을 안 읽어 exit 0으로 통과한다 (에이전트 4개가 같이 지적) | fix `9cdfc7c` |
| 2 | Important | `src/cheongyak_rag/golden/check.py:217` | `check_notices`가 `facts`가 없는 공고를 조용히 넘겨 어긋난 구절 0개로 센다 | fix `a682f6f` |
| 3 | Important | `src/cheongyak_rag/golden/check.py:126` | `rule`이 빈 문자열이거나 엉뚱한 글자여도 통과하고 `rule` null 비율(실패 징후 4)에서도 빠진다 | fix `3b21468` |
| 4 | Important | `src/cheongyak_rag/golden/check.py:241` | `agreement` 설명이 조 불일치를 「조 라벨이 다른 수」로 써 두었는데 코드는 「하나도 안 겹치는 수」다 (plan 정의는 코드 쪽) | fix `2ef21d0` |
| 5 | Important | `tests/test_golden_check.py:160` | 조 불일치(겹침 규칙)와 따로 붙인 쪽에 짝이 없는 라벨의 처리를 고정하는 테스트가 없다. 해당 줄을 바꾼 변형 2개가 테스트를 통과했다 | fix `ffaffaf` |
| 6 | Important | `src/cheongyak_rag/golden/report.py:55` | 판정값 하나의 라벨이 몫보다 적으면 jw 표본이 20개보다 적게 뽑히는데 제목은 20개로 나온다. 지금 데이터는 판정값이 3종이라 안 드러난다 | fix `4a1073d` |
| 7 | Important | `src/cheongyak_rag/golden/report.py:5` | 입력 설명이 `second.jsonl`을 입력으로 적었는데 `render_report`는 안 쓴다. `measure.json`이 손으로 적은 값이라는 것도 빠져 있다 | fix `4a1073d` |
| 8 | Important | `docs/75-label-rules.md:21` | 「경계에서 한 달 이상 떨어지게 짠다」가 g15에서 거짓이다 (6개월 경계 2026-08-27, `as_of` 2026-09-10, 14일). 라벨 값은 경계가 지난 쪽이라 틀리지 않다 | fix `7b558aa` |
| 9 | Important | `docs/75-label-rules.md:107` | 특별공급 유형의 정답 근거 조문을 「그 유형의 조문」(+ 제48조)로만 적었는데 `elderly-4`는 제53조, `elderly-5`·`firsttime-3`·`newborn-2`는 제28조를 더한다 | fix `7b558aa` |
| 10 | Suggestion | `docs/concepts.md:130` | 「쓰지 말 말」인 「케이스」를 썼다 (단어장 검사) | fix `620dc67` |
| 11 | Important | `src/cheongyak_rag/golden/check.py:241` | 따로 붙인 라벨 일치율을 다시 계산하는 명령이 없다. 리포트의 4/524는 손으로 적은 `measure.json` 값이다. 지금 `golden.jsonl`과 `second.jsonl`을 `agreement`로 맞추면 11/524가 나온다 (첫 라벨을 고치기 전 `second.jsonl`이라서) | defer — plan 실패 징후 1이 처음 값(고치기 전)을 재라고 정했고 그 값과 설명이 `measure.json` `notes`에 적혀 있다. 재계산 명령은 `check --second` 옵션으로 #76 전에 더한다 |
| 12 | Important | `src/cheongyak_rag/golden/check.py:187` | 한 하위 질의에 라벨이 둘이거나 질의 문장이 `axes.plan`과 다른 경우를 고정하는 테스트가 없다 (변형 2개 생존). 특별공급 축은 유형마다 질의가 하나라 테스트의 한 축 한 질의 `plan_of`로는 안 걸린다 | defer — 실제 `golden.jsonl`에서는 `check`가 이 규칙으로 0건이다. 테스트 보강은 #76 전에 한다 |
| 13 | Important | `src/cheongyak_rag/golden/check.py:291` | `run_check`·`main`의 exit 코드(통과 기준 8) 연결 코드에 테스트가 없다 | defer — 위와 같다. `check`를 실제 DB로 돌려 exit 0, 줄 단위 문제 0건을 이 리뷰에서 확인했다 |
| 14 | Important | `src/cheongyak_rag/golden/report.py:144` | `render_report`는 제목 줄만 테스트한다. 구간 판정 인자를 바꾼 변형 2개가 생존했고 `ag is None` 경로·`disagreements`가 있는 표가 안 걸린다 | defer — 커밋된 `docs/75-golden.md`·`runs/75/review-sample.md`가 코드 재생성 결과와 글자 하나까지 같다는 것을 코드 에이전트·문서 에이전트가 따로 확인했다. 값 단위 테스트는 #76 전에 더한다 |
| 15 | Important | `src/cheongyak_rag/golden/select.py:73` | 동점일 때 관리번호가 작은 쪽, `types`·`axes` 정렬 출력을 고정하는 테스트가 없다 (변형 생존). `frozenset` 순서에 기대면 `notices.json`이 실행마다 달라질 수 있다 | defer — 코드는 `to_dict`에서 `sorted`를 쓴다. 테스트로 고정만 안 했다. #76 전에 더한다 |
| 16 | Suggestion | `src/cheongyak_rag/golden/check.py:152` | 문항 한 줄의 칸이 틀리면 traceback으로 멈춘다 (`profile_kind` 없음, `pblanc_no` 틀림, `notice_evidence` 항목이 dict 아님). exit는 0이 아니라 통과로 잘못 나오지는 않는다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/golden/check.py:95` | `need`는 문자열 목록인지만 보고 이름이 프로필 칸인지는 안 본다. 실데이터에서도 17개 이름 중 14개는 프로필 칸이 아니다 (예: `deposit_amount`). 라벨 규칙이 프로필에 없는 사실도 `need`로 쓰게 하기 때문일 수 있다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/golden/text.py:28` | `quote_in`에 최소 길이가 없다. 가장 짧은 실제 구절은 6자라 지금은 해가 없다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/golden/text.py:34` | `article_text`는 같은 조 라벨에 행이 여럿이면 아무 행이나 돌려준다. 지금 `chunks`는 조 단위라 0건이고, 틀리면 거짓 통과가 아니라 거짓 어긋남으로 드러난다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/golden/check.py:249` | 조 불일치는 겹치는 조가 하나라도 있으면 일치로 센다 (plan 정의 그대로). 조를 하나 빼거나 더하는 차이는 안 드러난다. 이 한계를 `docs/75-golden.md`가 따로 적지 않았다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/golden/check.py:118` | `notice_evidence`가 빈 목록인 라벨이 ELIGIBLE 30개·INELIGIBLE 5개 있다. 라벨 규칙이 공고문에 기대지 않는 경우를 허용하는지는 문서가 정하지 않았다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/golden/select.py:92` | `pdf_notices`가 링크가 여럿인 공고에서 첫 `pdf` 줄을 고른다. `docs/concepts.md`는 공고 결과를 가장 나쁜 줄로 정한다. 고른 20건에는 링크가 둘 이상인 공고가 0건이다 | 기록만 |
| 23 | Suggestion | `docs/concepts.md:131` | `full` 문항 20개가 전부 `ever_owned=True`·`married=True`라 유주택·미혼 사례가 없고 「그 칸이 있어서」 설명이 순환한다 | 기록만 |
| 24 | Suggestion | `docs/75-label-rules.md:139` | `youth-5`가 소득·예치금을 요구하는데 인용한 제35조의2에는 그 요건이 없다. `income-1`이 청년을 안 적은 것과도 맞지 않는다 | 기록만 |
| 25 | Suggestion | `docs/75-golden.md:79` | 리포트에 Python 목록 표기(`['제43조']`)가 그대로 나온다. 「빈틈 둘」이 무엇인지도 모호하다. `second_rows` 인자는 안 쓰인다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `golden.jsonl` 50줄 · 공고 20건 · 프로필 꽉 찬 20·일부 22·빈 8 | 예 | `uv run python -m cheongyak_rag.golden.check` exit 0, 줄 단위 문제 0건. `docs/concepts.md` 20/22/8과 일치 |
| 2. 켜지는 하위 질의 전부에 라벨 하나, 켜지지 않은 축의 라벨 0 | 예 | `check`가 `axes.plan`(실제 DB)으로 대조해 0건. 라벨 524개 |
| 3. 정답 라벨의 칸 | 예 | `check`의 칸 검사 0건. 이 리뷰에서 `rule` 번호 꼴 검사를 더했고(#3) 실데이터 38종이 통과 |
| 4. 문항 한 줄의 칸 | 예 | `check`의 칸 검사 0건 |
| 5. 프로필 읽힘 · 꽉 찬/빈 프로필 | 예 | `check`가 `Profile.from_dict`·`score`로 읽어 0건 |
| 6. `docs/75-label-rules.md` 축 7개·유형 8개·규칙 번호 | 예 | 문서 존재. 골든셋이 쓰는 `rule` 38종이 전부 문서에 있다 (코드 에이전트 확인). #8·#9는 문서 문장 수정 |
| 7. `notices.json` 20건 · 기준 · 공고문 사실 · 어긋난 칸 · 같은 명령이면 같은 20건 | 예 | `runs/75/notices.json`에 `criteria`·`facts`·`db_mismatch`. 재실행 시 `label_facts`·`db_silent`가 지워지는 문제는 #1로 고침. 같은 입력이면 같은 20건이 나오는 코드이고 테스트가 있다 |
| 8. `golden.check`가 기준 1~5·글자 대조를 검사하고 어긋나면 exit 1 | 예 | 코드 `check.py:340` 이후, 실행 exit 0. 실패 시 exit 1 경로의 연결 코드는 테스트가 없다(#13 defer) |
| 9. `golden.report`가 `docs/75-golden.md`를 쓴다 | 예 | 재생성한 파일이 커밋된 파일과 같다. 첫 줄이 결론 한 문장 |
| 10. `review-sample.md` 20개 · `INELIGIBLE` 5개 이상 · 시드 고정 | 예 | 항목 20개(`맞음/틀림` 빈 칸 21곳 = 20 + 안내 1), 재생성 결과 동일. 판정값이 모자란 경우에 20개가 안 채워지던 것은 #6으로 고침 |
| 11. 전체 테스트 · `ruff check` · `ruff format --check` | 예 | 리뷰 수정 전 `pytest` 1213 passed, 수정 후 1219 passed(테스트 6개 추가), `ruff check`·`ruff format --check` 통과, `golden.check` exit 0 |
| 실패 징후 1: 판정값·조 불일치 5% 이하 | 값만 적는다 | 처음 4/524 = 0.8%, 조 0/524 = 0.0%. 지금 파일로 다시 맞추면 11/524(#11). 두 쪽 다 Claude라는 한계는 리포트에 있다 |
| 실패 징후 2: 어긋난 구절 0 | 예 | 처음 0개, 고친 뒤 0개. 첫 커밋 시점 `golden.jsonl`로 다시 재도 0개 (문서 에이전트 확인) |
| 실패 징후 3: `INELIGIBLE` 30개 이상, 4개 이상의 축 | 예 | 91개, 축 4개 (`account` · `homeless` · `householder` · `special_type`) |
| 실패 징후 4: `rule` null 10% 이하 | 예 | 0개 (0.0%) |

## 리뷰 기록 맨 아래

- 리뷰 수정 중 `ruff check` 줄 길이(100칸) 초과를 한글 두 칸 폭 때문에 세 번 나눠 고쳤다: `5d55d03` · `9396cd6` · `1924fc5`. 이 셋은 지적 행이 아니라 내 수정 때문에 생긴 것이다.
- #6과 #7은 같은 파일(`report.py`)이라 한 커밋 `4a1073d`에 들어갔다. 지적 하나에 커밋 하나 규칙의 예외다.
- 리뷰 에이전트 4개를 쓴 방식: 파일을 고치지 않고 읽기만 시켰고 지적마다 내가 직접 코드나 데이터로 확인했다. 확인한 것만 위 표에 옮겼다.
