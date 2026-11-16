# 180 리뷰 — PR #24

**대상:** `main...HEAD` — 10 commits, 21 files, +19032 −34 (대부분 `runs/180/` 측정 결과)
**plan:** docs/plans/180-1116-plan-eligible-missing-info.md

리뷰 에이전트 5개(코드·테스트·조용한 실패·주석·타입 설계)를 `pr-review-toolkit:review-pr`로 돌렸다. Critical은 없다.
단어장: `docs/concepts.md` `## 용어` 절이 있어 「쓰지 말 말」을 diff에서 찾았다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/eligible_report.py:70` | `ruled_by`가 기록된 `rule` 칸이 아니라 이유 문장 일치로 규칙을 센다. 규칙 이유 문장을 고치면 옛 `runs/180` 기록이 모델 이유로 세어져 징후 2가 조용히 틀린다 | defer — 골든셋 `runs/180/run.jsonl`에는 `rule` 칸이 없고 `eval/run.py`는 plan이 고치지 않기로 했다. 시연 JSON에는 `rule` 칸이 있어 그쪽만 먼저 읽게 하는 것은 후속으로 둔다 |
| 2 | Important | `src/cheongyak_rag/generate/eligible_report.py:84` | 골든셋 행 수·시연 쌍 수·`stop`·`cell_errors`·verdict `error`를 검사하지 않는다. 잘리거나 중간에 멈춘 입력이면 징후 1~3이 0으로 나와 통과로 읽힐 수 있다 | defer — 커밋된 입력은 직접 확인했다(골든셋 524행 전부 `matched`, 시연 18쌍 135판정, `error`·`stop` 없음). 분모(`0/55`, `421/524`)가 표에 찍히고 징후 4는 절대값이라 잘린 입력에서 미완이 된다. 재측정 가드는 후속 |
| 3 | Important | `tests/test_generate_aggregate_report.py:34` | 두 테스트 모듈이 `ELIGIBLE_RULES = ()`로 가능 규칙을 끄고 돌아서, 가능 규칙이 쓴 행이 `answer.md`·`last_run.json`까지 가는 경로를 보는 테스트가 없다. `last_run.json`이 `original_verdict`를 안 써도 테스트가 통과한다 | defer — `_note`·`judge_one` 단위 테스트는 있고 실제 `runs/180/demo/last_run.json`에 `ruled` 8행과 `original_verdict`가 들어 있다. 끝까지 도는 테스트 한 건은 후속 |
| 4 | Important | `src/cheongyak_rag/generate/eligible_report.py:84` | `golden_records`·`demo_records`가 직접 테스트되지 않는다. `matched` 필터나 `changed` 조건을 지워도 테스트가 통과한다 | defer — 위 3번과 같은 후속 테스트 티켓에 묶는다. 커밋된 리포트 값은 주석 에이전트가 원본 `run.jsonl`에서 따로 세어 같았다 |
| 5 | Important | `src/cheongyak_rag/generate/verdict.py:409` | 모델이 UNVERIFIABLE을 내고 인용이 0개이면 `forced`가 안 서서 가능 규칙이 걸리고, 인용 없는 ELIGIBLE이 나간다. 설계 §2는 「근거 없는 ELIGIBLE이 화면에 나가지 않게」 인용이 모두 기각된 판정에는 안 건다고 했고, plan 통과 기준 2는 모델 UNVERIFIABLE도 ELIGIBLE로 바꾼다고 했다. 둘이 어긋나고 코드·테스트는 plan 쪽을 골랐다. `docs/concepts.md:212`도 이 경우를 말하지 않는다 | defer — 설계와 plan 중 어느 쪽이 맞는지는 jw가 정한다. 이번 측정에서 최종 ELIGIBLE 63건은 모두 인용이 있다. 고치려면 `elif out.citations:`로 조건을 바꾸고 `test_eligible_rule_also_applies_to_a_model_unverifiable_without_citations`가 기대를 뒤집는다 |
| 6 | Suggestion | `src/cheongyak_rag/generate/rules.py:244`, `tests/test_generate_verdict.py:657,665` | 단어장 「쓰지 말 말」 `빈 칸`을 새 주석에 썼다 | fix `92010fe` |
| 7 | Suggestion | `src/cheongyak_rag/generate/verdict.py:8` | 모듈 docstring이 불가 규칙이 마지막 단계라고 한다. 가능 규칙 단계가 빠졌다 | fix `efd32fa` |
| 8 | Suggestion | `docs/180-eval.md:1` | `eval.report`가 #76 제목·jw 기준·「첫 측정이라 baseline 없음」 문구를 그대로 낸다. 이 PR의 baseline은 `runs/82`다 | defer — 생성물이고 고치려면 `eval.report`를 바꿔야 한다. 이번 티켓의 기준·baseline은 `docs/180-eligible.md`에 있다 |
| 9 | Suggestion | `docs/180-eligible.md:4` | 「정답 라벨」이 jw 기준 괄호에서는 시스템 판정, 징후 3·5에서는 골든셋 라벨이다 | 기록만 — 4행은 jw 원문 되물음이라 고치지 않는다. 징후 3·5는 표에 `골든셋`이라고 적혀 있다 |
| 10 | Suggestion | `src/cheongyak_rag/generate/rules.py:224,245,254` | `EligibleRule.when` 주석(`concepts.md`가 옮긴다)·`rule_eligible`의 시그니처 설명·`eligible_fields` 설명이 사실과 조금 다르다 | 기록만 — `when` 주석은 기존 `Rule`(59행)과 같은 문구다 |
| 11 | Suggestion | `docs/concepts.md:212` | 가능 규칙을 안 거는 경우에 근거 0개로 호출하지 않은 `no_context`가 빠졌다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/generate/verdict.py:496`, `src/cheongyak_rag/generate/aggregate.py:213` | 조사 「가」를 가능 규칙 번호가 모두 2로 끝난다는 가정으로 고정했다. 규칙을 더하면 조사가 틀린다 | 기록만 — 주석이 가정을 적고 있고 규칙은 둘이다 |
| 13 | Suggestion | `src/cheongyak_rag/generate/verdict.py:179` | `ruled=True`가 불가·가능 두 뜻이고 읽는 쪽 코드가 `verdict == "ELIGIBLE"`로 가른다. `rule_kind` 칸이 없다 | 기록만 — 규칙 종류가 둘이고 둘 다 판정을 바꾼다 |
| 14 | Suggestion | `src/cheongyak_rag/generate/rules.py:232` | 가능 규칙 이유 문장이 제53조·제2조제3호를 늘 적는다. 그 하위 질의 검색 결과에 그 조문이 없으면 웹이 「이유에서 언급했지만 검색 결과에는 없던 근거」 안내를 코드가 쓴 문장에 붙인다 | 기록만 — 현재 두 표본의 최종 ELIGIBLE은 모두 그 조문이 검색 결과에 있다 |
| 15 | Suggestion | `src/cheongyak_rag/generate/eligible_report.py:188` | `measure()`가 돌려주는 `count` 람다(`# noqa: E731`)를 아무도 읽지 않는다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `rules.py`에 `homeless-2`·`householder-2`가 설계 §2 조건·이유 문장 그대로 있다. 규칙마다 true·false·비어 있음 테스트가 있다 | 예 | `src/cheongyak_rag/generate/rules.py:229-239`, `tests/test_generate_rules.py` · `uv run pytest -q` 1485 passed |
| 2. `judge_one`이 불가 규칙 다음에 가능 규칙을 건다. 호출 성공 + `forced` 아님일 때만. 모델 NEED_INFO·UNVERIFIABLE·INELIGIBLE이 ELIGIBLE로 바뀌고 `forced`·호출 오류면 안 바뀌며 칸이 비면 guard가 NEED_INFO로 바꾼다 | 예 | `src/cheongyak_rag/generate/verdict.py:405-415`, `tests/test_generate_verdict.py`의 다섯 경우 |
| 3. 응답 체크리스트 `note`가 가능 규칙을 불가 규칙과 다른 문구로 적는다. 모델도 ELIGIBLE이면 「모델 판정도 ELIGIBLE」 | 예 | `src/cheongyak_rag/generate/aggregate.py:211-215`, `tests/test_generate_aggregate.py` |
| 4. harness를 `--out-dir runs/180`으로 돌려 `docs/180-eval.md`를 만들었고 시연 18쌍을 `runs/180/demo/`로 돌렸다. `runs/81`·`runs/82`·`docs/81-answer.md`·`docs/82-eval.md`는 그대로다 | 예 | `runs/180/run.jsonl` 524행, `runs/180/demo/last_run.json` 18쌍 · `git diff --stat main...HEAD`에 `runs/81`·`runs/82`·`docs/81-answer.md`·`docs/82-eval.md` 없음 |
| 5. `docs/180-eligible.md`에 jw 기준 측정값·구간, 징후 2~5, 지표 7개 전후 표, 가능 규칙이 바꾼 하위 질의 수, 설계 §4 세 줄이 있다 | 예 | `docs/180-eligible.md` 13-75행 |
| 실패 징후 1. 최종 ELIGIBLE 중 「정보가 없음」 칸이 있는 하위 질의 (통과 0) | 값만 적는다 | 골든셋 0/55 · 시연 0/8 · 합 0 (`docs/180-eligible.md:17`). 착수 때 0/44 · 0/8 |
| 실패 징후 2. 이유를 LLM이 쓴 최종 ELIGIBLE (정상 0) | 값만 적는다 | 골든셋 0/55 · 시연 0/8 (`docs/180-eligible.md:18`). 착수 때 44/44 · 8/8 |
| 실패 징후 3. 틀린 ELIGIBLE (정상 0) | 값만 적는다 | 0/55 (`docs/180-eligible.md:19`). 착수 때 0/44 |
| 실패 징후 4. 판정 정확도 (정상 421 이상) | 값만 적는다 | 432/524 (`docs/180-eligible.md:20`). `runs/82` 421/524 |
| 실패 징후 5. 치명오답 (정상 0) | 값만 적는다 | 0/91 (`docs/180-eligible.md:21`). `runs/82` 0/91 |
| 이번에 안 하는 것: 프롬프트·캐시 키·`eval/run.py`·골든셋·웹 화면·`docs/decisions.md`를 고치지 않는다 | 예 | `git diff --stat main...HEAD`에 해당 파일 없음. `docs/decisions.md`는 +1행(Kickoff 때 기준 칸) |

## 확인한 것

- 리뷰 시작 때 `uv run pytest -q` 1485 passed, `ruff check`·`ruff format --check` 통과. 마지막 fix 커밋 뒤 해당 테스트 파일 151 passed.
- 주석 에이전트가 `docs/180-eligible.md` 숫자를 `runs/180/run.jsonl`·`runs/82/run.jsonl`·`metrics.json`에서 따로 세어 같았다.
- 코드 리뷰 에이전트는 plan 통과 기준 1~5가 코드와 테스트로 채워졌고 「쓰지 말 말」이 diff에 없다고 확인했다. Important는 위 5번 하나다.
