# 81 리뷰 — PR #15

**대상:** `main...HEAD` — 11 commits, 10 files, +16610 −0 (리뷰 전 7 commits에 리뷰 fix·test 4개가 얹혔다)
**plan:** docs/plans/81-1103-plan-aggregate.md

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/generate/aggregate_report.py:335` | 호출이 실패해 판정이 없는 하위 질의(`verdict=None`)가 있어도 징후 1·2가 통과로 남고 exit 0이다. 리포트에도 어느 질의인지 안 나온다 | fix `e9e671a` |
| 2 | Important | `src/cheongyak_rag/generate/aggregate.py:285` | 응답 텍스트의 「검색 밖 언급」 줄을 확인하는 테스트가 없다. 줄을 지워도 테스트가 안 깨진다 (jw 기준 뒤 절이 보는 표시다) | fix `736f314` |
| 3 | Important | `src/cheongyak_rag/generate/aggregate.py:176` | 근거 원문을 공고의 법령 버전(MST) 행에서만 읽는 조건을 확인하는 테스트가 없다. 조건을 빼도 테스트가 통과한다 | fix `e645900` |
| 4 | Important | `src/cheongyak_rag/generate/aggregate.py:26` | 신청 가능한 경로가 `ELIGIBLE`·`CONDITIONAL`뿐인지 `ELIGIBLE`·`CONDITIONAL`·`INELIGIBLE`만 확인한다. `NEED_INFO`가 섞여도 테스트가 안 깨진다 | fix `ff59a33` |
| 5 | Important | `src/cheongyak_rag/generate/aggregate_report.py:155` | 징후 4가 HTTP 상태만 본다. law.go.kr는 없는 `lsiSeq=999999999`에도 200(내용이 거의 없는 6KB 페이지)을 줘서, 틀린 MST 링크도 통과한다. 실제 `286965`는 145KB 페이지로 확인됐다 | defer — plan 징후 4가 「받은 HTTP 상태」로 정의돼 그대로 쟀다. 응답 본문·`Content-Type`까지 보는 것은 측정 정의를 바꾸는 일이라 #84(화면에 링크를 실을 때)에서 정한다 |
| 6 | Important | `src/cheongyak_rag/generate/aggregate.py:235` | `chunks`에서 원문을 못 찾으면 `text=""`가 되고, `verdict` CLI 출력은 경고 없이 빈 근거 줄을 찍는다. `--report`의 D는 이 경우를 「chunks에 없다」로 잡는다 | defer — 이번 실데이터 389개는 전부 원문이 있다(D 0/389). 사용자에게 보이는 화면에서 「원문 없음」을 어떻게 보일지는 #84에서 정한다 |
| 7 | Important | `src/cheongyak_rag/generate/aggregate.py:81` | 켜진 축인데 판정이 하나도 없으면 집계에서 조용히 빠져 나머지로 전역 판정이 나온다. 측정 코드(`expected_routes`)도 같은 구멍이라 B가 못 잡는다 | won't-fix — `verdict.judge`가 켜진 축의 질의마다 `Verdict`를 만든다(`src/cheongyak_rag/generate/verdict.py:453-457`, 검색 결과가 비어도 「검색된 조문·FAQ가 없어」 판정이 생긴다). 지금 구조에서는 안 생긴다 |
| 8 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:37` | 특별공급 유형별 세대수가 없어 `Q_SPECIAL_NO_TYPE` 질의로 떨어진 경로(`유형 미상`)가 `ELIGIBLE`·`CONDITIONAL`이면 「신청 가능한 경로: 특별공급 유형 미상」으로 나온다. 신청할 수 없는 경로 이름이다 | defer — 설계 §B8이 정하지 않은 자리다. 표본 18쌍에는 없다(경로 키가 전부 실제 유형). 화면에서 어떻게 보일지와 같이 #84에서 정한다 |
| 9 | Suggestion | `src/cheongyak_rag/generate/aggregate_report.py:303` | 응답에 링크가 하나도 안 실리면 `zone_links({})`가 「통과」를 낸다 | 기록만 |
| 10 | Suggestion | `src/cheongyak_rag/generate/aggregate_report.py:106` | C의 정규식이 `aggregate.py:110`의 `_MENTION`과 같은 패턴이고, D의 SQL 조건도 `read_texts`와 같다. 둘이 같이 틀리면(「제 53조」, 「FAQ 5번」) C·D 0이 그 틀림을 못 잡는다. 리포트 「읽는 법」에는 B에만 이 단서가 있다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:24` | `PRIORITY`와 `verdict.VERDICTS`가 따로 있는 문자열 묶음이라, 판정값이 늘면 `merge`가 `KeyError`를 내고 `verdict` CLI는 LLM 호출 뒤에 죽는다. 두 묶음이 같다는 테스트가 없다 | 기록만 | <!-- style-exempt -->
| 12 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:74` | `ponytail:` 주석이 「세대주 축은 노부모 부양에만 걸린다」고 쓰는데, 세대주 축은 투기과열·청약과열일 때도 켜진다(`src/cheongyak_rag/retrieval/axes.py:196-205`). 줄여야 할 곳은 「노부모 부양 때문에만 켜졌을 때」다 | 기록만 |
| 13 | Suggestion | `tests/test_generate_aggregate.py:105` | 테스트 이름이 「질의를 키로 둔다」인데 실제로는 `유형 미상`으로 매핑된 경우를 보고 키도 안 본다. 283번 줄의 `"공고: " not in old.split("\n")[0]`는 첫 줄이 빈 줄이라 항상 참이다 (바로 아래 줄이 제대로 확인한다) | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/generate/aggregate_report.py:194` | `except Exception`이 셀 실패를 이름과 메시지만 남기고 traceback을 버린다. `symptoms()`(649번 줄)·`http_status`의 `InvalidURL`은 잡히지 않아 LLM 비용을 쓴 뒤 리포트 없이 죽을 수 있다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:84` | 호출이 실패한 질의가 있어도 경로·전역 판정은 그냥 `UNVERIFIABLE`로 나온다. 법적 이유로 확인 못 한 것과 API 장애가 응답에서 구분되지 않는다(체크리스트에만 「판정 실패」가 있다) | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/generate/aggregate.py:176` | `read_texts`가 라벨당 한 행을 가정한다. 색인을 `paragraph`로 바꾸면 한 라벨에 행이 여럿이라 임의의 한 항이 실린다. 지금 `runs/73/selected.json`은 `article`이고 `chunks`에 중복 라벨이 없음을 직접 확인했다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/generate/verdict_report.py:101` | 징후 3의 구간(두 번째 실행 1~3 → 다시 잰다, 4 이상 → 미완, 첫 실행 비용 $3 초과 → 미완)이 #81 plan에 없는 #80 기준이다. 이번 결과(0·0)에는 영향이 없다 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/retrieval/axes.py:196` | 공고 `2026000202`는 노부모 부양 4세대 때문에 세대주 축이 켜졌고, 그 판정이 일반공급·전역 판정에 들어간다. 세대주가 아닌 프로필이면 일반공급이 잘못 `INELIGIBLE`이 될 수 있다. 세 프로필로 다시 계산해 지금 표본에서는 전역 판정이 같음을 확인했다. 설계 §B8이 받아들인 한계다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `generate/aggregate.py`에 B8 집계·B9 응답 조립이 있고 LLM·네트워크를 부르지 않는다 | 예 | `src/cheongyak_rag/generate/aggregate.py`의 import는 `re`·`dataclasses`·`urllib.parse.urlencode`·`sqlalchemy`·`profile`·`axes`뿐이다. `urlencode`는 문자열을 만들 뿐 요청하지 않는다 |
| 2. B8: 설계 §B8 규칙 그대로 | 예 | `aggregate.py:24-95` — 우선순위 순서, 일반 축 5개, 특별공급 = 일반 + `income_asset` + 유형 질의, 전역 판정 = 일반공급, `verdict=None` → `UNVERIFIABLE`, 켜진 축 없으면 `None`. 테스트 `test_each_special_type_is_merged_on_its_own` · `test_missing_verdict_counts_as_unverifiable` · `test_nothing_on_gives_none` |
| 3. B9 응답 칸 전부, `asdict` 뒤 `json.dumps`가 된다 | 예 | `Answer`의 필드가 설계 칸과 같고 `test_answer_has_every_field_and_dumps_to_json`이 `json.dumps(dataclasses.asdict(a))`를 한다 |
| 4. 규칙 일치 테스트: 279,936개 조합에서 다른 조합 0 | 예 | `test_all_combinations_match_the_priority_rule` — 조합 279,936개, 다른 조합 0, 약 1.3초. 기대값은 `aggregate_report.ORDER`에서 따로 계산하고, 우선순위를 바꾼 음성 대조 `test_rule_check_catches_a_wrong_priority`가 실제로 깨진다 | <!-- style-exempt -->
| 5. `verdict` CLI 출력 맨 위에 응답, 아래는 지금 출력 그대로 | 예 | `uv run python -m cheongyak_rag.generate.verdict 2026000103 --profile runs/80/profiles/empty.json` exit 0, 맨 위 줄이 `전역 판정(일반공급): UNVERIFIABLE`. `test_verdict_cli_prints_the_answer_above_the_old_report` |
| 6. `--report`가 징후 1~4를 재고 두 파일을 쓴다. 징후 1 또는 2가 미완이면 exit 1 | 예 | `docs/81-answer.md` · `runs/81/last_run.json` 존재. exit 1 테스트: B=1 · D=1 · A=2 · 판정 실패(지적 1로 추가). 징후 2의 C만 1인 경우의 exit 1은 `main()` 통합 테스트가 없다 |
| 7. `SYSTEM` · user 메시지 조립 · `REQUIRED_FIELDS`를 바꾸지 않는다. `system_sha`가 `92f338a4` | 예 | `git diff main...HEAD -- src/cheongyak_rag/generate/verdict.py`가 import 1줄과 `main`의 출력 3줄뿐. `runs/81/last_run.json`의 `system_sha` = `92f338a4` |
| 8. `uv run pytest -q` 전체 통과 · `ruff check` · `ruff format --check` | 예 | 리뷰 fix 뒤 `981 passed` · `All checks passed!` · `154 files already formatted` |
| 징후 1: A 0 · B 0 | 예 (기록된 값) | `runs/81/last_run.json` — A 0/279,936, B 0/72, 구간 통과. 같은 우선순위 목록에서 기대값을 내므로 둘이 같이 틀릴 수 있다는 단서는 리포트에 있다 |
| 징후 2: C 0 · D 0 · E 1 이상 | 예 (기록된 값) | `runs/81/last_run.json` — C 0/135, D 0/389, E 15, 구간 통과. 정규식·SQL이 구현과 같은 꼴이라는 단서는 지적 10 |
| 징후 3: 첫 실행 호출 0 · 두 번째 0 · 분포 같음 | 예 (기록된 값) | `runs/81/last_run.json` — 첫 실행 0, 두 번째 0, 구간 통과 |
| 징후 4: 실린 링크 형식이 전부 200 | 예 (기록된 값) | `law` 200 · `faq` 200. 200이 「실제 페이지」를 뜻하는지는 지적 5 |

판정(통과·반려)은 하지 않는다. 위 값은 기록된 측정값이고 결과가 기준에 걸리는지는 사람이 정한다.

## 처리 기록

- 리뷰 방법: `pr-review-toolkit:review-pr` 에이전트 5개(code · tests · comments · errors · types) 병렬
- fix 4건은 지적 하나당 커밋 하나다. 각 테스트는 고친 코드(또는 조건)를 일부러 깨뜨려 실제로 실패하는 것을 확인한 뒤 되돌렸다
- 리뷰 fix 뒤 `runs/81/last_run.json` · `docs/81-answer.md`는 다시 쓰지 않았다. 지적 1은 `missing`이 0인 이번 실행의 값을 바꾸지 않는다
