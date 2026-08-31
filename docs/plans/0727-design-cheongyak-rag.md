# 주택청약 RAG — 설계

**작성일:** 2026-07-27
**목표:** 실배포 + 유저 유입 + 이직 면접 어필 (RAG 엔지니어링 역량 증명)

---

## 1. 제품 정의

### 유저가 얻는 것

프로필(부분 입력 허용)을 넣으면 **현재 진행 중인 청약 공고별로 지원 가능 여부를 요건별로 판정**하고, 각 판정의 **근거 조문을 인용**한다. 가점도 함께 계산한다.

### 진입 경험

**빈 프로필로 시작.** 입력 문턱 0. 공고를 고르면 요건 설명부터 나오고, 판정에 필요한 정보는 시스템이 순서를 정해 되묻는다.

### 핵심 설계 원칙

- **프로필은 규칙 엔진 입력이 아니라 retrieval conditioner다.** 프로필이 코퍼스를 facet으로 좁히고, 좁혀진 공간에서만 검색한다.
- **결정론으로 남기는 것은 가점 산술 하나뿐.** 자격 판정은 retrieval이 주도한다.
- **근거 없으면 판정하지 않는다.** LLM이 근거 없이 verdict를 내지 못하도록 강제한다.
- **프로필은 서버에 저장하지 않는다.** localStorage + 요청마다 전송, trace엔 해시만.

---

## 2. 코퍼스 4층 구조

| 층 | 내용 | 청킹 단위 | 임베딩 |
|---|---|---|---|
| **L1 법령** | 주택공급에 관한 규칙 | 조/항/호 (구조적) | O |
| **L2 유권해석** | 국토부 주택청약 FAQ | Q&A 쌍 | O |
| **L3 공고 서술부** | 모집공고문 PDF 본문 (자격·지역우선·특례·유의사항) | 섹션 | O |
| **L4 공고 사실** | 일정·세대수·금액·공급유형·지역 | 레코드 | **X — RDB** |

**L4를 벡터스토어에 넣지 않는 것이 이 설계의 분기점.** "2026년 3월 15일", "84㎡ 120세대"는 의미적 유사도로 찾을 값이 아니라 `WHERE`로 거르는 값이다. 임베딩에 넣으면 recall만 흐려진다.

이 분리가 개인화 fanout이 동작하는 이유다 — 프로필이 L4를 좁히고, 좁혀진 공고의 L1~L3만 검색한다.

---

## 3. 데이터 소스 (탐색 완료)

### 법령

| 데이터 | 위치 | 비고 |
|---|---|---|
| 조문 단위 조회 | `law.go.kr/DRF/lawService.do?target=lawjosub` | `JO`(조 6자리, 제2조=`000200`) / `HANG` / `HO` / `MOK`. 응답에 `조문시행일자` 포함 |
| **시행일 법령 본문 조회** | [data.go.kr/15057523](https://www.data.go.kr/data/15057523/openapi.do) | **as-of 검색이 API 레벨에서 제공됨** |
| 현행법령 본문 조회 | [data.go.kr/15057358](https://www.data.go.kr/data/15057358/openapi.do) | 현행 스냅샷 |
| 주택공급에 관한 규칙 | [law.go.kr/lsInfoP.do?lsiSeq=190732](https://www.law.go.kr/lsInfoP.do?lsiSeq=190732) | |

- 인증키는 `OC` 파라미터. 법제처 신청(02-2109-6446) — 자동승인 여부 미확인. data.go.kr 경유가 더 편할 수 있음.
- `open.law.go.kr` 탐색 시점에 "시스템 점검" 노출 — 가용성 확인 필요.

### 유권해석

| 데이터 | 위치 |
|---|---|
| 국토교통부 주택청약 및 공급규칙 FAQ (20240529) | [data.go.kr/15035942](https://www.data.go.kr/data/15035942/fileData.do) (fileData, PDF) |

규칙 본문은 추상적. 실제 "나 되나?"는 유권해석에서 갈린다. **코퍼스의 숨은 알맹이.**

### 공고 (청약홈)

**공식 API (권장 경로):**

```
https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail
→ 401 {"msg":"등록되지 않은 인증키 입니다."}   # 엔드포인트 살아있음, 키만 필요
```

> `api.data.go.kr/openapi/{카탈로그ID}` 는 존재하지 않는 경로 (`resultCode:12 NO OPENAPI SERVICE ERROR`). odcloud가 진짜.

신청 페이지 (카탈로그 ID는 미검증 — 열어서 대조할 것):

| 데이터 | URL |
|---|---|
| 한국부동산원_APT분양정보 | https://www.data.go.kr/data/15061149/openapi.do |
| 한국부동산원_오피스텔분양정보 | https://www.data.go.kr/data/15059223/openapi.do |
| 국토교통부_청약경쟁률 | https://www.data.go.kr/data/15098906/openapi.do |
| 국토교통부_분양권전매 | https://www.data.go.kr/data/15098780/openapi.do |
| LH_공급예정주택 | https://www.data.go.kr/data/15058470/openapi.do |
| 국토교통부_주택분양가 | https://www.data.go.kr/data/15058057/openapi.do |
| 한국부동산원_분양가상한제 | https://www.data.go.kr/data/15057583/openapi.do |

**스크래핑 (fallback + PDF 첨부 획득 전용):**

베이스: `https://www.applyhome.co.kr`

```
# 목록 (APT 분양정보) — 검증 완료
GET /ai/aia/selectAPTLttotPblancListView.do
  pageIndex=1~34        ✅ 동작 (page ❌ 서버가 무시)
  suplyAreaCode=서울    ✅ 동작, 한글 그대로 (sido ❌ 무시)

# 행 파싱: <table class="tbl_st …"> → <tr data-pbno data-hmno data-honm> → <td> 11개
# 순서: 지역 | 주택구분 | 분양/임대 | 주택명 | 시공사 | 문의처 | 모집공고일 | 청약기간 | 당첨자발표일 | 특별공급 | 경쟁률

# 상세 — 검증 완료
POST /ai/aia/selectAPTLttotPblancDetail.do
  Content-Type: application/x-www-form-urlencoded
  houseManageNo=<data-hmno>&pblancNo=<data-pbno>&houseNm=<data-honm>
# → 200, <table> 6개. <caption>:
#   입주자모집공고 주요정보 / 청약일정 / 공급대상 / 특별공급 공급대상 / 공급금액, 2순위 청약금 / 기타사항

# 붙임파일 (모집공고문)
GET https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do
  ?houseManageNo=<hmno>&pblancNo=<pbno>&atchmnflSeqNo=<seq>&atchmnflSn=<sn>
# 상세 HTML의 <a href>에 절대 URL로 박혀 있음
# 응답 헤더:
#   Content-Type: application/octet-stream;charset=UTF-8      ← 확장자 판별 불가
#   Content-Disposition: attachment; filename="…%EA%B3%A0%EB%AC%B8.pdf"   ← 여기서 뽑아야 함

# 잔여세대 — 200 확인, 컬럼 순서가 목록과 다름 (8개), 별도 매핑 필수
GET /ai/aia/selectAPTRemndrLttotPblancListView.do
# 순서: 지역 | 구분 | 주택명 | 시행사 | 모집공고일 | … | 경쟁률

# 200만 확인, 파라미터·구조 미검증
GET /ai/aib/selectSubscrptCalenderView.do?year=2026&month=7   (table 2개)

# 미검증 (repo 코드에만 존재)
GET  /ai/aia/selectOtherLttotPblancListView.do        (기타 분양)
POST /ai/aia/selectSpsplyReqstStusPopup.do            (특별공급 접수현황, JS에서 발견)
```

검색 폼(`#pbSearchForm`) 필드: `beginPd`/`endPd`(`YYYYMM`), `houseDetailSecd`, `houseNm`, `chk0`~`chk3`. 날짜 범위를 넓혀 POST해도 건수가 안 바뀜 — **동작 여부 결론 못 냄, 직접 확인 필요.**

**스크래핑 주의사항:**

1. 총 페이지는 `.arw_next`의 `href="?pageIndex=N"`에서 파싱 (34 하드코딩 금지)
2. 잔여세대는 `<th>` 텍스트로 인덱스 동적 생성 — 목록 매핑 재사용 금지
3. 확장자는 `Content-Disposition` filename URL 디코딩해서 추출
4. 요청 간 sleep + 백오프. NetFUNNEL(`static.applyhome.co.kr/netfunnel/netfunnel.js`) 대기열 있어 피크 시 HTML 구조 변동 가능
5. robots.txt 없음(soft 404) — 명시적 금지는 없으나 ToS 직접 확인
6. **스크래핑 표면 최소화 원칙:** L4는 odcloud API, 스크래핑은 PDF 첨부 링크 획득에만

### 미해결

- 법제처 `OC` 키 발급 경로 (전화 신청 vs data.go.kr 경유)
- odcloud `ApplyhomeInfoDetailSvc` 나머지 operation명
- 공고문 첨부 HWP 비율 (수집 돌려봐야 나옴)

---

## 4. 답변 계약

### 요건 7축 (전역 판정 아닌 요건별 판정)

무주택 여부·기간 / 청약통장(가입기간·예치금) / 거주지역·거주기간 / 소득·자산(특공) / 재당첨제한 / 세대주 여부 / 특별공급 유형별 요건

각 축이 **fanout sub-query와 1:1**. 요건 하나 = 검색 하나 = 판정 하나 = 근거 하나.

### 판정값 5개

| 값 | 의미 | 후속 |
|---|---|---|
| `ELIGIBLE` | 충족 | — |
| `INELIGIBLE` | 미충족 | 사유 + 조문 |
| `CONDITIONAL` | 조건부 충족 | 조건 명시 |
| `NEED_INFO` | 프로필 정보 부족 | 유저에게 되물음 (페이로드: 어떤 필드 / 왜 / 어디서 확인 / 답하면 뭐가 바뀌나) |
| `UNVERIFIABLE` | 근거 검색 실패 또는 규칙 충돌 | 사람 확인 안내 |

`NEED_INFO`와 `UNVERIFIABLE`을 합치면 안 된다. 전자는 UX 문제(물어보면 풀림), 후자는 시스템 문제(retrieval 결함). 합쳐두면 "기권률 12%"가 개선 대상인지 정상 동작인지 구분이 안 된다.

### 전역 집계 (결정론적, LLM 아님)

우선순위: `INELIGIBLE` > `UNVERIFIABLE` > `NEED_INFO` > `CONDITIONAL` > `ELIGIBLE`

### Guardrail 2단

1. 근거 chunk 0개 → 판정 강제 `UNVERIFIABLE`
2. 인용 조문번호를 L1 인덱스와 **실재 대조** — 없는 조문 인용 시 기각 → `UNVERIFIABLE`

2번이 hallucinated citation 방어. 인용이 있다는 것과 그 인용이 실재한다는 건 다른 문제.

---

## 5. 데이터 흐름

### Flow A — 적재 파이프라인 (오프라인)

```
[법제처 15057523/lawService]  ─┐
[국토부 FAQ PDF 15035942]     ─┤
[odcloud 공고 상세 API]        ─┼─▶ A1~A4 수집 ─▶ A5 정규화·청킹 ─▶ A6 인덱싱
[applyhome getAtchmnfl PDF]   ─┘                                      │
                                                                       ├─▶ pgvector (L1·L2·L3)
                                                                       ├─▶ tsvector BM25 (L1·L2·L3)
                                                                       └─▶ RDB (L4 + 조문 유효기간)
```

| 단계 | 하는 일 | 산출 |
|---|---|---|
| A1 법령 | 규칙 MST 확보 → 시행일 목록 → 시행일별 조문 스냅샷 (v1: 최근 3년) | `law_articles(법령ID, 조, 항, 호, 제목, 본문, **valid_from, valid_to**, 출처URL)` |
| A2 유권해석 | FAQ PDF → Q/A 쌍 분리 | `faq(질문, 답변, 기준일자, 참조조문)` |
| A3 공고 사실 | odcloud 리스트+상세. 실패 시 스크래핑 fallback | `notices(pblancNo, houseManageNo, 주택명, 지역, 공급유형, **모집공고일**, 청약기간, 세대수, 공급금액…)` |
| A4 공고문 | 상세 HTML `<a href>` → `getAtchmnfl.do` 다운 → `Content-Disposition` filename URL디코딩으로 확장자 판별 | PDF 원본 + 추출 텍스트 |
| A5 청킹 | L1 조문 단위(길면 항 단위 + 조 제목 prefix) / L2 Q&A 단위 / L3 공고문 섹션 단위 | 메타 부착된 chunk |
| A6 인덱싱 | OpenAI 임베딩 + kiwipiepy→tsvector BM25. **L4는 인덱싱 안 함** | 인덱스 |

`valid_to` = 다음 시행일 − 1일. 조문마다 **유효 구간**을 갖는 temporal table (SCD Type 2). 이거 없으면 as-of 불가능.

**HWP 대응:** v1은 hwp 감지 시 **격리 + 로그**, 파싱 시도 안 함. 커버리지 몇 %인지가 v2 판단 근거. 조용히 건너뛰면 누락률이 안 보인다.

### Flow B — 질의 흐름 (온라인)

```
프로필(localStorage, 전 필드 optional) + 공고선택
   │
   ├─ B1  정규화 ──▶ derived facts + 가점(부분 프로필이면 범위)        [결정론적]
   ├─ B1b 결손분석 ▶ 없는 필드 → 그게 막는 축 매핑
   │
   ├─ B2 L4 필터 ─▶ 아는 필드로만 필터 (지역 모르면 전국)              [SQL]
   ├─ B3 as-of ───▶ 공고.모집공고일 → valid_from ≤ 공고일 ≤ valid_to 인 법령 버전
   ├─ B4 요건분해 ▶ 7축 sub-query (공고 유형 따라 축 on/off)
   │
   ├─ B5 축별 병렬검색 ─┬─ metadata pre-filter (layer, 유효구간, 지역, 공고ID)
   │                    ├─ hybrid: dense + BM25 → RRF
   │                    └─ rerank (cross-encoder)
   │
   ├─ B6 축별 판정 ──▶ LLM(요건정의 + derived facts + top-k 근거) → verdict + citation
   ├─ B7 guardrail ─┬─ 근거 0개 → UNVERIFIABLE
   │                 └─ 인용 조문번호 L1 실재 대조 → 실패 시 기각
   ├─ B8 집계 ─────▶ 우선순위 규칙                                    [결정론적]
   │
   ├─ B9  응답 ────▶ 전역판정 + 축별 체크리스트 + 근거 원문 + 출처링크 + 가점
   └─ B9b 질문랭킹 ▶ 남은 NEED_INFO를 물어볼 순서로 정렬
```

**B2·B3가 B5보다 먼저 오는 순서가 성능 대부분을 결정한다.** 검색 전에 SQL과 유효기간으로 후보를 좁히면 벡터 검색 공간이 "이 공고, 이 시점"으로 줄어 recall과 latency가 동시에 좋아진다. post-filter는 top-k를 이미 무관한 문서가 차지한 뒤라 걸러도 남는 게 없다.

**부분 프로필에서도 pre-filter는 살아남는다.** 공고ID + 유효구간은 항상 적용되고, 지역·소득 facet만 빠진다. 프로필은 추가 절삭이지 전제가 아니다.

**B9b 랭킹 휴리스틱:** 집계가 `INELIGIBLE` 우선이므로 **불가 판정을 낼 수 있는 필드를 먼저 묻는 게 최적**. 재당첨제한에 걸려 있으면 나머지 6축은 물을 이유가 없다.

**가점은 범위로.** 부분 프로필 → "현재 최소 52점 / 통장 가입일 알려주면 확정". 구간이 좁아지는 게 다음 입력을 유도하는 훅.

---

## 6. 스택

| 층 | 선택 | 근거 |
|---|---|---|
| 언어/서빙 | Python + FastAPI | RAG 생태계 |
| 판정 LLM | **OpenAI `gpt-5.6-sol`** (baseline) | 단일 벤더. 아래 참조 |
| 구조화 출력 | `client.chat.completions.parse()` + Pydantic (`strict: true`) | verdict enum + citation 리스트를 스키마로 강제. 파싱 실패 제거 |
| 임베딩 | **OpenAI `text-embedding-3-small`** | Anthropic엔 임베딩 API 없음. 키 보유. 코퍼스 작아 비용 무시 가능($0.02/1M) |
| 벡터스토어 | **pgvector** | pre-filter가 아키텍처 핵심 → L4(RDB)와 벡터가 같은 쿼리 안에 있어야 함. 별도 벡터DB면 필터 조건 이중 관리 + 앱 레벨 join. 배포도 Postgres 하나 |
| BM25 | kiwipiepy 형태소 → Postgres tsvector | Postgres 기본 파서는 한국어 모름. 사전 토큰화 주입 |
| Rerank | `bge-reranker-v2-m3` | 코퍼스 작아 CPU 충분 |
| Eval | 자체 구현 (골든셋 JSON + pytest) | Ragas 기본 지표로는 치명오답률·정당기권률을 못 잼 |
| Trace | Postgres 테이블 | 이미 DB 있음. Langfuse는 나중 |
| 프론트 | **Next.js SSR** | 공고별 페이지 인덱싱 → 롱테일 검색 유입. SPA면 이 경로가 통째로 없음 |
| 배포 | Fly.io (nrt) 또는 Railway | 한국 리전 latency |

### 임베딩 결정 기록

BGE-m3(dense+sparse 한 모델)를 검토했으나 **OpenAI 채택**. 근거: OpenAI 키 보유로 모델 호스팅이 사라짐. 대신 BM25를 따로 세워야 해서(kiwipiepy) 컴포넌트 수는 순증감 제로, 배포 난이도는 OpenAI가 낮음. **eval 붙은 뒤 BGE-m3와 recall@k 비교를 별도 실험으로 진행** — 이 비교 자체가 산출물.

### 판정 LLM — 벤더 결정

**OpenAI 단일 벤더.** 임베딩이 이미 OpenAI이고 Anthropic 키가 없음. 벤더 하나면 키 관리·비용 추적·rate limit·장애 대응이 전부 한 군데. 설계(구조화 출력 5값, 인용 실재 대조, 7축 병렬)는 벤더 무관하게 그대로 성립한다.

**가격** (developers.openai.com/api/docs/pricing, 2026-07-27 확인, Standard 기준, $/1M):

| 모델 ID | Input | Cached Input | Output |
|---|---|---|---|
| `gpt-5.6-sol` | $5.00 | $0.50 | $30.00 |
| `gpt-5.6-terra` | $2.50 | $0.25 | $15.00 |
| `gpt-5.6-luna` | $1.00 | $0.10 | $6.00 |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |
| `gpt-5.4-nano` | $0.20 | $0.02 | $1.25 |

Cached input = 정가의 0.1배(90% 할인).

**질의당 비용** (7축 × 입력 ~4K + 출력 ~500. 캐시는 축당 요건정의 ~2K가 히트한다고 가정):

| 모델 | 캐시 없음 | 캐시 적용 |
|---|---|---|
| `gpt-5.6-sol` | ~$0.25 | ~$0.18 |
| `gpt-5.6-terra` | ~$0.12 | ~$0.09 |
| `gpt-5.6-luna` | ~$0.049 | ~$0.037 |
| `gpt-5.4-mini` | ~$0.037 | — |
| `gpt-5.4-nano` | ~$0.010 | — |

**프롬프트 캐싱 설계 규칙:** 축별 요건 정의 + 판정 규칙은 질의마다 동일 → 프리픽스로 앞에 고정. 근거 chunk·프로필·공고 정보는 반드시 **뒤에** 붙인다. 프리픽스 중간에 타임스탬프·공고ID가 끼면 캐시가 통째로 깨진다.

⚠️ 캐시 최소 프리픽스는 1024토큰 선. 축 시스템 프롬프트가 그보다 짧으면 **에러 없이 조용히 캐시 미스**. 요건 정의를 상세하게 쓰는 게 정확도뿐 아니라 비용에도 이득.

⚠️ 캐싱이 자동인지 명시적 write가 필요한지는 미확인 — 구현 시 `usage`의 `cached_tokens`로 실측 검증할 것. 반복 호출에도 0이면 프리픽스가 깨지고 있다는 뜻.

**모델 선택 전략:**

1. **개발·eval 단계는 `gpt-5.6-sol` 고정.** 트래픽 없으니 비용이 무의미(골든셋 50문항 풀 eval 1회 ≈ $12). 강한 모델로 baseline을 잡아야 "품질 문제 vs retrieval 결함"이 구분된다.
2. **런칭 전 eval 수치를 보고 다운그레이드 결정.** 축별 정확도 표가 근거.
3. **축별 라우팅**(통장 가입기간=조회+산술 → nano/mini, 특별공급 요건=진짜 판단 → sol)은 합리적이지만 **eval 이후에만 방어 가능**. 지금 나누면 추측이고, eval이 있으면 "축별 정확도 표를 보고 내렸다"가 된다.

> 임베딩 단가(`text-embedding-3-small`)는 공식 pricing 페이지에 미표기 — 실제 청구로 확인 필요. 코퍼스 규모상 어느 쪽이든 무시 가능한 수준.

---

## 7. Eval 지표

답변 계약에서 자동으로 떨어지는 것들:

- 요건별 retrieval recall@k (정답 근거 조문이 top-k에 있나)
- citation precision (인용 조문이 실재하나 + 관련 있나)
- 요건별 판정 정확도
- **정당 기권 vs 부당 기권** 분리
- **치명오답률 — 실제 `INELIGIBLE`을 `ELIGIBLE`로 답한 비율** ← 단일 최중요 지표
- `NEED_INFO` 정밀도 (실제로 필요한 필드를 물었나)
- 확정까지의 질문 수

**치명오답률이 최중요인 이유:** 오류 비용이 비대칭이다. 부적격 당첨은 당첨취소 + 청약제한 페널티로 이어지고, 반대 방향 오답(가능한데 불가)은 기회손실에 그친다. 둘을 같은 "정확도"로 묶으면 안 된다.

골든셋: v1 공고 20건 기반 50문항 + 요건별 정답 라벨 + 정답 근거 조문. **부분 프로필 케이스 포함.**

---

## 8. v1 범위

**포함:**
- 코퍼스: 법령 + FAQ + 공고문 10~20건 (수집은 수동/반자동)
- 표 파싱은 자격요건·공급세대수·일정 3종만
- as-of 시간축 검색 (API가 제공하므로 v1에 포함)
- 7축 판정 + guardrail + 집계
- eval 하네스 (1일차부터)
- 부분 프로필 + 질문 랭킹

**v2로:**
- 공고문 자동 수집 + 신규 감지 스케줄러
- 법령 개정 자동 추적
- 표 전종 파싱
- HWP 파싱
- 축별 모델 라우팅 (eval 근거 확보 후)
- BGE-m3 비교 실험

---

## 9. 태스크 (Notion 프로젝트 진행 DB)

프로젝트: `주택청약 RAG` · DB `29241e61-65c0-801f-9529-cabf8cad919b`

| ID | 태스크 | 선행 |
|---|---|---|
| #68 | 인프라 스캐폴딩 — FastAPI + Postgres(pgvector) + 환경변수 | — |
| #69 | 법령 수집 — 법제처 API 키 + 조문 temporal 적재(valid_from/valid_to) | #68 |
| #70 | 유권해석 수집 — 국토부 청약 FAQ PDF → Q&A 쌍 분리 | #68 |
| #71 | 공고 구조화 수집(L4) — odcloud 키 + 리스트/상세 → notices | #68 |
| #72 | 공고문 수집(L3) — getAtchmnfl PDF + 확장자 판별 + HWP 격리 로그 | #71 |
| #73 | 청킹 + 메타데이터 스키마 — L1 조문/L2 Q&A/L3 섹션 | #69 #70 #72 |
| #74 | 인덱싱 — OpenAI 임베딩 → pgvector + kiwipiepy → tsvector BM25 | #73 |
| #75 | 골든셋 구축 — 50문항 + 요건별 정답 라벨 + 근거 조문 | #72 |
| #76 | Eval 하네스 — recall@k / citation precision / 치명오답률 / 기권 분리 | #74 #75 |
| #77 | 프로필 정규화 + 가점 계산(B1) — 부분 프로필, 가점 범위 | #68 |
| #78 | as-of 해소(B3) — 모집공고일 → 유효 법령 버전 | #69 #71 |
| #79 | 요건 분해 + 축별 병렬검색(B4/B5) — pre-filter → hybrid → RRF → rerank | #74 #77 #78 |
| #80 | 축별 판정 + guardrail(B6/B7) — 구조화 출력 5값, 인용 실재 대조 | #79 |
| #81 | 집계 + 응답 조립(B8/B9) — 우선순위 집계, 체크리스트 | #80 |
| #82 | 결손 분석 + 질문 랭킹(B1b/B9b) — NEED_INFO 페이로드 | #77 #81 |
| #83 | Trace 로깅 — 프로필 해시만 저장 | #80 |
| #84 | 프론트 — Next.js SSR | #81 |
| #85 | 배포 — Fly.io(nrt)/Railway + Postgres | #83 #84 |

**임계 경로:** #68 → #71 → #72 → #73 → #74 → #79 → #80 → #81 → #84 → #85 (10단계)
**병렬 가능:** #69 · #70 · #77

---

### 설계 결정 요약 (면접 대비 TDR 후보)

1. 왜 가점 계산을 LLM에게 안 맡겼나 — 산술은 결정론
2. 왜 L4(구조화 데이터)를 벡터스토어에 안 넣었나 — pre-filter vs post-filter
3. 왜 as-of 시간축이 필요한가 — 법령은 불변 코퍼스가 아니다
4. 왜 `NEED_INFO`와 `UNVERIFIABLE`을 분리했나 — 기권을 지표로 쓰려면 사유가 타입이어야
5. 왜 인용 조문을 실재 대조하나 — 인용이 있다 ≠ 인용이 실재한다
6. 왜 pgvector인가 — 필터와 벡터가 같은 트랜잭션
7. 왜 eval을 1일차에 세웠나 — 병목을 추측이 아니라 수치로
