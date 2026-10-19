# 131 리뷰 — PR #3

**대상:** `main...HEAD` — 20 commits, 28 files, +3144 −0 (리뷰 수정 10커밋 포함)
**plan:** docs/plans/131-1013-plan-dense-hybrid.md

리뷰는 `pr-review-toolkit`의 에이전트 5개(code · tests · errors · comments · types)로 했다. 아래 표는 겹친 지적을 하나로 합친 것이다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `golden.py:67-79` | `부칙 제6조`(faq-141)·`부칙제4조`(faq-444)가 본문 제6조·제4조 정답으로 잡혔다. faq-444는 규칙 조문 인용이 하나도 없는데 질문으로 남아 세 run에서 모두 놓친 것으로 셌다 | fix `b992f2b` |
| 2 | Important | `evaluate.py:110-117`, `runs/*/config.json` | `config.json`의 `commit`(5e8083d)이 결과를 만든 코드가 아니다. bm25·hybrid 결과는 3f58a2c의 토크나이저 변경 뒤 커밋 전 작업 트리에서 만들어졌다 | fix `40f8f62` `73e63ed` (코드 변경이 있으면 `-dirty`). 결과는 `8341d00`에서 깨끗한 트리로 다시 만들었다 |
| 3 | Important | `embed.py:41-47,64` | 쓰다 끊긴 캐시 줄 뒤에 이어 쓰면 새 행이 그 줄에 붙어 읽을 수 없다. 그 텍스트가 매 실행 API로 다시 나가 "두 번째 실행은 호출 0회"가 깨진다. 키가 빠진 줄은 `KeyError` | fix `890fae9` |
| 4 | Important | `corpus.py:11-13` | `삭제<2024.12.18>`처럼 접두어 없이 날짜만 든 표시 29개와 제10조 `<img>` 태그가 남아 날짜 숫자가 BM25 토큰·임베딩 입력에 섞인다. 주석은 막는다고 적혀 있고 테스트는 `<개정`·`<신설`만 본다 | fix `fd858d2` |
| 5 | Important | `compare.py:109-115` | `check_runs`가 qid 집합만 비교해, golden 정답을 바꾸고 일부 run만 다시 돌려도 통과하고 리포트는 "일치를 확인했다"고 적는다 | fix `056cfd5` |
| 6 | Important | `golden.py:102-103`, 리포트 6절 | 조문 인용이 없는 답변 298개가 뺀 질문 수에 안 들어가, 480쌍 중 어떻게 124개가 남았는지 리포트로 안 보인다 | fix `68bd41b` |
| 7 | Important | `tests/test_retrieval_evaluate.py:67-92` | dense·hybrid 순위를 확인하는 테스트가 없다. hybrid가 dense 순위만 쓰거나 RRF 인자를 바꿔도 통과한다 | fix `79d3574` |
| 8 | Important | `tests/test_retrieval_compare.py:125-130` | 리포트 첫 줄은 접두어만 확인해 `d − h`로 부호가 뒤집혀도 통과한다 | fix `6a6eb80` |
| 9 | Important | `tests/test_retrieval_compare.py:30-63` | `evaluate_run` 출력을 `build_report`에 넣어 보는 테스트와, `Embedder`+`write_run`으로 재실행 0회·동일 바이트를 보는 테스트가 없다 | defer — 이 세션에서 실제 데이터로 직접 확인했다(dense 재실행 OpenAI 호출 0회, `results.jsonl` `cmp` 동일). 키 이름이 바뀌는 후속 티켓에서 통합 테스트를 넣는다 |
| 10 | Suggestion | `search.py:76-82` | RRF 동점은 BM25 순서가 정한다. 문서화돼 있고 리포트도 그렇게 적지만 docstring 표현이 모호하다 | 기록만 |
| 11 | Suggestion | `embed.py:3`, `evaluate.py:70,160` | 주석이 "한 요청"이라 하는데 `BATCH = 256`으로 나뉜다. 지금은 212개라 한 번이다 | 기록만 |
| 12 | Suggestion | `golden.py:25,93`, 리포트 6절 | 이름 없음 표본은 앞 글자가 20자 미만인 인용(7개)을 조용히 건너뛴다. 헤더는 "앞 60자"라 적는다 | 기록만 |
| 13 | Suggestion | `compare.py:456-469` | 점검 run 문구가 통과 구간(BM25 20 / dense 18 이상)을 안 보이고 `20`을 하드코딩한다 | 기록만 |
| 14 | Suggestion | `golden.py:75` | 주석의 "이름이 이긴다"는 korean-style 교정 표의 `이긴다`다 | 기록만 |
| 15 | Suggestion | `evaluate.py:124-130,144,208-210`, `search.py:63-67`, `corpus.py:43-46`, `embed.py:69`, `compare.py:170-175,300,535-541` | 현재 데이터에서는 안 걸리는 방어 부족. `config.json`이 인자 대신 상수를 적는다 · 본문 없는 조에서 `first_sentence` IndexError · 빈 golden이면 run 파일을 먼저 덮어쓴다 · 질의가 전부 미등록어면 BM25가 조 번호 순이 된다 · 조 라벨 중복 검사 없음 · 응답을 `index` 순으로 정렬하지 않는다 · 전체 평균이 0일 때 부호 문구 · 6절이 golden.jsonl 대신 FAQ에서 다시 만든다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 1. `golden`이 `runs/golden.jsonl`을 쓰고 분류별 인용 수와 뺀 질문 수·이유를 출력한다 | 예 | `runs/golden.jsonl` 123줄. 출력: 규칙 183 · 다른 법령 171 · 이름 없음 61, 뺀 질문 357(조문 인용 없는 답변 298 · 다른 법령 인용뿐 59) |
| 통과 2. `evaluate --run`이 `results.jsonl`(질문 한 줄)과 `config.json`을 쓴다 | 예 | `runs/{bm25,dense,hybrid}/results.jsonl` 각 123줄, `config.json` 각 1개 |
| 통과 3. `compare`가 `docs/131-dense-vs-hybrid.md`를 쓰고 7개 절이 전부 있다 | 예 | 리포트 `## 1.`~`## 7.` 존재 (+8~10절). `tests/test_retrieval_compare.py::test_report_has_all_sections_in_order` |
| 통과 4. dense 두 번째 실행은 OpenAI 호출 0회이고 `results.jsonl`이 바이트 동일 | 예 | 재실행 출력 `OpenAI 호출 0회`, `cmp runs/dense/results.jsonl` 직전 사본과 동일 |
| 통과 5. 점검 run 결과가 리포트에 있다 | 예 | 리포트 `## 9.` — BM25 19/20, dense 17/20 |
| 통과 6. `runs/`와 리포트를 커밋하고 `data/cache/`는 안 한다 | 예 | `git ls-files runs docs/131-dense-vs-hybrid.md` 포함, `.gitignore`에 `data/cache/` |
| 통과 7. 전체 테스트 · `ruff check` · `ruff format --check` | 예 | `247 passed`, `ruff check` 출력 없음, `48 files already formatted` |
| 실패 1. 세 run의 줄 수·질문 id 집합이 golden과 같다 | 예 | 세 run 각 123줄 = `runs/golden.jsonl` 123줄. `check_runs`가 qid와 정답 라벨까지 비교(#5 수정 뒤) |
| 실패 1. 95% 신뢰구간이 0을 포함하나 / 반폭 | 값만 적는다 | hybrid−dense `recall@5` +0.177, 95% CI [+0.119, +0.239], p=0.0001. 0을 포함하지 않음 → plan 구간 「차이 있음」. baseline 없음(첫 측정) |
| 실패 2. 「갈린 질문」 절에 `hit@5`가 다른 질문이 전부 있고 순위 칸이 비지 않았다 | 예 | `hit@5`가 다른 질문 24개, 리포트 4절 24줄에 qid 전부 있고 빈 순위 칸 0. 읽고 이해가 되는지는 jw 몫 |
| 실패 3. 점검 BM25 20/20 | 아니오 — 19/20 구간 | 놓친 것: 제59조(1위 제58조의4, 자기 2위). plan 구간 18~19 → PR 본문에 적는다. 리포트 9절에 질문·1위 조 기재 |
| 실패 3. 점검 dense 18/20 이상 | 아니오 — 17/20 구간 | 놓친 것: 제9조(자기 2위), 제45조(자기 4위), 제59조(자기 10위). plan 구간 15~17 → PR 본문에 적는다 |
| 실패 4. 정답 라벨 질문 수 100개 이상 | 예 | 123개 (사전 측정 142쌍 → 부칙 제외 · 현행에 없는 조 제외 뒤) |
| 실패 5. `제N조`가 든 질문을 뺀 결과의 부호 | 값만 적는다 | 96개, hybrid−dense +0.182 (95% CI [+0.117, +0.257]). 부호는 전체와 같음 |
| 실패 6. 제53조 정답 질문을 뺀 결과의 부호 | 값만 적는다 | 72개, hybrid−dense +0.218 (95% CI [+0.138, +0.302]). 부호는 전체와 같음 |
| 이번에 안 하는 것 — generator · abstain · pgvector · 항 단위 청킹 | 예 | `git diff main...HEAD --stat`에 해당 파일 없음. 새 환경변수 접근(`os.environ.get`·`os.getenv`) 추가 0건 |

## 참고

- 수정 #1·#4는 golden과 문서 텍스트를 바꿔 숫자가 움직였다. 질문 124→123개, hybrid−dense `recall@5` +0.174→+0.177, 점검 run은 BM25 19/20 · dense 17/20이다. `8341d00`이 `runs/`와 리포트를 다시 만든 커밋이다.
- 임베딩이 필요한 조문 텍스트가 바뀌어 `Embedder`가 API를 1회 불렀다. 그 외 run은 모두 0회다.
- 테스트는 수정 뒤 전체를 다시 돌려 green이다(247 passed).
- `docs/plans/` 파일은 `~/prv` 레포라 커밋 대상이다.
