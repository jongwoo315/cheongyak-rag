# 개념 표

판정 흐름에 나오는 목록형 개념을 한곳에 모았다. 새 개념을 만들거나 바꾼 티켓이 이 표를 같이 고친다.
정의는 코드가 기준이고, 표는 그 위치를 가리킨다.

## 축 7개 — 공고 하나의 청약 요건을 나눈 갈래

정의: `src/cheongyak_rag/retrieval/axes.py:78` `AXES`. 만든 티켓 #79.

| id | 이름 | 켜지는 때 | 보는 조문 |
| --- | --- | --- | --- |
| `homeless` | 무주택 여부·기간 | 항상 | 제53조 |
| `account` | 청약통장 | 항상 | 제9·10·27·28조 |
| `residence` | 거주지역·거주기간 | 항상 | 제4·34조 |
| `income_asset` | 소득·자산(특별공급) | 공고 주택형의 특별공급 세대수 합 > 0 | 제35·41·43·46조 |
| `rewin` | 재당첨제한 | 투기과열지구·청약과열지역·분양가상한제·공공택지 표시 중 하나라도 참 | 제54조 | <!-- style-exempt -->
| `householder` | 세대주 여부 | 투기과열지구·청약과열지역 표시 중 하나라도 참, 또는 노부모 부양 특별공급 세대수 > 0 | 제2·28조 |
| `special_type` | 특별공급 유형별 요건 | 공고 주택형의 특별공급 세대수 합 > 0 | 제35~47조 |

- 축 하나가 하위 질의 하나다. `special_type`만 공고에 세대수가 있는 특별공급 유형마다 하위 질의가 하나씩 생긴다
- 축 판정 하나는 LLM이 낸다(#80 `src/cheongyak_rag/generate/verdict.py`)

## 특별공급 유형 8개

정의: `src/cheongyak_rag/retrieval/axes.py:29` `SPECIAL_TYPES`. 만든 티켓 #79.

| 공고 원본 키 | 유형 |
| --- | --- |
| `MNYCH_HSHLDCO` | 다자녀가구 |
| `NWWDS_HSHLDCO` | 신혼부부 |
| `LFE_FRST_HSHLDCO` | 생애최초 |
| `OLD_PARNTS_SUPORT_HSHLDCO` | 노부모 부양 |
| `INSTT_RECOMEND_HSHLDCO` | 기관추천 |
| `YGMN_HSHLDCO` | 청년 |
| `NWBB_HSHLDCO` | 신생아 |
| `TRANSR_INSTT_ENFSN_HSHLDCO` | 이전기관 종사자 |

- 공고마다 세대수가 0보다 큰 유형만 하위 질의가 된다. 더샵 분당하이스트는 6개(다자녀·신혼부부·생애최초·노부모·기관추천·신생아)다

## 판정값 5개

정의: `src/cheongyak_rag/generate/verdict.py:41` `VERDICTS`, 뜻은 같은 파일 system 프롬프트 88~97줄. 만든 티켓 #80.

| 값 | 뜻 |
| --- | --- |
| `ELIGIBLE` | 프로필에 있는 값이 요건을 채운다고 근거 문맥으로 확인된다 |
| `INELIGIBLE` | 프로필 값이 요건을 못 채운다고 근거 문맥으로 확인된다 |
| `CONDITIONAL` | 지금은 못 채우지만 공고 이후 신청자가 행동하면(전입, 통장 가입, 세대주 변경 등) 채운다 |
| `NEED_INFO` | 요건을 가릴 값이 프로필에 없다. 그 값만 있으면 판정이 정해진다 |
| `UNVERIFIABLE` | 근거 문맥에서 요건의 근거를 못 찾았거나 규정끼리 부딪힌다 |

- 합칠 때 우선순위: `INELIGIBLE` > `UNVERIFIABLE` > `NEED_INFO` > `CONDITIONAL` > `ELIGIBLE`(`docs/plans/0727-design-cheongyak-rag.md:168`). 여럿을 합치면 가장 앞의 값이 결과다. 집계(B8)는 #81
- 코드가 LLM 판정을 바꾸는 경우 둘: 남은 인용이 0개면 `UNVERIFIABLE`(`forced`), 축에 필요한 프로필 칸이 없으면 `ELIGIBLE`을 `NEED_INFO`로(`guarded`, `verdict.py:130` `REQUIRED_FIELDS`)

## 프로필 칸 15개

정의: `src/cheongyak_rag/profile.py:214` `Profile`. 만든 티켓 #77. 전부 비워 둘 수 있고, 빈 칸은 「모른다」는 뜻이다.

| 칸 | 뜻 |
| --- | --- |
| `birth_date` | 생년월일 |
| `married` | 공고일 현재 배우자가 있다 |
| `ever_married` | 혼인한 적이 있다(이혼·사별 포함) |
| `marriage_date` | 최초 혼인신고일 |
| `homeless_now` | 지금 무주택이다(제53조 판정은 사용자가 끝낸 값) |
| `ever_owned` | 집을 가진 적이 있다 |
| `homeless_since` | 무주택이 된 날 |
| `is_household_head` | 세대주다 |
| `children_unmarried` | 미혼 자녀 수 |
| `children_30plus_1y` | 30세 이상 자녀 중 1년 넘게 같이 산 수 |
| `ascendants_3y` | 3년 넘게 부양한 직계존속 수 |
| `ascendants_any_owner` | 부양하는 직계존속 중 집을 가진 사람이 있다 |
| `savings_join_date` | 청약통장 가입일 |
| `spouse_has_savings` | 배우자 청약통장이 있다 |
| `spouse_savings_join_date` | 배우자 청약통장 가입일 |

- 예치금·납입 횟수·소득·자산·거주 지역·당첨 이력 칸은 없다. 그래서 청약통장·거주·소득자산·재당첨·특별공급 유형 축은 ELIGIBLE을 낼 수 없다(#80 guard)

## 경로 — 신청할 수 있는 길 하나의 합친 판정

정의: `src/cheongyak_rag/generate/aggregate.py:71` `aggregate`, 일반 축 목록은 같은 파일 29줄 `GENERAL_AXES`. 만든 티켓 #81.

| 경로 | 합치는 축 | 개수 |
| --- | --- | --- |
| 일반공급 | 일반 축 5개(`GENERAL_AXES`: `homeless`·`account`·`residence`·`rewin`·`householder`) 중 켜진 것의 판정을 합친다 | 공고마다 1개 |
| 특별공급 유형별 | 켜진 일반 축 + 소득·자산 축(`income_asset`) + 그 유형의 `special_type` 하위 질의 | 공고에 세대수가 있는 유형마다 1개 |

- 전역 판정 = 일반공급 경로 판정이다. 특별공급 경로는 전역 판정에 들어가지 않는다
- 신청 가능한 경로 = 판정이 `ELIGIBLE`·`CONDITIONAL`인 경로다
- 합치는 규칙은 판정값 5개 절의 우선순위다. 꺼진 축의 판정은 합치지 않고, 호출이 실패해 판정이 없는 하위 질의는 `UNVERIFIABLE`로 센다

## trace 상태 2개

정의: `src/cheongyak_rag/trace.py:27` `OK`·`ERROR`, `traces.status` 칸에 들어간다. 만든 티켓 #83.

| 값 | 뜻 |
| --- | --- |
| `ok` | 질의가 B9 응답까지 갔다. `answer`·`verdict`·`steps`에 값이 있다 |
| `error` | 흐름 중간에 예외가 났다. `error`에 예외 이름과 메시지(프로필 값 가린 뒤)가 있고 `answer`·`verdict`는 null, `steps`는 빈 객체다 |

- 행 쓰기가 실패한 질의는 행이 없으므로 어느 상태도 아니다. 응답은 돌려주고 `trace_error`로 알린다
- `error` 행을 쓴 뒤 예외는 그대로 다시 올라간다

## 공고문 수집 결과 5개 — 공고 하나의 공고문 받기가 끝난 모습

정의: `src/cheongyak_rag/ingest/notice_doc.py:40` `RESULTS`, 뜻은 `src/cheongyak_rag/ingest/notice_doc_report.py:39` `MEANING`. 만든 티켓 #72.

| 값 | 뜻 |
| --- | --- |
| `pdf` | 공고문을 받았고 PDF로 열린다 |
| `hwp` | 받은 파일이 HWP·HWPX라 격리했다 |
| `other` | 받은 파일이 PDF·HWP가 아니라 격리했다 |
| `no_link` | 상세 페이지에 공고문 링크가 없다(지금은 LH 10건) |
| `error` | 받기가 실패했거나(HTTP·시간 초과·크기 초과), PDF라는데 안 열린다 |

- 링크가 둘 이상이면 링크마다 줄이 남고, 공고의 결과는 가장 나쁜 줄을 따른다(`error` > `other` > `hwp` > `pdf`)
- `pdf`는 HTTP 200이고 앞 바이트가 `%PDF-`이며 `pymupdf`로 열려 쪽수가 1 이상일 때만이다. 앞 바이트가 `%PDF-`가 아니면 `hwp`나 `other`로 격리하고, 앞 바이트가 `%PDF-`인데 안 열리거나 HTTP 200이 아니면 `error`다
- 목록은 `data/raw/notices/manifest.jsonl`(링크 하나가 한 줄)이고, 격리한 파일은 `data/raw/notices/quarantine/`에 있다

## 용어

plan·리포트·PR 본문·판단 로그에서 쓰는 말이다. 「쓰지 말 말」은 같은 것을 가리키는 다른 이름이라 쓰지 않는다.
제안자는 그 말을 먼저 쓴 쪽이다.

| 용어 | 뜻 | 쓰지 말 말 | 제안자 | 만든 티켓 |
| --- | --- | --- | --- | --- |
| 질의 | 공고 하나 × 프로필 하나를 B9 응답까지 돌리는 한 번. 그 안에 하위 질의가 여럿 있다 | 요청 · 쿼리 · 셀 | Claude | #83 |
| trace 행 | 질의 한 건이 판정 흐름을 지나간 기록. `traces` 테이블의 한 행이다 | 로그 · trace 레코드 | Claude | #83 |
| 프로필 해시 | 비밀 키로 만든 프로필 지문. 원본 없이 같은 프로필의 질의를 묶는다 | 프로필 ID | Claude | #83 |
| 가리기 | trace 행을 저장할 때 프로필 날짜를 `[프로필 값]`으로 바꾸는 것 | 마스킹 · 비식별화 | Claude | #83 |
| 하루 판정 한도 | 한국 날짜 기준 하루에 받는 판정 질의 수의 최대치. 넘으면 429를 낸다 | 레이트 리밋 · 요청 제한 | Claude | #85 |
| 공고문 | 청약홈 공고 상세 페이지의 「모집공고문 보기」로 받는 첨부 파일 하나 | 첨부파일 · 공고 PDF | Claude | #72 |
| 격리 | 받은 공고문이 PDF가 아니면 따로 두고 목록에 남기는 것. 읽지 않는다 | 건너뛰기 · 스킵 | Claude | #72 |
| 문항 | 골든셋의 질의 하나. 공고 하나 × 프로필 하나와, 그 공고에서 켜지는 하위 질의마다의 정답 라벨 | 케이스 · 샘플 · 셀 | Claude | #75 |
| 정답 라벨 | 하위 질의 하나의 참 판정값과 그 이유. 프로필 15칸 + 공고문 + 규칙으로 정한다 | gold label · 기대 판정 | 바탕 설계 §7, jw 기준에 씀 | #75 |
| 정답 근거 조문 | 정답 라벨을 받치는 조문 라벨(`제28조` 꼴)과 그 조문에서 그대로 옮긴 구절 | gold 조문 · 정답 조문 | 바탕 설계 §7, jw 기준에 씀 | #75 |
| 공고문 근거 | 정답 라벨이 기대는 공고문 쪽수와 그 쪽에서 그대로 옮긴 구절 | 공고 인용 · 출처 | Claude | #75 |
| 라벨 규칙 | 축마다 볼 프로필 칸·공고문 사실, 판정값 조건, 정답 근거 조문을 적은 문서 | 라벨링 가이드 | Claude | #75 |
| 따로 붙인 라벨 | 첫 라벨을 보지 않은 하위 에이전트가 라벨 규칙과 원문만 보고 같은 문항에 붙인 라벨 | 2차 라벨 · 교차 검증 | Claude | #75 |
