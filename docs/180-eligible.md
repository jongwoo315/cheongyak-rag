# #180 「정보가 없다」에 기대는 ELIGIBLE 막기 — 측정

- jw 기준: 「'정보가 없음' 프로필 칸에 정답 라벨 'ELIGIBLE'이 붙는 케이스가 발생하지 않는다」
  - 되물은 뒤: 「정답 라벨」은 시스템 판정, LLM이 낸 ELIGIBLE을 뜻한다
- 표본은 골든셋 50문항(`runs/180/run.jsonl`)과 시연 18쌍이다
  - 시연 18쌍은 `runs/180/demo/last_run.json`이다
- 착수 때 값은 변경 전 코드로 돌린 `runs/82`·`runs/81`을 같은 함수로 센 것이다
- 「정보가 없음」 칸은 하위 질의 하나에서 아래 셋 중 하나에 드는 것이다
  - 결손 분석(#82 `questions.analyze`)의 없는 정보
  - 결손 분석의 불가 판정을 낼 수 있는 빈 칸
  - 그 하위 질의에 걸리는 프로필 가능 규칙이 보는 칸 중 비어 있는 것

## 실패 징후 1~5

| 징후 | 착수 때 값 | 이번 값 | 구간 |
| --- | --- | --- | --- |
| 1. jw 기준 — 최종 ELIGIBLE 중 「정보가 없음」 칸이 있는 하위 질의 | 골든셋 0/44 · 시연 0/8 | 골든셋 0/55 · 시연 0/8 · 합 0 | 통과 |
| 2. 이유를 LLM이 쓴 최종 ELIGIBLE | 골든셋 44/44 · 시연 8/8 | 골든셋 0/55 · 시연 0/8 · 합 0 | 정상 |
| 3. 틀린 ELIGIBLE — 골든셋 최종 ELIGIBLE인데 정답 라벨이 ELIGIBLE이 아닌 것 | 0/44 | 0/55 | 정상 |
| 4. 판정 정확도 — 골든셋 맞힌 하위 질의 | 421/524 | 432/524 | 정상 |
| 5. 치명오답 — 정답이 INELIGIBLE인 하위 질의에 최종 ELIGIBLE | 0/91 | 0/91 | 정상 |

- 구간: 징후 1은 0 통과 · 1~2 다시 잰다 · 3 이상 미완이다
- 징후 2·3·5는 0 정상 · 1~2 다시 잰다 · 3 이상 미완이다
- 징후 4는 421 이상 정상 · 416~420 다시 잰다 · 415 이하 미완이다

## 지표 7개 — 변경 전(`runs/82`)과 변경 후(`runs/180`)

| 지표 | 변경 전 | 변경 후 |
| --- | --- | --- |
| recall@5 | 92.8% (670/722) | 92.8% (670/722) |
| hit@5 | 100.0% (524/524) | 100.0% (524/524) |
| citation precision | 74.2% (638/860) | 74.2% (638/860) |
| 판정 정확도 | 80.3% (421/524) | 82.4% (432/524) |
| 치명오답률 | 0.0% (0/91) | 0.0% (0/91) |
| 정당 abstain 비율 | 94.4% (357/378) | 94.4% (357/378) |
| 부당 abstain 비율 | 9.6% (14/146) | 2.1% (3/146) |

- 판정 정확도와 치명오답만 이번 기준이다. 나머지는 전후 값만 적는다

## 가능 규칙이 이유를 쓴 하위 질의 — 규칙별 · 모델 판정별

- 두 표본의 최종 ELIGIBLE 중 이유가 가능 규칙 문장인 하위 질의 수다
- 모델 판정이 ELIGIBLE이 아닌 칸은 판정값까지 코드가 바꾼 것이다
- 모델 판정이 ELIGIBLE인 칸은 이유만 바꾼 것이다

| 규칙 | ELIGIBLE | CONDITIONAL | NEED_INFO | UNVERIFIABLE | INELIGIBLE | 합 |
| --- | --- | --- | --- | --- | --- | --- |
| homeless-2 | 26 | 0 | 10 | 0 | 0 | 36 |
| householder-2 | 26 | 0 | 0 | 1 | 0 | 27 |

- 합 63개는 최종 ELIGIBLE 63개 중 규칙이 이유를 쓴 것이다
- 착수 때 값은 0개다

## 골든셋에서 `runs/82`와 최종 판정이 달라진 하위 질의 — 11개

| 문항 | 축 | 정답 라벨 | 변경 전 판정 | 변경 후 판정 | 가능 규칙 |
| --- | --- | --- | --- | --- | --- |
| g05 충정로역자이르네 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g06 충정로역자이르네 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g11 고덕강일지구 3단지 토지임대부(본청약) | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g18 대전 경남아너스빌 센텀스카이 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g21 상동역 롯데캐슬 시그니처 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g24 용인반도체클러스터 동일하이빌 파크밸리(D1-1블록) | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g26 세종 우미 린 센터파크(행정중심복합도시 5-2생활권 S1블록, 글미마을 9단지) | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g38 두산위브더제니스 대연 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g44 달서자이 제니크 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |
| g44 달서자이 제니크 | householder | ELIGIBLE | UNVERIFIABLE | ELIGIBLE | householder-2 |
| g46 포레나힐스테이트 진주 | homeless | ELIGIBLE | NEED_INFO | ELIGIBLE | homeless-2 |

## 설계 §4 — 숫자 읽는 법

- jw 기준 측정값은 이번 변경 전에도 0이다. 프로필 칸이 빈 ELIGIBLE은 #80 ELIGIBLE guard가 이미 막고 있다. 이번 티켓이 바꾸는 것은 화면에 나가는 이유(같이 재는 것 첫 줄)와, 칸이 찼는데 LLM이 놓친 ELIGIBLE이다
- 규칙과 정답 라벨이 같은 문서에서 나왔다. 프로필 가능 규칙은 라벨 규칙 ELIGIBLE 줄을 옮긴 것이다. 판정 정확도가 오르면 거의 정의상 오른 것이다(#82와 같다)
- 「정보가 없음」 칸 정의가 결손 분석에 기댄다. 결손 분석 표가 축에 필요한 정보를 빠뜨렸으면 측정값도 같이 0으로 나온다. #82에서 결손 분석은 정답 라벨 `need`와 378/378 같았다
