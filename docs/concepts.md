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

## 용어

plan·리포트·PR 본문·판단 로그에서 쓰는 말이다. 「쓰지 말 말」은 같은 것을 가리키는 다른 이름이라 쓰지 않는다.
제안자는 그 말을 먼저 쓴 쪽이다.

| 용어 | 뜻 | 쓰지 말 말 | 제안자 | 만든 티켓 |
| --- | --- | --- | --- | --- |
| 질의 | 공고 하나 × 프로필 하나를 B9 응답까지 돌리는 한 번. 그 안에 하위 질의가 여럿 있다 | 요청 · 쿼리 · 셀 | Claude | #83 |
| trace 행 | 질의 한 건이 판정 흐름을 지나간 기록. `traces` 테이블의 한 행이다 | 로그 · trace 레코드 | Claude | #83 |
| 프로필 해시 | 비밀 키로 만든 프로필 지문. 원본 없이 같은 프로필의 질의를 묶는다 | 프로필 ID | Claude | #83 |
| 가리기 | trace 행을 저장할 때 프로필 날짜를 `[프로필 값]`으로 바꾸는 것 | 마스킹 · 비식별화 | Claude | #83 |
