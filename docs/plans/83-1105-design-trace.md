# #83 trace 저장 — 설계

**Notion:** #83 · **선행:** #81(B8 집계·B9 응답, PR #15 머지 `41aac53`) · **바탕 설계:** `docs/plans/0727-design-cheongyak-rag.md` §1 핵심 설계 원칙(23행 「trace엔 해시만」)·§6 스택(Trace = Postgres 테이블)

## jw 기준

질의 한 건이 판정 흐름을 지나간 기록을 DB 테이블에 한 행씩 쌓는다

- 이 문장은 jw가 「trace라고 하면 로그 쌓는 거 말하는거야?」라고 물었을 때 Claude가 설명으로 먼저 쓴 문장이다. jw가 그 문장을 그대로 기준으로 골랐다

## 왜

- #81까지 공고 하나 × 프로필 하나를 응답까지 돌리면 결과가 화면(stdout)에만 나오고 사라진다. 「이 공고에 왜 이 판정이 나왔나」를 나중에 되짚을 수 없다
- #85 배포 뒤에는 질의를 사람이 직접 보지 않는다. 남겨 둔 기록이 없으면 오답을 신고받아도 재현할 재료가 없다
- 프로필은 서버에 저장하지 않는다는 원칙(바탕 설계 23행)이 trace에서 처음 실제 저장소를 만난다. 원본을 안 남기고도 같은 프로필의 질의를 묶을 수 있어야 한다

## 흐름에서의 자리

- 이미 있는 것: 공고 값 → 축 켜고 끄기(B4) → 축별 검색(B5) → LLM 판정(B6) → 인용 대조·ELIGIBLE guard(B7) → B8 집계 → B9 응답. 진입점은 `uv run python -m cheongyak_rag.generate.verdict <공고> --profile <json>` 하나다
- 이번에 바꾸는 stub: trace. #81 설계는 자리 없이 「다음 티켓」으로만 뺐다(`docs/plans/81-1103-design-aggregate.md:22`)
- 이번에 더하는 것: B9 뒤에 trace 행 하나를 쓴다. 흐름 중간에 예외가 나도 행을 쓴다
- 남는 stub: B9b 질문 랭킹(#82), 화면·HTTP API(#84)

## 질의 한 건이 무엇인가

- **질의 = 공고 하나 × 프로필 하나를 B9 응답까지 돌리는 한 번의 호출.** 하위 질의(축 하나 또는 특별공급 유형 하나의 검색 문장)와 다르다. 질의 하나 안에 하위 질의가 여럿 있다
- 코드로는 새 함수 하나다: `trace.run_traced(...)` — `verdict.judge` → `aggregate.build_answer` → trace 행 쓰기. `verdict` CLI가 이 함수를 부른다. #84 HTTP API도 이 함수를 부르게 된다
- 측정 리포트(`verdict_report`·`aggregate_report`)는 `judge`를 직접 부르므로 행을 쓰지 않는다. 측정 한 번에 18쌍 × 여러 번 행이 쌓여 실제 사용 기록과 섞이는 것을 막는다

## 정한 것

바탕 설계가 정하지 않은 것을 여기서 정한다.

| 항목 | 고른 것 | 안 고른 것과 이유 |
| --- | --- | --- |
| 저장 모양 | **테이블 하나 `traces`.** 거르고 정렬할 칸만 열로 두고, 흐름 기록은 `steps` JSONB, 응답 전문은 `answer` JSONB | 단계마다 하위 테이블(`trace_steps` 등). trace는 쓰고 나서 고치지 않고 질의 단위로 다시 꺼내 본다. 여러 질의를 가로질러 SQL로 집계할 일이 아직 없다. 생기면 그때 JSONB에서 뽑거나 Langfuse로 옮긴다(바탕 설계 §6) |
| 프로필 해시 | **HMAC-SHA256.** 키는 새 환경 변수 `TRACE_HASH_KEY`. 입력은 `Profile.to_dict()`를 키 정렬한 JSON | 키 없는 SHA-256. 프로필 칸 대부분이 비어 있거나 참·거짓이라 경우의 수가 작다. 생년월일만 채운 프로필이면 날짜 2만여 개를 다 해시해 보면 원본이 나온다 — 해시가 곧 원본이 된다 |
| 키가 없을 때 | 흐름을 돌리기 전에 멈춘다(CLI exit 2, 「`TRACE_HASH_KEY`가 없다」) | 행 없이 응답만 낸다. 조용히 기록이 빠지고 jw 기준이 깨진다 |
| 이유 문장 속 프로필 값 | **가린다.** 저장하는 모든 글자(`steps`·`answer`)에서 그 질의 프로필의 문자열 값(날짜)이 글자 그대로 나오면 `[프로필 값]`으로 바꾼다 | 그대로 저장. 착수 때 main 세션이 #81 측정(`runs/81/last_run.json`)을 세어 보니 LLM 이유 135개 중 10개가 프로필 날짜를 그대로 적었다(예: 「프로필의 혼인신고일(2012-05-20)과 공고일…」). 그대로 두면 해시만 남기는 의미가 없다 |
| 파생값 | 가리지 않는다. 가입기간 `12년6월3일`·나이 같은 값은 그대로 저장한다. 리포트에 몇 행에 나왔는지만 센다 | 파생값까지 가리기. 공고일과 합치면 원본 날짜를 되돌릴 수 있지만, 판정 이유를 읽는 데 필요한 값이라 가리면 trace를 읽는 목적이 줄어든다. 이번에 안 하는 것에 둔다 |
| 흐름 중간 실패 | **행을 쓴다.** `status='error'`, `error`에 예외 이름과 메시지(프로필 값 가린 뒤). 그리고 예외를 그대로 다시 올린다 | 성공만 기록. 실패한 질의가 바로 나중에 되짚어야 할 질의다 |
| 행을 못 쓸 때(DB 오류) | 응답은 그대로 출력하고 stderr에 알린 뒤 exit 1 | 응답도 막기. 사용자에게 줄 답을 기록 실패 때문에 버리지 않는다. 대신 exit 코드로 드러낸다 |
| 행이 없는 경우 | 프로필 JSON을 못 읽은 경우만. 흐름에 들어가기 전이라 질의가 아니다 | — |

## `traces` 칸

| 칸 | 타입 | 뜻 |
| --- | --- | --- |
| `id` | bigserial PK | |
| `created_at` | timestamptz, 기본값 now() | |
| `house_manage_no` | text, not null | 요청에 들어온 공고 관리번호 |
| `pblanc_no` | text, null 가능 | 정해진 공고번호. 공고를 못 찾으면 null |
| `profile_hash` | text, not null | HMAC-SHA256 16진수 64자 |
| `status` | text, not null | `ok` · `error` |
| `error` | text, null 가능 | `status='error'`일 때 예외 이름과 메시지 |
| `verdict` | text, null 가능 | 전역 판정(일반공급 판정). 실패면 null |
| `model` | text, not null | 판정 LLM 모델 이름 |
| `system_sha` | text, not null | 판정 system 프롬프트 해시(`verdict_report.system_sha()`와 같은 값) |
| `seconds` | double, not null | 흐름 전체 걸린 시간 |
| `steps` | jsonb, not null | 아래 |
| `answer` | jsonb, null 가능 | B9 응답 전문(`dataclasses.asdict`). 실패면 null |

`steps`:

- `as_of`(공고일) · `law_mst` · 켜진 축과 꺼진 축(축마다 켜고 끈 이유) — B3·B4
- 하위 질의마다: 축 · 질의 문장 · 검색 결과 라벨(`context_labels`) · 모델 판정(`original_verdict` 또는 `verdict`) · 최종 판정 · `forced`·`guarded` · 기각된 인용 · 입력·출력 토큰 · 비용 · 캐시 여부 · 오류 — B5~B7
- 질의 합계: LLM 호출 수(캐시 제외) · 토큰 · 비용

인덱스: `created_at`, `(house_manage_no, pblanc_no)`, `profile_hash`. 행이 쌓여도 「이 공고」·「이 프로필」로 꺼내 볼 수 있게 한다.

## 측정

- 표본: #81과 같은 공고 6건(`runs/79/last_run.json`) × 프로필 3종(`runs/80/profiles/`), 18쌍. 여기에 없는 관리번호 1건(공고 못 찾음 → 실패 행), 꽉 찬 프로필 한 쌍을 한 번 더(같은 프로필 → 같은 해시). 질의 20건
- 캐시(`data/cache/verdict-gpt-5.4-mini.jsonl`)를 읽으므로 LLM 호출 0이 기대값이다
- 실제 DB(5433)에 `0005` 마이그레이션으로 `traces`를 만들고 거기에 쓴다. `chunks`·`notices`·`notice_models`·`law_versions`는 읽기만 한다
- 측정 코드는 `trace.py` 함수를 import하지 않는다. 행 수는 측정 전 `max(id)` 뒤로 새로 생긴 행을 센다. 저장된 응답은 측정 코드가 반환 응답에 따로 가리기를 해서 비교한다

## 이번에 안 하는 것

- 파생값(가입기간·나이) 가리기 — 위 표
- 측정 리포트(`verdict_report`·`aggregate_report`)가 행을 쓰게 하기 — 위 「질의 한 건이 무엇인가」
- trace 보는 화면·조회 API — #84
- 오래된 행 지우기·보존 기간 — 배포(#85) 뒤 실제로 쌓이는 양을 보고 정한다. 리포트에 행당 크기만 적는다
- Langfuse 연동 — 바탕 설계 §6 「나중」
- 판정 정확도·프롬프트 — #75·#76·#143
