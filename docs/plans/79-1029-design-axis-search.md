# #79 설계 — 요건을 7축으로 쪼개고 축마다 따로 검색한다

**Tier:** C · **Notion:** #79 · 브랜치 `feat/79-axis-search`

## jw 기준

「7축별로 나눠서 retriever 단계가 잘돌고, 켜진 축 목록과 축마다 검색된 근거 청크 top-k를 확인한다」

## 1. 지금 상태

RAG 파이프라인 지도 Lane B로 보면 B1(#77 프로필 정규화)·B3(#78 공고별 법령 버전)까지 있고 B4·B5가 없다.

| 단계 | 지금 | 위치 |
| --- | --- | --- |
| B3 as-of | 공고마다 법령 버전 MST를 고른다. 84건 전부 MST 286965 | view `notice_law_versions`(0003), `asof.py` |
| 색인 | 조문 88 + FAQ 480 청크가 DB에 있다. source별 HNSW 부분 인덱스, `law_mst` 칸 | `chunks`(0004), `retrieval/index_db.py` `nearest()` |
| 검색 | 질문 한 줄을 메모리에서 hybrid(BM25 + dense → RRF)로 찾는다. 조문 5개·FAQ 3개 | `retrieval/query.py` `Index.search` |
| B4 요건 쪼개기 | 없다 | |
| B5 축별 검색 | 없다 | |

## 2. 7축 (마스터 설계 `docs/plans/0727-design-cheongyak-rag.md` §4)

축 하나 = 하위 질의 하나 = 검색 하나. 하위 질의는 축마다 고정 문장에 공고 값을 끼운다(LLM으로 다시 쓰지 않는다).

| id | 축 | 켜는 조건 | 하위 질의에 끼우는 공고 값 | 기대 조 (§5 징후 2) |
| --- | --- | --- | --- | --- |
| `homeless` | 무주택 여부·기간 | 항상 | — | 제53조 |
| `account` | 청약통장(가입기간·예치금) | 항상 | — | 제9조 · 제10조 · 제27조 · 제28조 |
| `residence` | 거주지역·거주기간 | 항상 | 공급지역명(`subscrpt_area_nm`) | 제4조 · 제34조 |
| `income_asset` | 소득·자산(특별공급) | 공고 주택형의 특별공급 세대수 합 > 0 | — | 제35조 · 제41조 · 제43조 · 제46조 |
| `rewin` | 재당첨제한 | 투기과열지구·청약과열지역·분양가상한제·공공택지 표시 중 하나라도 참 | — | 제54조 | <!-- style-exempt -->
| `householder` | 세대주 여부 | 항상 | — | 제2조 · 제28조 |
| `special_type` | 특별공급 유형별 요건 | 공고 주택형의 특별공급 세대수 합 > 0 | 공급이 있는 유형 이름(다자녀·신혼부부·생애최초·노부모·기관추천·청년·신생아·이전기관) | 제35조 ~ 제47조 중 하나 |

- 기대 조는 main 세션이 법령 조 제목 88개를 보고 구현 전에 정했다. 결과를 보고 바꾸지 않는다
- 켜는 조건의 공고 칸
  - 재당첨제한: `notices.speclt_rdn_earth_at`(투기과열지구) · `mdat_trget_area_secd`(청약과열지역) · `parcprc_uls_at`(분양가상한제) · `public_house_earth_at`(공공택지) <!-- style-exempt -->
  - 특별공급: `notice_models.spsply_hshldco` 합. 유형별 세대수는 `notice_models.raw`의 `MNYCH_HSHLDCO`(다자녀) · `NWWDS_HSHLDCO`(신혼부부) · `LFE_FRST_HSHLDCO`(생애최초) · `OLD_PARNTS_SUPORT_HSHLDCO`(노부모) · `INSTT_RECOMEND_HSHLDCO`(기관추천) · `YGMN_HSHLDCO`(청년) · `NWBB_HSHLDCO`(신생아) · `TRANSR_INSTT_ENFSN_HSHLDCO`(이전기관)
- 착수 실측(2026-10-29, 실제 DB)
  - 공고 84건. 특별공급 세대수 합이 0인 공고 5건 → 그 5건은 특별공급 축 둘이 꺼진다
  - 규제 표시 넷이 전부 거짓인 공고 48건 → 그 48건은 재당첨제한 축이 꺼진다
- 켜는 조건은 마스터 설계 「공고 유형 따라 축 on/off」를 공고 데이터로 옮긴 것이다. 사용자 프로필은 보지 않는다(B1b·#82 몫)
- 축마다 「왜 켜졌나/꺼졌나」를 한 줄로 같이 돌려준다(`reason`). 예: `재당첨제한: 꺼짐 — 투기과열·청약과열·분양가상한제·공공택지 표시 모두 거짓` <!-- style-exempt -->

## 3. 축마다 검색 (B5)

```
공고 → MST(notice_law_versions) → 켜진 축마다:
  하위 질의 → 임베딩(캐시) → 조문: chunks WHERE source='law' AND law_mst=<MST>
                                 dense(nearest) + BM25 → RRF → 상위 5
                            FAQ:  chunks WHERE source='faq'
                                 dense + BM25 → RRF → 상위 3
```

- **pre-filter는 `law_mst`다.** 조문 행만 공고의 MST로 거른다. FAQ는 `law_mst`가 없어서 거르지 않는다
- **dense는 DB에서.** `nearest()`에 `law_mst` 조건을 더한다. 부분 인덱스 `source='law'` 위에 `law_mst` 조건이 붙으면 HNSW가 후보 `ef_search`개를 먼저 고르고 그 뒤에 거른다(필터 × ANN). 지금은 조문 88행이 전부 한 MST라 결과가 같다. 그래도 k개보다 적게 돌아온 축을 센다(징후 1)
- **BM25는 앱에서.** Postgres `ts_rank`는 IDF가 없어 BM25가 아니다(#74 설계 §3). 같은 조건으로 DB에서 행을 읽어 `search.BM25`로 점수를 낸다. (source, MST)마다 한 번만 만든다
- **RRF는 `search.rrf`(k=60) 그대로.** `query.Index.search`와 같은 방식(BM25 + dense → RRF)이라 같은 질문이면 같은 결과가 나와야 한다(징후 3)
- 임베딩은 `Embedder`(캐시). 공고 84건의 하위 질의는 축 7개 × 서로 다른 공급지역·특공 유형 수만큼이라 수십 개다

## 4. 결과와 CLI

- `axes.plan(engine, house_manage_no, pblanc_no)` → 축 7개(켜짐 여부, 이유, 하위 질의)
- `axes.search(engine, embedder, house_manage_no, pblanc_no, k=5, faq_k=3)` → 켜진 축마다 조문 상위 5 · FAQ 상위 3
- `python -m cheongyak_rag.retrieval.axes <공고번호>` — 한 공고의 축 목록과 축마다 top-k를 출력한다
- `--report` — 공고 84건 전부 돌려 `docs/79-axis-search.md`·`runs/79/last_run.json`을 쓴다(#74·#77과 같은 방식)
  - 리포트에는 켜진 축 목록이 서로 다른 공고를 하나씩 골라 축마다 top-k 전체를 싣는다. jw가 그걸 읽고 확인한다

## 5. jw 기준을 재는 법 (plan §실패 징후)

| 확인 | 무엇과 대조하나 |
| --- | --- |
| 7축 검색이 끝까지 동작한다 | 공고 84건 × 켜진 축마다 예외 0, 조문 5개·FAQ 3개가 다 돌아오는지 |
| 켜진 축 목록 | `axes.plan`의 켜짐 여부 ↔ 측정 코드가 SQL로 따로 다시 계산한 켜짐 여부 |
| 근거 청크 top-k | 축마다 기대 조(§2 표)가 조문 상위 5개 안에 있는지. 리포트 표본으로 jw가 직접 읽는다 |
| 메모리 검색과 같은가 | 같은 하위 질의로 DB 경로 상위 5 ↔ `query.Index.search` 상위 5 |

## 6. 이번에 안 하는 것

- **rerank(cross-encoder)** — `bge-reranker-v2-m3`는 torch와 모델 파일(2GB대)을 붙인다. 붙여서 나아졌는지 잴 eval이 #76 전이라 없다. #76 뒤에 따로 잰다
- **LLM으로 하위 질의를 다시 쓰기** — 고정 문장으로 먼저 돌려 보고, 기대 조가 안 잡히는 축이 있으면 그때 본다
- **축을 동시에 실행** — 로컬 DB에 질의 7개라 공고 하나에 몇 초 안쪽으로 본다. 공고당 시간을 재서 리포트에 적는다(징후 5)
- **사용자 프로필로 축 끄기**(B1b 결손 분석) — #82
- **축별 판정** — #80
- **`query.Index`·#139 답 생성을 이 경로로 바꾸기** — 지금 답 생성은 공고를 받지 않는다
- **다른 법령 조문** — #135. `law_mst`가 시행일 하드코딩에서 오는 문제(#74 defer #13)도 #135 몫이다
- **API 엔드포인트** — #84 프론트가 붙을 때

## 7. 위험

- 켜는 조건은 Claude가 조 제목과 공고 칸 이름으로 정했다. 루프는 제54조(재당첨 제한)·제28조(세대주) 본문을 읽고 조건과 어긋나면 고치되, 무엇을 바꿨는지 리포트 §열린 질문에 적는다
- 기대 조도 Claude가 정했다. 징후 2는 「이 질의가 그럴듯한 조를 찾는가」를 보는 확인이지 정답 대조가 아니다
- 하위 질의 문장이 축마다 결과를 거의 정한다. 문장은 리포트에 그대로 싣는다
