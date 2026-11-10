# 라벨 규칙 (#75)

정답 라벨을 붙일 때 따르는 규칙이다. 하위 질의(축 하나, 특별공급은 유형 하나)마다 라벨 하나를 붙이고, 같은 상황에는 같은 규칙이 걸린다.
규칙의 조문은 MST 286965 `chunks`의 본문이다. 규칙 번호(`homeless-1` 꼴)는 라벨의 `rule` 칸에 적는다.

## 1. 원칙

- 정답 라벨은 **프로필 15칸 + 공고문 + 규칙**으로 정해지는 참값이다. 시스템이 지금 어떻게 답하는지는 보지 않는다(그걸 재는 것이 #76이다).
- 요건을 가리려면 프로필에 없는 정보(거주 지역·기간, 소득·자산, 예치금, 당첨 이력, 직장, 자녀 나이)가 필요하면 `NEED_INFO`다.
- 프로필 칸만으로 요건이 안 채워진다고 정해지면 `INELIGIBLE`이다. 다른 요건에 필요한 정보가 빠져 있어도 그렇다
  (한 요건이라도 확정 실패면 `INELIGIBLE`이 `NEED_INFO`보다 앞선다).
- 같은 칸이라도 요건에 갈래가 여럿이고 갈래를 프로필로 못 가리면 `INELIGIBLE`을 주지 않고 `NEED_INFO`다.
- `ELIGIBLE`은 그 축의 요건 전부가 프로필 칸으로 확인될 때만이다. 프로필에 예치금·소득·거주·당첨 이력 칸이 없어서 무주택·세대주 축에서만 나온다.
- `CONDITIONAL`·`UNVERIFIABLE`을 쓰는 규칙은 없다. 프로필은 모집공고일 기준 값이라 공고 뒤의 행동(전입, 세대주 변경, 통장 가입)으로 채워지는 요건이 없고(세대주 변경과
  거주지 전입의 기준일은 모집공고일 당일이다), 요건의 근거 조문은 `chunks`에서 읽을 수 있다. 어느 규칙으로도 안 정해지면 값은 직접 정하고 `rule`을 null로 두고 `rule_note`에 이유를 적는다.

## 2. 기준일과 날짜 계산

- 기준일(`as_of`)은 문항 공고의 모집공고일이다. 프로필의 모든 날짜는 이 날 이전이다.
- 만 나이 = `as_of` 기준 생일이 지난 만 나이.
- 「가입하여 N개월이 지나고」 = 가입일에 N개월을 더한 날이 `as_of` 이전(같은 날 포함)이다. 문항은 이 경계에서 한 달 이상 떨어지게 짠다.
- 혼인기간 7년 이내 = 최초 혼인신고일(`marriage_date`)에 7년을 더한 날이 `as_of` 이후(같은 날 포함)다.

## 3. 축의 뜻 — 이 문서가 정한 약속

| 축 | 라벨이 답하는 것 |
| --- | --- |
| `homeless` 무주택 | 신청자 세대가 무주택세대구성원(제2조제4호)인가. 유주택자도 신청할 수 있는 공급이 있어도 이 축은 무주택 요건을 채우는지를 본다 |
| `account` 청약통장 | 이 공고의 **1순위** 통장 요건(가입 기간 + 예치금)을 채우는가 |
| `residence` 거주 | 이 공고의 해당 주택건설지역·우선공급 거주 요건을 채우는가 |
| `income_asset` 소득·자산 | 이 공고가 공급하는 특별공급 유형의 소득·자산 기준을 채우는가 |
| `rewin` 재당첨제한 | 재당첨 제한 기간에 걸린 당첨 이력이 없는가 |
| `householder` 세대주 | 이 공고에서 세대주 요건이 걸린 공급(투기과열지구·청약과열지역 1순위, 노부모 부양 특별공급)의 세대주 요건을 채우는가 |
| `special_type` | 그 유형 특별공급의 신청 자격을 채우는가 |

## 4. 축 규칙

규칙은 위에서부터 보고 처음 맞는 것을 쓴다. 인용 조문은 `citations`, 그 조문에서 옮긴 구절은 `article_quotes`, 공고문 근거는 `notice_evidence`에 적는다.

### 4.1 무주택 `homeless`

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `homeless-1` | `homeless_now` = false | INELIGIBLE | 제53조, 제2조 |
| `homeless-2` | `homeless_now` = true | ELIGIBLE | 제53조, 제2조 |
| `homeless-3` | `homeless_now` 비었음 | NEED_INFO(`homeless_now`) | 제53조 |

- `homeless_now`는 제53조 판정을 사용자가 끝낸 값이다. `ever_owned`·`homeless_since`는 이 축의 판정값을 바꾸지 않는다. `fields`에는 `homeless_now`만 적는다.
- 공고문 근거는 달지 않는다.

### 4.2 청약통장 `account`

- 공고문 사실: 이 공고의 1순위 통장 가입 기간 N개월(`runs/75/notices.json`의 `account_months`). 투기과열지구·청약과열지역은 24, 수도권 12, 그 밖은 6이 기본이고 시·도지사가
  늘려 공고하면 공고문 숫자를 따른다. 민영주택은 제28조, 국민주택은 제27조를 인용한다.

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `account-1` | `savings_join_date`가 있고 `as_of`까지 N개월이 안 지났다 | INELIGIBLE | 제28조(또는 제27조) |
| `account-2` | `savings_join_date`가 있고 N개월이 지났다 | NEED_INFO(민영 `deposit_amount`, 국민주택 `payment_count`) | 제28조(또는 제27조), 제10조 |
| `account-3` | `savings_join_date` 비었음 | NEED_INFO(`savings_join_date`와 위와 같은 칸) | 제28조(또는 제27조) |

- 국민주택(공고문이 납입 횟수를 1순위 요건으로 적고 예치금은 적지 않은 공고)은 제27조와 `payment_count`를 쓴다. 예치금·납입 횟수 칸이 프로필에 없어서 이 축은 ELIGIBLE이 나오지 않는다.
- 이 공고의 N과 인용할 조는 `runs/75/notices.json`의 `label_facts`(`account_months`, `account_article`)에 있다.
- 공고문 근거: 이 공고의 1순위 통장 요건 문장(`facts.account_first_rank`).

### 4.3 거주 `residence`

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `residence-1` | 항상 | NEED_INFO(`residence_area`, `residence_period`) | 제4조. 공고문이 대규모 택지개발지구·공공주택지구의 지역 우선공급 비율을 적었으면 제34조도 |

- 프로필에 거주 지역·기간 칸이 없다. 행정중심복합도시 예정지역처럼 거주 지역과 무관하게 공급대상이어도 해당지역 거주자 우선공급이 있어서 NEED_INFO다. <!-- style-exempt -->
- 공고문 근거: 거주 요건 문장(`facts.residence`).

### 4.4 소득·자산 `income_asset`

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `income-1` | 항상 | NEED_INFO(`household_income`, `real_estate_value`) | 이 공고가 공급하는 유형 중 소득·자산 기준이 있는 유형의 조문: 신혼부부 제41조, 생애최초 제43조, 신생아 제35조의3 |

- 프로필에 소득·자산 칸이 없다.
- 공고문 근거는 달지 않는다(소득 기준표는 이 골든셋이 따로 옮기지 않는다).

### 4.5 재당첨제한 `rewin`

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `rewin-1` | 항상 | NEED_INFO(`winning_history`) | 제54조 |

- 공고문 근거: 재당첨 제한 문장(`facts.rewin`)이 있으면 단다.

### 4.6 세대주 `householder`

| 번호 | 조건 | 판정값 | 정답 근거 조문 |
| --- | --- | --- | --- |
| `householder-1` | `is_household_head` = false | INELIGIBLE | 투기과열지구·청약과열지역이면 제28조, 노부모 부양 특별공급을 공급하면 제46조, 세대주 정의 제2조 |
| `householder-2` | `is_household_head` = true | ELIGIBLE | 위와 같다 |
| `householder-3` | `is_household_head` 비었음 | NEED_INFO(`is_household_head`) | 위와 같다 |

- 투기과열지구·청약과열지역인지는 **공고문**을 따른다(공고문과 DB 규제 표시가 어긋나면 어긋남 표에 적는다). 공고문이 규제 지역이라고 하지 않았으면 제28조를 인용하지 않는다.
- 공고문 근거: 규제 지역 문장(`facts.regulation`) 또는 노부모 부양 자격 문장.

### 4.7 특별공급 유형 `special_type`

유형마다 하위 질의가 하나다. 규칙 번호는 유형 이름표를 앞에 둔다: `multichild`(다자녀가구) · `newlywed`(신혼부부) · `firsttime`(생애최초) · `elderly`(노부모 부양) ·
`newborn`(신생아) · `referral`(기관추천) · `youth`(청년) · `relocated`(이전기관 종사자). 공통: 소득·자산·거주·직장·자녀 나이처럼 프로필에 없는 요건이 있어서 ELIGIBLE은 나오지 않는다.
정답 근거 조문은 그 유형의 조문이다: 다자녀 제40조, 신혼부부 제41조, 생애최초 제43조, 노부모 부양 제46조, 신생아 제35조의3, 청년 제35조의2, 이전기관 제47조,
기관추천 민영주택 제36조·국민주택 제35조. 공고문 근거는 그 유형의 자격 문장(`facts.special_types[].quote`).

| 번호 | 조건 | 판정값 |
| --- | --- | --- |
| `multichild-1` | `homeless_now` = false | INELIGIBLE (미성년 자녀 둔 무주택세대구성원 요건, 제40조) |
| `multichild-2` | `children_unmarried` = 0 | INELIGIBLE (자녀가 없으면 태아를 넣어도 둘이 안 된다) |
| `multichild-3` | 그 밖 | NEED_INFO(`minor_children_count`) — 미혼 자녀 중 미성년 수와 태아·입양을 프로필로 못 가린다. `children_unmarried` = 1은 태아 갈래 때문에 여기다 |
| `newlywed-1` | `homeless_now` = false | INELIGIBLE (무주택세대구성원, 제41조) |
| `newlywed-2` | `married` = true이고 `marriage_date`가 있고 혼인기간 7년 초과 | INELIGIBLE (제41조제1항제1호가목) |
| `newlywed-3` | 그 밖 | NEED_INFO(`household_income`, `real_estate_value`; `married`가 false면 갈래 확인용 `marriage_status`도) — 혼인 중이 아니면 예비신혼부부·한부모가족 갈래를 프로필로 못 가린다 |
| `firsttime-1` | `ever_owned` = true | INELIGIBLE (제43조 생애 최초: 세대에 속한 모든 자가 과거 주택을 소유한 사실이 없을 것) |
| `firsttime-2` | `homeless_now` = false | INELIGIBLE (무주택세대구성원) |
| `firsttime-3` | 그 밖 | NEED_INFO(`household_income`, `real_estate_value`, `income_tax_years`, `deposit_amount`) |
| `elderly-1` | `ascendants_3y` = 0 | INELIGIBLE (3년 이상 부양한 직계존속이 없다) |
| `elderly-2` | `is_household_head` = false | INELIGIBLE (세대주에 한정, 제46조제1항제2호) |
| `elderly-3` | `homeless_now` = false | INELIGIBLE |
| `elderly-4` | `ascendants_any_owner` = true | INELIGIBLE (제53조 단서: 제46조 특별공급은 60세 이상 직계존속 소유 예외를 적용하지 않으므로 부양 직계존속이 주택을 가지면 무주택이 아니다) |
| `elderly-5` | 그 밖 | NEED_INFO(`ascendant_age`, `deposit_amount`) |
| `newborn-1` | `homeless_now` = false | INELIGIBLE (제28조제1항 1순위 무주택세대구성원, 제35조의3) |
| `newborn-2` | 그 밖 | NEED_INFO(`child_age`, `household_income`, `deposit_amount`) |
| `referral-1` | `homeless_now` = false | INELIGIBLE (무주택세대구성원, 제36조·제35조) |
| `referral-2` | 그 밖 | NEED_INFO(`referral_status`) — 기관 추천 대상인지는 프로필로 못 가린다 |
| `youth-1` | `ever_owned` = true | INELIGIBLE (과거 주택을 소유한 사실이 없는 사람, 제35조의2) |
| `youth-2` | `married` = true | INELIGIBLE (혼인 중이 아닐 것) |
| `youth-3` | `birth_date`가 있고 `as_of`의 만 나이가 19세 미만 또는 39세 초과 | INELIGIBLE (19세 이상 39세 이하) |
| `youth-4` | 그 밖 | NEED_INFO(`household_income`, `deposit_amount`) |
| `relocated-1` | 항상 | NEED_INFO(`employer_status`) — 이전기관 종사자 여부는 프로필로 못 가린다 |

- 한 유형에서 INELIGIBLE 규칙이 여럿 맞으면 표에서 앞선 규칙의 번호를 `rule`에 적는다.
- `newlywed`의 갈래(예비신혼부부·한부모가족)는 공고문에 있는 것만 갈래다. 공고문 신혼부부 자격 문장에 둘 다 없으면 `married` = false도 혼인 중이 아니라는 확정 실패라
  INELIGIBLE이고 이때 `rule`은 null, `rule_note`에 이유를 적는다.
- `referral-1`의 예외: 공고문의 기관추천 대상에 도시재생 토지 소유자(제35조제1항제27호의2)가 있으면 `homeless_now` = false도 갈래가 되므로 `referral-2`다.

## 5. 라벨 칸

`runs/75/golden.jsonl`의 정답 라벨 하나는 다음 칸을 갖는다.

| 칸 | 내용 |
| --- | --- |
| `axis` | 축 id(`homeless` 등) |
| `query` | `axes.plan`의 하위 질의 문장 그대로 |
| `verdict` | `ELIGIBLE` · `INELIGIBLE` · `CONDITIONAL` · `NEED_INFO` · `UNVERIFIABLE` |
| `reason` | 이유 한 문장. 어느 칸의 어느 값이 어떤 요건에 걸렸는지 쓴다 |
| `fields` | 판정에 쓴 프로필 칸 이름 목록 |
| `need` | `NEED_INFO`일 때 없는 정보 이름 목록, 아니면 빈 배열 |
| `citations` | 정답 근거 조문 라벨(`제28조` 꼴) 목록, 1개 이상 |
| `article_quotes` | 라벨마다 그 조문 본문에서 **그대로 옮긴** 구절 `{"제28조": "…"}` |
| `notice_evidence` | `{page, quote}` 목록. 공고문에 기대지 않으면 빈 배열 |
| `rule` | 따른 규칙 번호. 규칙으로 안 정해졌으면 null |
| `rule_note` | `rule`이 null일 때 이유. 아니면 null |

구절은 공백 말고는 한 글자도 바꾸지 않는다. 줄임표와 요약은 쓰지 않는다.
