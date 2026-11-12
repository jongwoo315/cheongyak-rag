# #76 리뷰 — PR #21

**대상:** `main...HEAD` — 20 commits, 16 files, +2522 −0 (리뷰 fix 커밋 11개와 이 파일 커밋 포함)
**plan:** docs/plans/76-1112-plan-eval-harness.md

리뷰는 `pr-review-toolkit:review-pr`의 하위 에이전트 4개(코드·테스트·무음 실패·주석)와 직접 읽기로 했다. 단어장 검사는 아래 지적 18에 적었다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/eval/run.py:159` | 멈추거나 판정이 실패한 세 번째 실행이 앞서 완주한 `second_run` 기록을 `None`으로 지운다. 그러면 리포트의 재현성 징후가 `미측정`으로 돌아가 통과 기준 5의 증거가 사라진다 | fix `6328a58` |
| 2 | Important | `src/cheongyak_rag/eval/report.py:278` | 첫 실행이 비용 상한에서 멈추면 비용 징후가 plan이 정한 `미완`이 아니라 `미측정`으로 나온다. 뒤 실행이 멈추면 첫 실행이 통과여도 `미완`으로 나온다 | fix `742af03` | <!-- style-exempt -->
| 3 | Important | `src/cheongyak_rag/eval/metrics.py:102` | 문항 판정 실패 줄을 알아보는 문구 `공고 판정 실패`가 `run.py`와 `metrics.counts`에 따로 적혀 있다. 한쪽 문구를 바꾸면 `item_failures`가 0이 되고 실패한 실행이 완주로 기록된다 | fix `71252e6` |
| 4 | Important | `src/cheongyak_rag/eval/metrics.py:3` | 「못 맞춘 라벨은 분모에 남는다」는 설명이 citation precision에는 맞지 않는다(그 지표의 분모는 시스템이 인용한 조문이다). 판정 정확도의 값 모양도 설명과 다르다 | fix `2306148` |
| 5 | Important | `src/cheongyak_rag/eval/run.py:38` | `matched=false`를 「시스템에 같은 하위 질의가 없다」로만 설명했다. 문항 판정이 통째로 실패한 줄과 실행이 멈춰 안 돈 줄도 같은 값이다 | fix `bc3f057` `b93f2a0` |
| 6 | Important | `docs/concepts.md:141` | 개념 표의 「정의한 곳」 줄 번호가 4번 수정 뒤 `metrics.py`의 함수 정의 줄과 어긋난다 | fix `086d902` |
| 7 | Important | `tests/test_eval_run.py:45` | `make_line`이 만드는 `law_top5`·`faq_top3` 나누기, guard 전 판정값(`sys_pre_verdict`)을 확인하는 테스트가 없다. 나누기가 틀려도 recall@5·hit@5 테스트는 손으로 만든 줄을 쓰므로 통과한다 | fix `7e5ff98` |
| 8 | Important | `tests/test_eval_run.py:107` | 문항 하나가 예외로 실패한 뒤 다음 문항을 계속 돌리는지 확인하는 테스트가 없다 | fix `fd46954` |
| 9 | Important | `tests/test_eval_run.py:126` | 근거가 없어 호출하지 않은 판정과 캐시에서 읽은 판정이 호출 수·비용에 안 들어가는지 확인하는 테스트가 없다 | fix `5ac1525` |
| 10 | Important | `tests/test_eval_run.py:195` | 상한에서 멈춘 실행이 exit 1을 내고 `metrics.json`에 멈췄다는 기록이 남는지 `main` 수준 테스트가 없다 | fix `098b7e8` | <!-- style-exempt -->
| 11 | Important | `src/cheongyak_rag/eval/run.py:111` | 문항 안에서 판정 호출이 일부 끝난 뒤 예외가 나면, 이미 쓴 비용이 `spent`에 안 들어가 첫 실행 비용이 문항 하나 몫까지 적게 나올 수 있다 | defer — 부분 결과를 돌려받으려면 `generate.verdict.judge`를 고쳐야 하는데 plan이 판정 흐름 코드를 안 고치기로 했다. 이번 실행은 판정 실패 0이라 영향이 없다 |
| 12 | Important | `src/cheongyak_rag/eval/report.py:289` | 재현성 징후는 두 번째 실행이 캐시에서만 읽으므로 호출 0 · 지표 같음이 사실상 항상 참이다. LLM이 같은 입력에 같은 답을 내는지는 못 잰다 | push-back — plan 징후 5가 이 정의(호출 0 · 다른 지표 0)를 정했고, 재는 것은 캐시 키가 안 바뀌었는지다. LLM 응답이 매번 같은지는 이 티켓이 재는 것이 아니다 |
| 13 | Important | `src/cheongyak_rag/eval/run.py:218` | 앞선 실행이 `first_run` 없이 멈춘 상태에서 다른 문항 수나 다른 모델로 돌리면, 이어 받던 비용이 말없이 버려지고 첫 실행 비용이 적게 나온다 | defer — 비용 상한 $10 안에서는 판정을 바꾸지 않고, 실제 실행은 이 경우가 없었다. 한 `--out-dir`에 다른 조건 실행을 섞지 않는 것으로 막는다 | <!-- style-exempt -->
| 14 | Important | `tests/test_eval_run.py:226` | 이전 실행이 `first_run` 없이 멈췄고 문항 수가 다를 때 덮어쓰기를 막는 가드가 안 걸린다는 것을 테스트가 못 박지 않는다 | defer — 13과 같은 동작이라 13에서 동작을 정할 때 같이 테스트한다 |
| 15 | Suggestion | `src/cheongyak_rag/eval/run.py:72` | 캐시에서 읽은 줄도 `usd`에 처음 불렀을 때의 금액이 들어가서, 커밋된 `run.jsonl`(두 번째 실행, 전부 캐시)의 `usd` 합이 $3.7176이다. 리포트가 적은 첫 실행 비용 $3.3605(그 사이 캐시 51개는 앞선 시험 실행이 냈다)와 두 번째 실행 비용 $0과 모두 다르다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/eval/report.py:25` | 비용 상한 `BUDGET_USD = 10.0`이 코드에 박혀 있고 `metrics.json`에는 실행 때 쓴 `--budget-usd`가 없다. 다른 상한으로 돌린 실행의 비용 구간이 틀리게 적힌다 | 기록만 | <!-- style-exempt -->
| 17 | Suggestion | `src/cheongyak_rag/eval/run.py:124` | 비용 상한 검사가 문항 하나를 다 돌린 뒤에 한다. 마지막 문항의 비용만큼 상한을 넘길 수 있고, 마지막 문항에서 넘기면 다 돌았는데도 멈춤으로 기록된다(비용 구간은 상한 초과라 `미완`이 맞다) | 기록만 | <!-- style-exempt -->
| 18 | Suggestion | `src/cheongyak_rag/eval/run.py:47` | 단어장 검사: run 줄 칸 이름이 `gold_verdict`·`gold_citations`·`gold_reason`이다. 용어 절의 쓰지 말 말(`gold label`)과 같은 말이다. 칸 이름이 커밋된 `runs/76/run.jsonl`과 테스트에 박혀 있다 | defer — 코드 식별자이자 커밋된 데이터의 칸 이름이다. 바꾸면 `run.jsonl`을 다시 써야 하고 지표에는 영향이 없다. 칸 이름을 다음 티켓이 정할 때 같이 바꾼다 |
| 19 | Suggestion | `src/cheongyak_rag/eval/report.py:369` | `notes.json`이 있는데 깨졌어도 조용히 빈 값으로 넘어가 「의심스러운 정답 라벨」 절이 「적을 것이 없다」로 나온다. 파일이 없을 때만 넘겨야 한다 | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/eval/report.py:339` | plan 통과 기준 5는 「리포트에 두 실행 값을 같이 적는다」인데 실행 기록 절은 호출 수·캐시 수·비용과 「지표 값 같음」만 적는다. 두 실행의 지표 값은 `metrics.json`에만 있다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/eval/report.py:53` | 「지표를 읽는 법」의 `72%(378/524)`와 「세 축은 전부 `NEED_INFO`」가 `rows`에서 계산한 값이 아니라 고정 문장이다. 골든셋이 바뀌면 표는 바뀌고 이 문장은 그대로 남는다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/eval/run.py:204` | 문항이 0개인 입력(`--limit 0`, 빈 골든셋)도 exit 0이고 분모 0 지표만 있는 기록을 쓴다 | 기록만 |
| 23 | Suggestion | `src/cheongyak_rag/eval/run.py:94` | 시스템이 같은 `(axis, query)`를 둘 이상 만들면 하나로 합쳐져 `unmatched_system_queries`가 적게 센다. 지금 데이터에는 중복이 0이다 | 기록만 |
| 24 | Suggestion | `src/cheongyak_rag/eval/run.py:142` | `attach_runs` docstring이 「직전 기록이 완주 실행이면」이라고 쓰지만 코드는 `first_run`이 있는지로 가른다. 비용을 이어 받는 문장은 `first_run`이 아직 없을 때만 맞다 | 기록만 |
| 25 | Suggestion | `docs/76-eval.md:27` | 「비용 $0.0000 (이 실행)」은 마지막(두 번째) 실행의 비용이다. 같은 리포트의 징후 4가 적은 첫 실행 비용 $3.3605와 달라 읽는 사람이 헷갈릴 수 있다 | 기록만 |
| 26 | Suggestion | `tests/test_eval_report.py:112` | `render`의 구간 계산을 쓰는 곳 중 징후 1·2 구간, `second_run` 있을 때의 징후 5, 따로 센 결과가 달라 「다름」이 뜨는 칸, `report.main` 읽기 실패(exit 2)는 테스트가 없다. 징후 4는 `742af03`에서 더했다 | 기록만 |
| 27 | Suggestion | `tests/test_eval_run.py:152` | `attach_runs`의 일부 갈래(세 번째 완주 실행이 `second_run`을 바꾸는 것, 멈춘 실행이 두 번 이어질 때 비용을 더하는 것, 모델이 다를 때 기록을 처음부터 시작하는 것)와 `main`의 「준비 실패」(exit 3) 갈래에 테스트가 없다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1: 문항 50개를 돌려 `run.jsonl`(정답 라벨 524줄)과 `metrics.json`을 쓴다 | 예 | `runs/76/run.jsonl` 524줄, `runs/76/metrics.json` items 50 |
| 통과 2: `metrics.json`에 지표 7개가 값·분자·분모로 있고 옆에 내는 수가 있다 | 예 | `metrics.json` metrics 7개, counts 8칸 |
| 통과 3: report가 `eval.metrics`를 import하지 않고 따로 세어 다른 지표 수를 센다 | 예 | `src/cheongyak_rag/eval/report.py:5-9`, `tests/test_eval_report.py::test_report_does_not_import_the_harness_metrics`, 리포트 「같음」 7/7 |
| 통과 4: 리포트에 정해진 절이 모두 있다 | 예 | `docs/76-eval.md` 절 12개, 치명오답 2개 전부 |
| 통과 5: 두 번째 실행은 LLM 호출 0회이고 지표가 같다 | 예 (두 실행의 지표 값은 「같음」으로만 적혀 있다, 지적 20. 이 징후가 캐시만 재는 한계는 지적 12) | `metrics.json` second_run calls 0, 리포트 실행 기록 |
| 통과 6: 판정 흐름 코드와 `runs/75/`를 고치지 않았다 | 예 | `git diff main...HEAD -- src/cheongyak_rag/retrieval src/cheongyak_rag/generate src/cheongyak_rag/trace.py src/cheongyak_rag/api.py runs/75` 빈 출력 |
| 통과 7: 지표·맞추기·따로 세기 테스트, OpenAI·DB 안 씀 | 예 | `uv run pytest -q` (아래 확인 절) |
| 통과 8: 개념 표 「eval 지표 7개」 | 예 | `docs/concepts.md:141-147`, 줄 번호가 모두 `def` 줄과 같다(`086d902` 뒤 확인) |
| 징후 1: 못 맞춘 + 조문 0개 | 0 → 통과 구간 | `docs/76-eval.md` 실패 징후 1 |
| 징후 2: 분모 0 + 다른 값 | 0 → 통과 구간 | `docs/76-eval.md` 실패 징후 2 |
| 징후 3: 판정 실패 | 0 → 통과 구간 | `docs/76-eval.md` 실패 징후 3 |
| 징후 4: 첫 실행 비용 | $3.3605 → 통과 구간 | `metrics.json` first_run |
| 징후 5: 재현성 | 호출 0 · 지표 같음 → 통과 구간 | `metrics.json` second_run |
| 징후 6: 지표 값 자체 | 값만 적었다 (판정하지 않음) | `docs/76-eval.md` 지표 7개 표 |

단어장 검사: 이 repo에 `docs/concepts.md` `## 용어` 절이 있어 diff의 문서·주석·docstring에서 쓰지 말 말을 찾았다. 문장에서는 나오지 않았고 식별자 `gold_*` 한 곳(지적 18)만 나왔다.

## 확인

- 리뷰 fix 뒤 `uv run pytest -q` 1258 passed(리뷰 전 1250), `uv run ruff check` 통과, `uv run ruff format --check` 225개 이미 정리됨, `golden.check` exit 0, `eval.report` exit 0.
- 리뷰 fix로 `src/`의 지표 계산은 바뀌지 않았다. `runs/76/`과 `docs/76-eval.md`는 다시 쓰지 않았다(`eval.report`를 다시 돌려도 `docs/76-eval.md`가 그대로임을 확인).
