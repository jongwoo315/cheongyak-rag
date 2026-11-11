# jw 표본 검토 — 정답 라벨 20개

시드 75 무작위. 판정값별로 고르게 뽑았다(없는 판정값은 제외). 항목마다 맞음/틀림과 메모를 적는다.

## 1. g27 · 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지)

- 프로필(full): birth_date=1985-06-24, married=True, ever_married=True, marriage_date=2021-04-20, homeless_now=True, ever_owned=True, homeless_since=2022-05-31, is_household_head=True, children_unmarried=0, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-07-22, spouse_has_savings=True, spouse_savings_join_date=2018-06-30
- 하위 질의: 무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?
- 정답 라벨: ELIGIBLE (규칙 homeless-2)
- 이유: homeless_now가 true라 제53조 판정이 끝난 무주택세대구성원이다.
- 정답 근거 조문 구절:
  - 제53조: 「주택 또는 분양권등의 공유지분을 소유하고 있는 경우에는 주택을 소유하고 있는 것으로 보되」
  - 제2조: 「세대원 전원이 주택을 소유하고 있지 않은 세대의 구성원을 말한다」
- 공고문 근거: 없음
- 맞음/틀림: 맞음
- 메모:

## 2. g38 · 두산위브더제니스 대연

- 프로필(partial): homeless_now=True, ever_owned=True, homeless_since=2023-06-30
- 하위 질의: 무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?
- 정답 라벨: ELIGIBLE (규칙 homeless-2)
- 이유: homeless_now가 true라 제53조 판정이 끝난 무주택세대구성원이다.
- 정답 근거 조문 구절:
  - 제53조: 「주택 또는 분양권등의 공유지분을 소유하고 있는 경우에는 주택을 소유하고 있는 것으로 보되」
  - 제2조: 「세대원 전원이 주택을 소유하고 있지 않은 세대의 구성원을 말한다」
- 공고문 근거: 없음
- 맞음/틀림: 맞음 
- 메모:

## 3. g26 · 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지)

- 프로필(partial): married=True, homeless_now=True, is_household_head=False
- 하위 질의: 무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?
- 정답 라벨: ELIGIBLE (규칙 homeless-2)
- 이유: homeless_now가 true라 제53조 판정이 끝난 무주택세대구성원이다.
- 정답 근거 조문 구절:
  - 제53조: 「주택 또는 분양권등의 공유지분을 소유하고 있는 경우에는 주택을 소유하고 있는 것으로 보되」
  - 제2조: 「세대원 전원이 주택을 소유하고 있지 않은 세대의 구성원을 말한다」
- 공고문 근거: 없음
- 맞음/틀림: 맞음 
- 메모:

## 4. g27 · 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지)

- 프로필(full): birth_date=1985-06-24, married=True, ever_married=True, marriage_date=2021-04-20, homeless_now=True, ever_owned=True, homeless_since=2022-05-31, is_household_head=True, children_unmarried=0, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-07-22, spouse_has_savings=True, spouse_savings_join_date=2018-06-30
- 하위 질의: 세대주만 청약할 수 있나요? 세대주 요건은 무엇인가요?
- 정답 라벨: ELIGIBLE (규칙 householder-2)
- 이유: is_household_head가 true라 세대주 요건을 채운다.
- 정답 근거 조문 구절:
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
  - 제2조: 「세대별 주민등록표에서 성년자인 세대주를 말한다」
- 공고문 근거:
  - 16쪽: 「만65세 이상의 직계존속(배우자의 직계존속 포함)을 3년 이상 계속하여 부양(같은 세대별 주민등록표등본에 등재되어 있는 경우에 한함)한 분」
- 맞음/틀림: 맞음 
- 메모:

## 5. g03 · 더샵 분당하이스트

- 프로필(partial): birth_date=1982-08-27, homeless_now=False, ever_owned=True, is_household_head=True
- 하위 질의: 세대주만 청약할 수 있나요? 세대주 요건은 무엇인가요?
- 정답 라벨: ELIGIBLE (규칙 householder-2)
- 이유: is_household_head가 true라 세대주 요건을 채운다.
- 정답 근거 조문 구절:
  - 제28조: 「세대주일 것」
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
  - 제2조: 「세대별 주민등록표에서 성년자인 세대주를 말한다」
- 공고문 근거:
  - 4쪽: 「수도권 투기과열지구 및 청약과열지역의 민간택지에서 공급하는 분양가상한제 미적용 민영주택으로」
  - 18쪽: 「만 65세 이상의 직계존속(배우자의 직계존속 포함)을 3년 이상 계속하여 부양하고 있는 분」
- 맞음/틀림: 맞음 
- 메모:

## 6. g45 · 포레나힐스테이트 진주

- 프로필(full): birth_date=1985-07-08, married=True, ever_married=True, marriage_date=2021-05-04, homeless_now=True, ever_owned=True, homeless_since=2022-06-14, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=0, ascendants_any_owner=False, savings_join_date=2024-08-05, spouse_has_savings=True, spouse_savings_join_date=2018-07-14
- 하위 질의: 무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?
- 정답 라벨: ELIGIBLE (규칙 homeless-2)
- 이유: homeless_now가 true라 제53조 판정이 끝난 무주택세대구성원이다.
- 정답 근거 조문 구절:
  - 제53조: 「주택 또는 분양권등의 공유지분을 소유하고 있는 경우에는 주택을 소유하고 있는 것으로 보되」
  - 제2조: 「세대원 전원이 주택을 소유하고 있지 않은 세대의 구성원을 말한다」
- 공고문 근거: 없음
- 맞음/틀림: 맞음 
- 메모:

## 7. g33 · 아산 그랑시티필하우스

- 프로필(full): birth_date=1985-09-01, married=True, ever_married=True, marriage_date=2021-06-28, homeless_now=True, ever_owned=True, homeless_since=2022-08-08, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-09-29, spouse_has_savings=True, spouse_savings_join_date=2018-09-08
- 하위 질의: 세대주만 청약할 수 있나요? 세대주 요건은 무엇인가요?
- 정답 라벨: ELIGIBLE (규칙 householder-2)
- 이유: is_household_head가 true라 세대주 요건을 채운다.
- 정답 근거 조문 구절:
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
  - 제2조: 「세대별 주민등록표에서 성년자인 세대주를 말한다」
- 공고문 근거:
  - 17쪽: 「만65세 이상의 직계존속(배우자의 직계존속 포함)을 3년 이상 계속하여 부양(같은 세대별 주민등록표등본에 등재되어 있는 경우에 한함)한 분」
- 맞음/틀림: 맞음
- 메모:

## 8. g48 · 신분평 에피트 더웨이시티

- 프로필(partial): birth_date=1982-09-30, homeless_now=False, ever_owned=True, is_household_head=True
- 하위 질의: 기관추천 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 referral-1)
- 이유: homeless_now가 false라 무주택세대구성원이 아니어서 기관추천 특별공급을 신청할 수 없다.
- 정답 근거 조문 구절:
  - 제36조: 「입주자모집공고일 현재 제4조제3항에 따른 공급대상인 무주택세대구성원(제8호의2에 해당하는 경우는 제외한다)으로서」
- 공고문 근거:
  - 11쪽: 「￭ 최초 입주자모집공고일 현재 무주택세대구성원으로서 아래 해당 기관의 추천 및 인정서류를 받으신 분」
- 맞음/틀림: 맞음 
- 메모:

## 9. g48 · 신분평 에피트 더웨이시티

- 프로필(partial): birth_date=1982-09-30, homeless_now=False, ever_owned=True, is_household_head=True
- 하위 질의: 노부모 부양 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 elderly-3)
- 이유: homeless_now가 false라 무주택세대구성원이 아니어서 노부모 부양 특별공급을 신청할 수 없다.
- 정답 근거 조문 구절:
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
- 공고문 근거:
  - 15쪽: 「￭ 만65세 이상의 직계존속(배우자의 직계존속 포함)을 3년 이상 계속하여 부양(같은 세대별 주민등록표등본에 등재되어
  있는 경우에 한함)한 분」
- 맞음/틀림: 맞음 
- 메모:

## 10. g39 · 아르티엠 라 테라스

- 프로필(full): birth_date=1980-07-25, married=True, ever_married=True, marriage_date=2015-07-05, homeless_now=True, ever_owned=True, homeless_since=2022-06-14, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-08-05, spouse_has_savings=True, spouse_savings_join_date=2018-07-14
- 하위 질의: 신혼부부 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 newlywed-2)
- 이유: 최초 혼인신고일 2015-07-05부터 모집공고일 2026-08-14까지 7년이 넘어 혼인기간 7년 이내 요건을 채우지 못한다.
- 정답 근거 조문 구절:
  - 제41조: 「이 7년 이내일 것」
- 공고문 근거:
  - 10쪽: 「혼인기간이 7년 이내(혼인신고일 기준, 동일인과의 재혼인 경우에는 이전 혼인기간을 포함)인 분」
- 맞음/틀림: 맞음
- 메모:

## 11. g49 · 진도 승원팰리체 더 테라스

- 프로필(full): birth_date=1980-09-18, married=True, ever_married=True, marriage_date=2015-08-29, homeless_now=True, ever_owned=True, homeless_since=2022-08-08, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-09-29, spouse_has_savings=True, spouse_savings_join_date=2018-09-08
- 하위 질의: 신혼부부 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 newlywed-2)
- 이유: 최초 혼인신고일 2015-08-29부터 모집공고일 2026-10-08까지 7년이 넘어 혼인기간 7년 이내 요건을 채우지 못한다.
- 정답 근거 조문 구절:
  - 제41조: 「이 7년 이내일 것」
- 공고문 근거:
  - 11쪽: 「혼인기간이 7년 이내(혼인신고일 기준, 동일인과의 재혼인 경우에는 이전 혼인기간을 포함)인 분」
- 맞음/틀림: 맞음 
- 메모:

## 12. g29 · 문수데시앙2단지 공가세대 일반공급

- 프로필(partial): birth_date=1991-08-25, savings_join_date=2026-05-17
- 하위 질의: 청약통장 가입 기간과 예치금 기준은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 account-1)
- 이유: 청약통장 가입일 2026-05-17부터 모집공고일 2026-08-28까지 3개월이라 1순위 가입 기간 6개월에 못 미친다.
- 정답 근거 조문 구절:
  - 제27조: 「주택청약종합저축에 가입하여 6개월이 지난 자로서 매월 약정납입일에 월납입금을 6회 이상 납입한 자」
- 공고문 근거:
  - 2쪽: 「청약저축 또는 주택청약종합저축에 가입하여 6개월이 경과되고 매월 약정
납입일에 월납입금을 6회 이상 납입한 자」
- 맞음/틀림: 맞음 
- 메모:

## 13. g06 · 충정로역자이르네

- 프로필(partial): married=True, homeless_now=True, is_household_head=False
- 하위 질의: 노부모 부양 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: INELIGIBLE (규칙 elderly-2)
- 이유: is_household_head가 false라 세대주에 한정되는 노부모 부양 특별공급을 신청할 수 없다.
- 정답 근거 조문 구절:
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
- 공고문 근거:
  - 15쪽: 「만 세 이상의 직계존속배우자의 직계존속 포함을 년 이상 계속하여 부양」
- 맞음/틀림: 맞음 
- 메모:

## 14. g26 · 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지)

- 프로필(partial): married=True, homeless_now=True, is_household_head=False
- 하위 질의: 세대주만 청약할 수 있나요? 세대주 요건은 무엇인가요?
- 정답 라벨: INELIGIBLE (규칙 householder-1)
- 이유: is_household_head가 false라 세대주 요건을 채우지 못한다.
- 정답 근거 조문 구절:
  - 제46조: 「무주택세대구성원(세대주에 한정하며」
  - 제2조: 「세대별 주민등록표에서 성년자인 세대주를 말한다」
- 공고문 근거:
  - 16쪽: 「만65세 이상의 직계존속(배우자의 직계존속 포함)을 3년 이상 계속하여 부양(같은 세대별 주민등록표등본에 등재되어 있는 경우에 한함)한 분」
- 맞음/틀림: 맞음 
- 메모:

## 15. g05 · 충정로역자이르네

- 프로필(partial): homeless_now=True, is_household_head=True
- 하위 질의: 신생아 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 newborn-3)
- 이유: 자녀 나이와 소득·예치금 칸이 프로필에 없어 요건을 채우는지 알 수 없다.
- 정답 근거 조문 구절:
  - 제35조의3: 「입주자모집공고일 현재 2세 미만(2세가 되는 날을 포함한다)의 자녀」
- 공고문 근거:
  - 18쪽: 「입주자모집공고일 현재 세 미만 세가 되는 날을 포함한다의 자녀임신중이거나 입양한 경우 포함」
- 맞음/틀림: 맞음 
- 메모:

## 16. g16 · 대전 경남아너스빌 센텀스카이

- 프로필(empty): (15칸 전부 비었다)
- 하위 질의: 대전 지역 거주 요건과 거주 기간은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 residence-1)
- 이유: 프로필에 거주 지역·기간 칸이 없어 이 공고의 거주 요건을 채우는지 알 수 없다.
- 정답 근거 조문 구절:
  - 제4조: 「입주자모집공고일 현재 해당 주택건설지역에 거주하는 성년자에게 1인 1주택의 기준으로 공급한다」
- 공고문 근거:
  - 23쪽: 「①지역 : 해당지역 거주자(대전광역시 1년 이상 계속 거주자) → 기타지역 거주자(대전광역시 1년 미만 거주자 및 세종특별자치시 및 충청남도 거주자)」
- 맞음/틀림: 맞음
- 메모:

## 17. g17 · 대전 경남아너스빌 센텀스카이

- 프로필(full): birth_date=1985-07-28, married=True, ever_married=True, marriage_date=2021-05-24, homeless_now=True, ever_owned=True, homeless_since=2022-07-03, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-08-25, spouse_has_savings=True, spouse_savings_join_date=2018-08-03
- 하위 질의: 다자녀가구 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 multichild-4)
- 이유: 미혼 자녀 중 미성년 수와 태아·입양 여부를 프로필로 알 수 없다.
- 정답 근거 조문 구절:
  - 제40조: 「입주자모집공고일 현재 미성년자인 두 명 이상의 자녀를 둔 무주택세대구성원에게」
- 공고문 근거:
  - 11쪽: 「만19세 미만의 자녀 2명 이상(태아, 입양자녀 포함)이 있는 분」
- 맞음/틀림: 맞음 
- 메모:

## 18. g34 · 아산 그랑시티필하우스

- 프로필(partial): birth_date=1982-09-23, homeless_now=False, ever_owned=True, is_household_head=True
- 하위 질의: 청약통장 가입 기간과 예치금 기준은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 account-3)
- 이유: savings_join_date가 비어 있어 1순위 가입 기간 6개월을 채웠는지 알 수 없다.
- 정답 근거 조문 구절:
  - 제28조: 「주택청약종합저축에 가입하여 6개월이 지나고 별표 2의 예치기준금액에 상당하는 금액을 납입한 자」
- 공고문 근거:
  - 22쪽: 「① 청약예금 : 해당 주택에 신청가능한 청약예금에 가입하여 6개월이 경과하고, 지역별·면적별 예치금액 이상인 분」
- 맞음/틀림: 맞음
- 메모:

## 19. g49 · 진도 승원팰리체 더 테라스

- 프로필(full): birth_date=1980-09-18, married=True, ever_married=True, marriage_date=2015-08-29, homeless_now=True, ever_owned=True, homeless_since=2022-08-08, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=1, ascendants_any_owner=False, savings_join_date=2024-09-29, spouse_has_savings=True, spouse_savings_join_date=2018-09-08
- 하위 질의: 신생아 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 newborn-3)
- 이유: 자녀 나이와 소득·예치금 칸이 프로필에 없어 요건을 채우는지 알 수 없다.
- 정답 근거 조문 구절:
  - 제35조의3: 「입주자모집공고일 현재 2세 미만(2세가 되는 날을 포함한다)의 자녀」
- 공고문 근거:
  - 18쪽: 「입주자모집공고일 현재 2세 미만(2세가 되는 날을 포함한다)의 자녀(임신중이거나 입양한 경우 포함)가 있는 분」
- 맞음/틀림: 맞음
- 메모:

## 20. g45 · 포레나힐스테이트 진주

- 프로필(full): birth_date=1985-07-08, married=True, ever_married=True, marriage_date=2021-05-04, homeless_now=True, ever_owned=True, homeless_since=2022-06-14, is_household_head=True, children_unmarried=2, children_30plus_1y=0, ascendants_3y=0, ascendants_any_owner=False, savings_join_date=2024-08-05, spouse_has_savings=True, spouse_savings_join_date=2018-07-14
- 하위 질의: 신혼부부 특별공급의 신청 자격과 요건은 어떻게 되나요?
- 정답 라벨: NEED_INFO (규칙 newlywed-5)
- 이유: 소득·자산 칸이 프로필에 없어 요건을 채우는지 알 수 없다.
- 정답 근거 조문 구절:
  - 제41조: 「해당 세대의 월평균 소득이 다음의 어느 하나에 해당할 것」
- 공고문 근거:
  - 14쪽: 「혼인기간이 7년 이내(혼인신고일 기준, 동일인과의 재혼인 경우에는 이전 혼인기간을 포함)인 분」
- 맞음/틀림: 맞음 
- 메모:

