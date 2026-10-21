# #139 답 생성 — 설계

**Notion:** #139 · **Tier:** B · **작성:** 2026-10-22

## jw 기준

질문에 대한 답이 생성되고 내가 확인이 가능하다

## 목적

수집(#69·#70) → 청킹(#73) → 검색(#131)까지 이어져 있고, 검색 결과로 답을 만드는 단계와 질문을 넣는
진입점이 없다. 이번 티켓은 질문 하나 → hybrid 상위 조 → LLM이 인용을 단 답 → 근거가 없으면 `abstain`까지
끝에서 끝으로 잇는다 (walking skeleton).

## 착수 때 jw가 정한 범위 (2026-10-22)

- generator는 **OpenAI 하나**. OpenAI·Anthropic 2종 비교는 후속 티켓으로 뺀다
- 진입점은 **CLI**. `POST /ask`는 이번에 안 한다

## 1. 흐름

```
질문 ─▶ query.Index.search (article, hybrid)  ─▶ 조 상위 5 + FAQ 상위 3
     ─▶ 프롬프트(문맥 = 조·FAQ 원문, 각각 라벨 [제34조] [Q47])
     ─▶ OpenAI chat.completions, JSON schema {abstain, answer, citations}
     ─▶ 사후 점검: 문맥에 없는 인용은 버리고 센다 · 유효 인용 0개인 답은 abstain으로 바꾸고 센다
     ─▶ CLI 출력 (답 · 인용 조 원문 · 검색 상위 조 · 토큰·$)
```

- 검색은 `src/cheongyak_rag/retrieval/query.py`의 `Index`를 그대로 쓴다. 고른 구조는 `runs/73/selected.json`의 `article`
- 새 모듈 `src/cheongyak_rag/generate/` — `answer.py`(프롬프트·호출·사후 점검·캐시·CLI), `evaluate.py`(일괄 실행·지표·리포트)

## 2. 설계 결정

| 결정 | 고른 것 | 안 고른 것과 이유 |
| --- | --- | --- |
| 모델 | `gpt-5.4-mini` (설정 `OPENAI_GEN_MODEL`) | `gpt-5.6-sol`(판정용 기본값)은 이 리포의 판정 LLM 자리다. 답 생성은 호출 수가 많아 싼 모델로 시작한다. 가격 입력 $0.75 · 출력 $4.50 / 1M 토큰 — OpenAI 모델 페이지, 2026-10-22 확인 |
| 출력 형식 | JSON schema (strict) `{abstain: bool, answer: str, citations: [str]}` | 본문에서 `[제N조]`를 정규식으로 뽑는 방식은 인용과 문장이 어긋나도 못 잡는다. 구조화 출력이면 인용 목록이 따로 오고, 본문 안 `[...]` 표기와의 일치는 점검으로 센다 |
| 문맥 | 조 상위 5 + FAQ 상위 3 | `query.py` docstring이 이미 「#139가 이 함수를 generator 입력으로 쓴다」로 정해 둠. FAQ도 공식 답이라 근거가 된다 |
| 근거 없음 | 모델이 `abstain=true`를 고르거나, 유효 인용이 0개면 코드가 `abstain`으로 바꾼다 | 프롬프트만 믿으면 인용 없는 답이 그대로 나간다. 바꾼 건수는 따로 센다(숨기지 않는다) |
| 재현 | 응답 캐시 `data/cache/gen-<model>.jsonl` — 키는 `sha256(model + system + user)`, 값은 응답 JSON·usage·지연 | 임베딩 캐시(`retrieval/embed.py`)와 같은 방식. 두 번째 실행은 호출 0회, 같은 결과 |
| 비용 상한 | 일괄 실행 중 누적 $가 6을 넘으면 멈춘다 (`--budget-usd`, 기본 6) | 무인 루프에서 프롬프트 버그 하나가 재시도로 비용을 태우는 것을 막는다 | <!-- style-exempt -->
| 평가 누수 | 일괄 실행에서는 `exclude_same_question=True` | golden 질문은 FAQ 질문이라 자기 FAQ 쌍이 문맥에 들어가면 답을 베낀다 |

## 3. jw가 확인하는 방법

- CLI 한 줄: `python -m cheongyak_rag.generate.answer "질문"` → 답, abstain 여부, 인용한 조의 원문(앞 300자), 검색 상위 조 목록, 토큰·$
- 리포트 `docs/139-answer.md` — 표본 10문항(seed 0)을 질문 · 생성 답 · 인용 · FAQ 공식 답 · 정답 조를 나란히 둔다. golden에서 abstain한 문항은 전부 목록으로

## 4. 평가 질문

- golden 123문항 (`runs/golden.jsonl`, 정답은 조 단위)
- 범위 밖 10문항 (`runs/139/ood.jsonl`, plan에 고정) — 7개는 주택과 무관, 3개는 주택 관련이지만 이 규칙에 없는 것(대출 LTV · 재산세 · 전월세 신고). 전부 `abstain`이어야 맞다

## 5. 지표

| 지표 | 정의 |
| --- | --- |
| 생성 실패 | 예외·JSON 파싱 실패 건수 |
| 인용 없는 답 | `abstain=false`인데 유효 인용 0개였던 건수 (코드가 abstain으로 바꾼 것) |
| 문맥 밖 인용 비율 | 문맥에 없는 라벨 인용 수 / 전체 인용 수 |
| golden abstain 비율 | golden 123 중 최종 abstain 수 / 123. 검색 hit@5(정답 조가 문맥에 있음) 여부로 갈라서도 낸다 |
| 범위 밖 abstain | 10문항 중 abstain 수 |
| 인용 정밀도 | 답한 문항에서 인용한 조 중 정답 조인 비율의 평균. 분모가 0인 문항(조 인용 없이 FAQ만 인용)은 빼고 그 수를 같이 적는다. 검색 hit@5 문항만으로 한 번 더 낸다 |
| 비용 | 호출 수, 입력·출력 토큰 합과 질문당 평균, $, 지연 p50·p95 |

baseline 없음 — 이번이 첫 측정이고 후속 provider 비교 티켓의 기준선이 된다.

## 이번에 안 하는 것

- provider 2종 비교 — 후속 티켓 (Anthropic 키 필요)
- `POST /ask` — 진입점은 CLI만
- 답이 맞는지 LLM judge로 채점 — 이번에는 jw가 리포트 표본으로 본다
- rerank·질문 쪼개기 #79, pgvector 적재 #74, 다른 법령 #135, 검색 놓친 조 #138
- golden set 변경, 검색 파라미터 변경 (k=5, faq_k=3 고정)

## 열린 질문 (PR 게이트에서 jw가 본다)

- FAQ를 문맥에 넣는 것이 답을 FAQ 문장 베끼기로 만드는지 — 표본에서 눈으로 본다
- abstain 기준을 모델에 맡기는 것이 충분한지 — 범위 밖 10문항과 golden abstain 목록으로 본다
