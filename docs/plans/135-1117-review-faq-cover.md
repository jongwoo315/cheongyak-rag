# #135 리뷰 — PR #25

**대상:** `main...HEAD` — 13 commits, 16 files, +1963 −128 (리뷰 세션 fix 커밋 6개 포함, 이 파일은 제외)
**plan:** docs/plans/135-1116-plan-faq-cover.md

단어장 검사: `docs/concepts.md` `## 용어` 「쓰지 말 말」 칸의 말이 diff에 원뜻 밖으로 나온 곳은 없다(`포함`만 걸렸고 FAQ 원문 인용·「가지 포함」이라 원뜻이다). 지적 없음.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/ingest/faq_cover_report.py:547` | `main()`이 `inputs`·`merge`가 아닌 모든 인자(`merg` 같은 오타)를 리포트 생성으로 보내, 예전 `law-names.jsonl`로 리포트를 덮어쓰고 종료 코드 0으로 끝난다 | fix `384e0f3` |
| 2 | Important | `tests/test_faq_cover_report.py:245` | 표본 테스트가 `len(...) <= 20`이라 빈 목록도 통과한다. 10·5·5 구성과 간격 순서를 확인하는 테스트가 없다 | fix `559e776` |
| 3 | Important | `src/cheongyak_rag/ingest/faq_cover_report.py:256` | `merge_raw`(`runs/135/law-names.jsonl`을 만든 함수)에 테스트가 없다 | fix `db67d40` |
| 4 | Important | `tests/test_faq_cover_report.py:218` | `build_report` 테스트가 실패 징후 표의 값·구간, 「실패 징후 1에 걸린 쌍」 절을 확인하지 않는다. `"모름" in out`은 머리글 때문에 항상 참이다 | fix `fd08daa` |
| 5 | Important | `src/cheongyak_rag/ingest/law_report.py:527` | 규칙 인용 정의가 「가장 가까운 앞 법령 이름이 규칙이거나 이름이 없다」뿐이라, `부칙` 앞 조를 다른 법령으로 보내는 코드(`citations.py:82`)와 어긋난다. `faq_cover_report.py`·`docs/135-faq-cover.md`의 같은 문구도 같다 | fix `154d4d2` |
| 6 | Suggestion | `src/cheongyak_rag/ingest/citations.py:38` | `Citation.name` 주석이 「부칙이면 `부칙`」이라 했지만 앞 법령 이름이 있으면 `<이름> 부칙`이 된다 | fix `87285ff` |
| 7 | Important | `src/cheongyak_rag/ingest/citations.py:28` | `ADDENDA`가 조 바로 앞의 `부칙`만 잡아, `부칙 제6조 및 제7조`의 제7조는 규칙 인용(`none`)으로 샌다. 분류 결함이다. 실제 15개 갈린 자리에는 이 경우가 안 걸렸다 | defer — 분류를 고치면 `runs/golden.jsonl`(#131 정답 라벨)이 바뀌어 #131·#73·#139 값과 비교할 수 없다. plan 설계 4가 이번에 분류를 안 고치기로 했다. 분류 수정 티켓에서 `golden.jsonl` 재생성과 함께 처리한다 |
| 8 | Important | `src/cheongyak_rag/ingest/faq_cover_report.py:154` | `모름`이 실패 징후 2의 갈린 자리, 징후 1의 분모·분자에 안 들어가고 구간 판정도 `모름` 수를 보지 않는다. 하위 에이전트가 애매한 자리를 전부 `모름`으로 붙이면 징후 1·2가 통과·정상으로 나온다 | push-back — plan 실패 징후 2가 「`모름`은 빼고 따로 적는다」고 정했다. 이번 값은 `모름` 0건이고 리포트 표에 `모름` 수가 같이 찍힌다. 구간에 `모름`을 넣으려면 plan 구간을 바꿔야 한다 |
| 9 | Suggestion | `src/cheongyak_rag/ingest/citations.py:65` | `sentence_of`가 문장 끝을 찾을 때 `pos`에서 바로 목록 시작에 걸려, 다음 문장이 목록 항목이면 하위 에이전트에게 준 context에서 뒤 문장이 빈다(415자리 중 97자리). 답변 원문 전체도 같이 줬다 | defer — 라벨이 이 입력으로 이미 붙었다. 고치면 `inputs`가 만드는 파일이 라벨을 붙인 때와 달라져 재현이 안 맞는다. 라벨을 다시 붙이는 티켓에서 `pos + 1`부터 찾도록 같이 고친다. `Place.sentence`(리포트의 문장 전체)는 영향이 없다 |
| 10 | Suggestion | `src/cheongyak_rag/ingest/faq_cover_report.py:300` | `golden_unchanged()`가 `golden.main()`의 직렬화를 다시 적어 비교한다. `main` 쪽 형식이 바뀌면 징후 3이 실제 파일과 다른 문자열을 비교한다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:406` | `pair["answer"]`로 바뀌어 `answer` 키가 없는 FAQ 줄은 `KeyError`가 난다. 실제 FAQ JSONL에는 항상 있고 소리가 나는 쪽이라 조용한 실패보다 낫다 | 기록만 |
| 12 | Suggestion | `runs/135/law-names-prompt.md` | 하위 에이전트 프롬프트가 분류의 `RULE_WORDS`(`규칙`·`공급규칙`·`동 규칙`)를 미리 알려 줘, 그 말 뒤 자리는 맞대도 검사되지 않는다. 리포트는 부칙만 이 한계로 적었다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/ingest/faq_cover_report.py:404` | 리포트 머리말이 읽는 파일에 `runs/golden.jsonl`을 안 적었다(모듈 docstring에는 있다) | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/ingest/citations.py:36` | `Citation.kind`가 `str`이라 규칙 인용 판정(`kind != "other"`)이 `law_report.py`·`golden.py`·`chunk.py`·`faq_cover_report.py`(`CLASS_SIDE`)에 따로 있고 모르는 값을 다르게 처리한다. `Literal`·`Enum`과 `is_rule` 프로퍼티로 모을 수 있다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/ingest/law_report.py:367` | `FaqCross.by_number_*` 기본값 0이 빠뜨린 생성자에서 조용히 0을 낸다. `FaqCross.uncovered_pairs`(`rule_pairs − covered_pairs`)와 `LabelCover.uncovered_pairs`(`q_no` 개수)의 정의도 다르다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/ingest/faq_cover_report.py:140` | `evidence`가 비어 있지 않기만 하면 통과한다. 415줄 중 23줄은 공백을 접어도 답변의 부분 문자열이 아니다(대부분 `...` 줄임) | 기록만 |
| 17 | Suggestion | `tests/test_faq_cover_report.py:276` | 테스트 빈틈 — `gold_pair_changes`의 「빠짐」 방향, `by_number_*`의 항·호·삭제 조 값, `validate_labels`의 허용 값 검사가 다른 검사에 가려진 것, `golden_unchanged`·`main` 분기, `sentence_of`의 목록 경계 | 기록만 |
| 18 | Suggestion | `src/cheongyak_rag/ingest/faq_cover_report.py:280` | `센 값`(교정 표 「집계한 값」), `extract_citations가 낸 자리`(「찾아 돌려준 자리」), `완전히 독립된 확인`이 한국어 표현 교정 표에 있는 말이다. `docs/135-faq-cover.md`에도 같은 말이 있다 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/generate/rules.py:244` | #135와 무관한 docstring 줄바꿈 변경이 diff에 들어왔다(내용 변경 없음) | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1: `ingest/citations.py`가 있고 `golden.py`가 거기서 가져다 쓴다. 만든 파일이 `runs/golden.jsonl`과 바이트 단위로 같다 | 예 | `golden.py:18-21` import · `cmp runs/golden.jsonl <재생성>` exit 0(`CMP_OK`, 리뷰 세션이 fix 뒤에 다시 돌림) |
| 통과 기준 2: `faq_cross`가 설계 2대로 센다. 단위 테스트 6항목, 기존 테스트는 고친다 | 예 | `tests/test_law_report.py:222·228·235·242·258·277`이 6항목 하나씩. `pytest -q` 1523 passed |
| 통과 기준 3: `format_report` FAQ 절이 새 커버·다른 법령 인용만 있는 쌍·이름별 수·번호로만 센 커버 줄을 내고 옛 문구를 지운다 | 예 | `law_report.py:515-540` · 「다른 법령 인용도 분모에서 빼지 않았다」 문구 grep 0건 |
| 통과 기준 4: `runs/135/law-names.jsonl` 한 줄 한 자리, 자리 수가 `extract_citations` 결과 전체와 같다 | 예 | 415줄 · `validate_labels` 문제 0건 |
| 통과 기준 5: `python -m cheongyak_rag.ingest.faq_cover_report`가 `docs/135-faq-cover.md`를 쓴다(API·DB 없음). 징후 1~4 값·구간, 전후 표, 갈린 자리 전부, jw 표본 20자리 | 예 | exit 0 · 리포트 `## 실패 징후`·`## 새 커버와 번호로만 센 커버`·`## 분류와 법령 이름 라벨이 다른 자리`·`## jw 표본 20자리` · 표본 10+5+5는 `559e776` 테스트 |
| 실패 징후 1: 라벨 기준 규칙 인용인데 현행에 없는 조를 인용한 쌍. 통과는 0 | 값만 적는다 | 라벨 기준 0/122 · 분류 기준 0/123 (`docs/135-faq-cover.md:13`) |
| 실패 징후 2: 갈린 자리. 정상 0~4 · 다시 잰다 5~20 · 미완 21 이상 | 값만 적는다 | 15/415, `모름` 0. 커버 판정을 바꾸는 자리 0 · 정답 라벨을 바꾸는 자리 8 (`docs/135-faq-cover.md:14,23`) |
| 실패 징후 3: `runs/golden.jsonl`이 그대로 | 예 | `cmp` exit 0 · `git diff main...HEAD -- runs/golden.jsonl` 비어 있음 |
| 실패 징후 4: 새 커버 숫자가 착수 때 값(123 · 123 · 59)과 같다 | 예 | 123 · 123 · 59 (`docs/135-faq-cover.md:16`) |
| Done: `docs/decisions.md`는 건드리지 않는다 | 판정 불가 | diff에 +1행이 있다. `ba0dbea`(main 세션의 Kickoff 커밋)에서 들어왔고 구현 루프 커밋이 아니다 |
| Done: `docs/concepts.md`에 「인용 법령 분류 3개」 표를 더했다 | 예 | `dbce857` · `docs/concepts.md` diff +17행 |
| Done: 하위 에이전트 입력 파일·실행 로그는 커밋하지 않는다 | 예 | `.gitignore`에 `runs/135/inputs/`·`runs/135/raw/` · `git status --porcelain` 비어 있음 |

## 확인한 것

- 이 PR에서 `runs/golden.jsonl`은 바뀌지 않았다. 분류 함수 옮기기는 동작이 같다(옛 `kind = _name_kind(nm) or kind`와 새 `if found := ...`가 같은 결과).
- `law_report`는 `.law` 파서를 import하지 않는다. API·DB 호출과 `data/` 쓰기는 없다.
- 리뷰 세션이 리포트를 다시 만들었을 때 값이 커밋된 것과 같았다(정의 문구 한 줄만 `154d4d2`에서 바뀜).
- 하위 에이전트 라벨은 같은 모델이 읽은 것이라 완전히 독립된 확인이 아니다(리포트 머리말이 적고 있다).

## 맨 아래

- 테스트: fix 뒤 `uv run pytest -q` 1523 passed, `uv run ruff check`·`ruff format --check` 통과.
- 인라인 스레드는 7·8·9행(defer·push-back)에 단다. 게시 결과는 PR에서 확인한다.
