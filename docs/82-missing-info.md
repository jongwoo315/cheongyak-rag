# #82 결손 분석과 질문 순서 — 불가 판정을 먼저 내고 필요한 질문만 묻는다

측정: 골든셋 정답 라벨(`runs/75/golden.jsonl`)과 `runs/82/run.jsonl`·`runs/138/run.jsonl`을 읽어 이 파일의 코드(`generate/questions_report.py`)가 센 값이다. 설계는 `docs/plans/82-1114-design-missing-info.md`다.

## jw 기준

「입력한 프로필에서 어느 필드가 부족한지 분석이 된다, 불가 판정 여부를 먼저 진행하여 불필요한 질문을 하지 않는다」

- 구간: **다시 잰다** (통과: ①이 전부이고 ②가 0문항 / 다시 잰다: ①이 360~377개이거나 ②가 1~3문항 / 미완: ①이 359개 이하이거나 ②가 4문항 이상)

| 값 | 이번(runs/82) | 비교값 |
| --- | --- | --- |
| ① 결손 분석 — 정답 라벨이 NEED_INFO인 하위 질의 중 없는 정보 집합이 정답 `need`와 같은 수 | 378/378 | — |
| ② 불필요한 질문 — 시스템 질문에 불필요한 질문이 있는 문항 수 (50문항 중) | 1 | 32 (규칙 없이 `runs/138` 판정으로 경로를 안 거르고 NEED_INFO 하위 질의의 없는 정보를 다 묻는 값) |

불필요한 질문이 있는 문항 — 질문마다 그 질문이 쓰인 시스템 NEED_INFO 하위 질의:

| 문항 | 공고 | 불필요한 질문 | 쓰인 하위 질의 | 정답 판정(규칙) | 시스템 판정 |
| --- | --- | --- | --- | --- | --- |
| g21 | 상동역 롯데캐슬 시그니처 | marriage_status | special_type: 신혼부부 특별공급의 신청 자격과 요건은 어떻게 되나요? | INELIGIBLE (newlywed-3) | NEED_INFO |

- 이 질문 1개 중 정답 규칙이 이번에 옮기지 않은 규칙(referral-1·newlywed-3, 공고문 사실이 필요하다)인 것: **1개**. 시스템은 그 경로를 INELIGIBLE로 닫지 못해 질문이 남았다

## 실패 징후 2 — 빠진 질문이 늘었나

- 빠진 질문이 있는 문항: **24개** (비교값 24개: 같은 질문 거르기를 `runs/138` 판정에 돌린 값) → 구간 **정상** (정상: 비교값 이하 / 다시 잰다: 1~3 많다 / 미완: 4 이상 많다)

빠진 질문이 있는 문항:

| 문항 | 공고 | 빠진 질문 | `runs/138` 판정에서도 빠졌나 |
| --- | --- | --- | --- |
| g01 | 더샵 분당하이스트 | residence_area·residence_period | 예 |
| g02 | 더샵 분당하이스트 | minor_children_count | 예 |
| g05 | 충정로역자이르네 | referral_status | 예 |
| g09 | 써밋 클라비온 | minor_children_count·winning_history | 예 |
| g10 | 고덕강일지구 3단지 토지임대부(본청약) | residence_area·residence_period·birth_date | 예 |
| g13 | 중동역 다채로움 더원 | residence_area·residence_period·referral_status | 예 |
| g14 | 중동역 다채로움 더원 | residence_area·residence_period | 예 |
| g17 | 대전 경남아너스빌 센텀스카이 | child_age·minor_children_count | 예 |
| g18 | 대전 경남아너스빌 센텀스카이 | residence_area·residence_period | 예 |
| g19 | 상동역 롯데캐슬 시그니처 | residence_area·residence_period | 예 |
| g20 | 상동역 롯데캐슬 시그니처 | household_income·real_estate_value·child_age·minor_children_count | 아니오 |
| g22 | 용인반도체클러스터 동일하이빌 파크밸리(D1-1블록) | employer_status | 예 |
| g24 | 용인반도체클러스터 동일하이빌 파크밸리(D1-1블록) | residence_area·residence_period·employer_status | 예 |
| g25 | 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지) | minor_children_count·ascendant_age | 예 |
| g27 | 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지) | referral_status | 예 |
| g33 | 아산 그랑시티필하우스 | real_estate_value·residence_area·residence_period·referral_status·minor_children_count | 예 |
| g36 | 제일풍경채 첨단3지구(A6BL) | residence_area·residence_period | 예 |
| g37 | 두산위브더제니스 대연 | ascendant_age | 예 |
| g38 | 두산위브더제니스 대연 | referral_status | 예 |
| g39 | 아르티엠 라 테라스 | real_estate_value·residence_area·residence_period·minor_children_count | 아니오 |
| g42 | 시티오씨엘 9단지 오션파크뷰 | referral_status·minor_children_count | 예 |
| g45 | 포레나힐스테이트 진주 | residence_area·residence_period·minor_children_count | 예 |
| g47 | 신분평 에피트 더웨이시티 | minor_children_count | 예 |
| g49 | 진도 승원팰리체 더 테라스 | residence_area·residence_period·referral_status·minor_children_count | 예 |

## 실패 징후 3 — 규칙이 정답과 어긋났나

- 규칙이 INELIGIBLE로 정한 하위 질의 87개 중 정답 라벨이 INELIGIBLE이 아닌 것: **0개** → 구간 **정상** (정상: 0 / 다시 잰다: 1~3 / 미완: 4 이상)
- 규칙이 걸려야 하는데 `run.jsonl`의 시스템 판정이 INELIGIBLE이 아닌 하위 질의: **0개**

## 실패 징후 4 — 치명오답

- 치명오답(정답 INELIGIBLE인데 시스템 ELIGIBLE): **0개** (`runs/138`은 2/91) → 구간 **정상** (정상: 2 이하 / 다시 잰다: 3~5 / 미완: 6 이상)

## 지표 7개 — `runs/138` 대비 전후

판정 지표는 이번 기준이 아니다. 값만 적는다. 오른 것은 대부분 규칙이 INELIGIBLE을 낸 덕이다.

| 지표 | 뜻 | #138 | #82 |
| --- | --- | --- | --- |
| recall@5 | 정답 근거 조문 중 조문 검색 top-5에 든 것의 비율 | 92.8% (670/722) | 92.8% (670/722) |
| hit@5 | 정답 근거 조문이 하나라도 top-5에 든 정답 라벨의 비율 | 100.0% (524/524) | 100.0% (524/524) |
| citation precision | 시스템이 인용한 조문 중 정답 근거 조문인 것의 비율 | 74.2% (638/860) | 74.2% (638/860) |
| 판정 정확도 | 시스템 최종 판정값이 정답 라벨과 같은 비율 | 65.6% (344/524) | 80.2% (420/524) |
| 치명오답률 | 정답이 INELIGIBLE인 라벨 중 시스템이 ELIGIBLE을 낸 비율 | 2.2% (2/91) | 0.0% (0/91) |
| 정당 abstain 비율 | 정답이 NEED_INFO인 라벨 중 시스템도 abstain한 비율 | 94.4% (357/378) | 94.4% (357/378) |
| 부당 abstain 비율 | 정답이 ELIGIBLE·INELIGIBLE인 라벨 중 abstain한 비율 | 61.0% (89/146) | 10.3% (15/146) |

## 규칙이 바꾼 하위 질의 — 76개

규칙이 걸린 하위 질의 87개 중 모델 판정이 INELIGIBLE이 아니어서 규칙이 바꾼 것이 76개다. 모델 판정이 이미 INELIGIBLE이면 판정은 그대로이고 이유 문장만 규칙의 것이 된다.

| 규칙 | 모델 ELIGIBLE | 모델 CONDITIONAL | 모델 NEED_INFO | 모델 UNVERIFIABLE | 모델 INELIGIBLE | 합 |
| --- | --- | --- | --- | --- | --- | --- |
| firsttime-1 | 9 |  | 13 |  | 2 | 24 |
| homeless-1 | 2 |  | 1 |  | 2 | 5 |
| multichild-1 |  |  | 4 |  |  | 4 |
| newlywed-1 |  |  | 4 |  |  | 4 |
| elderly-3 |  |  | 4 |  |  | 4 |
| newborn-1 |  |  | 4 |  |  | 4 |
| householder-1 |  |  |  |  | 5 | 5 |
| elderly-1 |  |  | 5 |  |  | 5 |
| elderly-2 |  |  | 3 |  |  | 3 |
| account-1 | 5 |  | 1 |  |  | 6 |
| elderly-5 |  |  | 3 |  |  | 3 |
| newborn-2 |  |  | 4 |  |  | 4 |
| youth-3 |  |  |  | 1 |  | 1 |
| multichild-2 | 1 |  |  |  | 2 | 3 |
| firsttime-3 |  |  | 2 |  |  | 2 |
| newlywed-2 | 1 |  | 2 |  |  | 3 |
| elderly-4 |  |  | 3 |  |  | 3 |
| multichild-3 |  |  | 2 |  |  | 2 |
| newlywed-4 |  |  | 2 |  |  | 2 |

| 모델 판정 | 개수 |
| --- | --- |
| ELIGIBLE | 18 |
| CONDITIONAL | 0 |
| NEED_INFO | 57 |
| UNVERIFIABLE | 1 |
| INELIGIBLE | 11 |

## 질문 목록 예시 — 부분 프로필 문항 g05 (충정로역자이르네)

- 프로필에 값이 있는 칸: homeless_now, is_household_head
- 필요한 질문(정답 기준): savings_join_date·deposit_amount·household_income·real_estate_value·residence_area·residence_period·referral_status·child_age·minor_children_count·winning_history·ascendant_age·income_tax_years·ever_owned·married·marriage_date·children_unmarried·ascendants_3y·ascendants_any_owner

| 차례 | 정보 이름 | 문장 | 프로필 칸 | 불가 판정을 낼 수 있음 | 쓰이는 경로 |
| --- | --- | --- | --- | --- | --- |
| 1 | savings_join_date | 청약통장 가입일이 언제인가요? | 있음 | 예 | 일반공급 · 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 2 | ever_owned | 과거에 주택을 소유한 적이 있나요? | 있음 | 예 | 특별공급 생애최초 |
| 3 | married | 지금 배우자가 있나요? | 있음 | 예 | 특별공급 신혼부부 |
| 4 | marriage_date | 최초 혼인신고일이 언제인가요? | 있음 | 예 | 특별공급 신혼부부 |
| 5 | children_unmarried | 미혼 자녀가 몇 명인가요? | 있음 | 예 | 특별공급 다자녀가구 |
| 6 | ascendants_3y | 3년 넘게 부양한 직계존속이 몇 명인가요? | 있음 | 예 | 특별공급 노부모 부양 |
| 7 | ascendants_any_owner | 부양하는 직계존속 중 주택을 소유한 사람이 있나요? | 있음 | 예 | 특별공급 노부모 부양 |
| 8 | deposit_amount | 청약통장 예치금이 얼마인가요? | 입력란 없음 |  | 일반공급 · 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 9 | residence_area | 어느 지역에 거주하나요? | 입력란 없음 |  | 일반공급 · 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 10 | residence_period | 그 지역에 얼마나 거주했나요? | 입력란 없음 |  | 일반공급 · 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 11 | winning_history | 과거 당첨 이력이 있나요? | 입력란 없음 |  | 일반공급 · 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 12 | household_income | 세대의 월평균 소득이 얼마인가요? | 입력란 없음 |  | 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 13 | real_estate_value | 보유한 부동산 자산 가액이 얼마인가요? | 입력란 없음 |  | 특별공급 다자녀가구 · 특별공급 신혼부부 · 특별공급 생애최초 · 특별공급 노부모 부양 · 특별공급 신생아 |
| 14 | child_age | 자녀의 나이(출생 시점)가 어떻게 되나요? | 입력란 없음 |  | 특별공급 신생아 |
| 15 | minor_children_count | 미성년 자녀가 몇 명인가요? (태아·입양 포함) | 입력란 없음 |  | 특별공급 다자녀가구 |
| 16 | ascendant_age | 부양하는 직계존속이 몇 세인가요? | 입력란 없음 |  | 특별공급 노부모 부양 |
| 17 | income_tax_years | 소득세를 낸 기간이 몇 년인가요? | 입력란 없음 |  | 특별공급 생애최초 |

## 설계 §4 — 숫자 읽는 법

- 규칙과 정답 라벨이 같은 문서에서 나왔다. 2.1 규칙도 2.2 없는 정보도 라벨 규칙을 옮긴 것이고, 정답 라벨도 그 규칙으로 붙였다. 그래서 결손 분석 일치 수와 규칙이 고친 판정은 거의 정의상 맞는다. 같이 틀릴 수 있다 — 라벨 규칙이 법령을 잘못 읽었으면 둘 다 틀린다
- 따로 떼어 둔 확인용 문항은 없다. 골든셋이 유일한 측정 데이터다(#138과 같다)
- 판정 정확도·치명오답률이 #138보다 오르는 것은 대부분 규칙 덕이다. 규칙이 바꾼 하위 질의 수를 따로 센다
