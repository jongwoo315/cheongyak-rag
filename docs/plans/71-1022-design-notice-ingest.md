# #71 공고 구조화 수집(L4) — 설계

**Notion:** #71 · **Tier:** C · **작성:** 2026-10-22

## jw 기준

청약홈 공고들을 sql 테이블에 성공적으로 적재한다

## 목적

제품(설계 `docs/plans/0727-design-cheongyak-rag.md` §1)은 「프로필 + 공고 → 요건별 판정」이다. 지금 끝까지
도는 흐름(#139)은 법령·FAQ 질의응답이라 제품 입력의 절반인 공고가 없다. 이번 티켓은 L4 공고 사실
(일정·지역·공급유형·세대수·금액)을 SQL로 거를 수 있게 Postgres 테이블에 넣는다. 공고문 PDF(L3)는 #72다.

## 착수 때 확인한 사실 (2026-10-22, main 세션 실측)

- 데이터셋은 data.go.kr **15098547 「한국부동산원_청약홈 분양정보 조회 서비스」**다. 0727 설계에 적힌
  15061149는 지금 404다. Base URL `https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1`
- 개발계정 자동승인, 트래픽 40,000. 키는 `.env`의 `DATA_GO_KR_KEY`(jw가 넣음). **Encoding 키라 `%`가 들어 있다** —
  쿼리 파라미터로 다시 인코딩하면 401 「등록되지 않은 인증키」, 그대로 붙이면 200이었다
- API 명세(swagger): `https://infuser.odcloud.kr/api/stages/37000/api-docs` (키 없이 받는다). operation 10개
- `getAPTLttotPblancDetail`(APT 분양정보 상세): `totalCount` 2,909. `perPage=1000`으로 3번 호출에 전부 받았다(각 0.9초 안팎).
  `(HOUSE_MANAGE_NO, PBLANC_NO)` 2,909개 전부 서로 다르다. 행마다 키 49개. 모집공고일 2020-02-03 ~ 2026-10-21,
  2026년 공고 273건, 공급지역 17개. 모집공고일이 빈 행 0
- `getAPTLttotPblancMdl`(APT 주택형별 상세): `totalCount` 14,899. 키 17개 — 주택형(`HOUSE_TY`)·공급면적·일반/특별공급
  세대수·특별공급 유형별 세대수·분양최고금액(`LTTOT_TOP_AMOUNT`, 문자열, 만원)
- `cheongyak-db`는 메인 repo에서 떠 있고 alembic은 `0001 (head)`. 테이블은 아직 하나도 없다

## 1. 범위

| 대상 | 이번에 넣나 | 이유 |
| --- | --- | --- |
| APT 분양정보 상세 → `notices` | 넣는다 | 주택공급규칙이 다루는 본체다 |
| APT 주택형별 상세 → `notice_models` | 넣는다 | 0727 설계 L4의 세대수·금액이 여기에만 있다 |
| 잔여세대 · 오피스텔/도시형 · 공공지원 민간임대 · 임의공급 (6개 operation) | 안 넣는다 | 규칙 적용이 다르거나 일부만 적용된다. 판정 흐름이 APT로 먼저 돌고 나서 본다 |

- 기간: **모집공고일이 실행일 기준 최근 3개월인 공고만** 받는다 (Kickoff에서 jw 지정: 「최근 3개월만 파싱해도 충분」).
  상세 API에 `cond[RCRIT_PBLANC_DE::GTE]=<실행일 − 3개월>`을 건다. 2026-10-22 실측: `cond[RCRIT_PBLANC_DE::GTE]=2026-07-22`이면
  `matchCount` 81, `totalCount`는 필터와 무관하게 2,909로 나온다 — **필터를 건 요청의 건수는 `matchCount`다**
- 주택형별 API는 날짜 조건을 받지 않는다(파라미터가 `HOUSE_MANAGE_NO`·`PBLANC_NO` 둘뿐). 그래서 받은 공고마다
  `cond[HOUSE_MANAGE_NO::EQ]`·`cond[PBLANC_NO::EQ]`로 한 번씩 부른다. 실측: 공고 하나에 `matchCount` 10, 행 10
- 이전 실행에서 들어온 행은 지우지 않는다. 기간 밖으로 밀려난 공고도 테이블에 남는다

## 2. 설계 결정

| 결정 | 고른 것 | 안 고른 것과 이유 |
| --- | --- | --- |
| 저장 모양 | 거를 때 쓰는 열만 타입을 준 열로 두고, 응답 한 행 전체를 `raw jsonb`에 그대로 둔다 | 49개 필드를 전부 열로 만들면 스키마가 응답 변화에 묶인다. 전부 jsonb면 `WHERE`가 느리고 타입 검사가 없다 |
| 키 | `notices` PK `(house_manage_no, pblanc_no)`, `notice_models` PK `(house_manage_no, pblanc_no, model_no)` | 실측에서 앞의 둘이 유일했다 |
| `notice_models` → `notices` FK | 건다 (`ON DELETE CASCADE`). 공고를 먼저 넣고 그 공고의 주택형을 넣는다 | 주택형을 공고별로 받으므로 짝 없는 주택형이 생길 수 없다. 앱 코드로 대조하는 것보다 DB 제약이 짧다 |
| 재실행 | `INSERT ... ON CONFLICT (pk) DO UPDATE` + `fetched_at` | 공고는 정정이 잦다. 지우고 다시 넣기는 판정 결과와 이어 붙일 때 행 정체성을 잃는다 |
| 키 처리 | `urllib.parse.unquote(settings.data_go_kr_key)`로 한 번 풀고 httpx `params`에 넘긴다 | Encoding·Decoding 키 어느 쪽이 와도 같은 요청이 나간다 |
| HTTP | `httpx`(이미 의존성), 동기. 테스트는 `httpx.MockTransport` | 호출이 20번 안팎이라 동시성이 필요 없다 |
| DB 쓰기 | 동기 `create_engine(settings.database_url)` (psycopg3) | 앱은 async지만 적재는 배치 한 번이다 |
| 테스트 DB | 같은 컨테이너의 `cheongyak_test` DB. URL은 `DATABASE_URL`의 DB 이름을 **바꿔서** 만든다(덧붙이지 않는다) | 실제 적재 대상(`cheongyak`)과 섞이지 않게 한다 |

## 3. 지표

| 지표 | 정의 |
| --- | --- |
| 적재율 | 이번 실행이 받은 PK 중 테이블에 있는 수 / 같은 실행의 API `matchCount` (공고는 상세 요청 하나, 주택형은 공고별 요청의 합) |
| 재실행 | 같은 명령 두 번째 실행 뒤 행 수와 PK 집합이 그대로인가, 새로 들어간 행 수 |
| 필드 보존 | `raw`의 키 집합이 API 응답 키 집합과 같은 행의 비율 |
| 타입 변환 실패 | 날짜·정수·Y/N 열로 옮기다 실패해 NULL이 된 값의 수 (원문이 빈 값인 것은 따로 센다) |
| 주택형 없는 공고 | 이번 실행이 받은 공고 중 주택형 행이 0개인 공고 수 |
| 명세 차이 | 응답 키 중 swagger에 없는 것, swagger 필드 중 응답에 없는 것 |
| 호출 | API 호출 수 · 재시도 수 · 걸린 시간 |

baseline 없음 — 첫 적재다.

## 이번에 안 하는 것

- 공고문 PDF·HWP(L3) — #72
- APT 외 operation 6개 (위 §1)
- 주기적 갱신(cron), 판정 쪽 쿼리 — 판정 skeleton·#78에서
- 임베딩·검색 대상에 넣기 — L4는 벡터에 넣지 않는다(0727 설계 §2)

## 열린 질문 (PR 게이트에서 jw가 본다)

- 주택형 없는 공고가 0이 아니면 그것이 API 시점 차이인지, 다른 공고 유형이 섞인 것인지
- 기간을 넓힐 때(예: 판정 표본이 모자랄 때)는 `--months`만 바꾸면 된다. 기간 밖 행을 지울지는 판정 티켓에서 정한다
