# #74 설계 — 검색 색인을 Postgres에 적재한다

**Tier:** C · **Notion:** #74 · 브랜치 `feat/74-pg-index`

## jw 기준

「기존에 메모리에서 계산하던 임베딩 결과를 postgresql 테이블에 적재하고 인덱스도 추가된다」

## 1. 지금 상태

RAG 파이프라인 지도의 Lane A로 보면 A3·A4까지는 있고 A5·A6이 없다.

| 단계 | 지금 | 위치 |
| --- | --- | --- |
| A3 청킹 | `article` 후보(#73). 조문 청크 88개 + FAQ 청크 480개 = 568개 | `retrieval/chunk.py` `law_chunks`·`faq_chunks`, `runs/73/selected.json` |
| A4 임베딩 | `text-embedding-3-small`(1536차원). 텍스트 sha256 → 벡터를 파일에 캐시한다 | `retrieval/embed.py`, `data/cache/embed-text-embedding-3-small.jsonl`(3056줄) |
| A5 저장 | 없다 | alembic은 0001 pgvector 확장 · 0002 notices · 0003 law_versions뿐이다 |
| A6 인덱싱 | 없다. `query.Index`가 실행할 때마다 568개 벡터를 메모리에 올리고 numpy 코사인으로 전부 비교한다. BM25도 파이썬으로 계산한다 | `retrieval/query.py:24`, `retrieval/search.py` |

`query.Index`는 #139 답 생성이 쓴다. 이 티켓은 그 검색 경로를 바꾸지 않는다(§6).

## 2. 무엇을 만드나

1. alembic 0004 — 테이블 `chunks`와 인덱스
2. 적재 CLI — `python -m cheongyak_rag.retrieval.index_db`
   - `query.Index`와 **같은 함수**(`law_chunks(rows, 선택된 후보)`·`faq_chunks`)로 청크를 만든다. 그래야 DB 행과 메모리 계산이 같은 텍스트를 쓴다
   - 벡터는 `Embedder`로 가져온다. 캐시에 있으면 API를 부르지 않는다. 부른 횟수를 리포트에 적는다
   - 한 트랜잭션 안에서 테이블을 비우고 568행을 다시 넣는다. 다시 돌려도 결과가 같다
3. `--report` — 적재 결과와 측정값을 `docs/74-pg-index.md`·`runs/74/last_run.json`에 쓴다(#71·#77과 같은 방식)

## 3. 테이블

| 칸 | 타입 | 내용 |
| --- | --- | --- |
| `chunk_id` | text PK | `law:제2조` · `faq:47` — `Chunk.chunk_id` 그대로 |
| `source` | text, `law`·`faq`만 허용(CHECK) | 조문인지 FAQ인지 |
| `label` · `path` · `title` | text | `Chunk`의 같은 이름 칸. FAQ는 `title`이 비어 있다 |
| `text` | text | 임베딩에 넣은 텍스트 그대로 |
| `text_sha256` | text | 캐시 키와 같은 값. 캐시와 대조할 때 쓴다 |
| `law_mst` | text, null 허용 | 조문 청크의 법령 버전(`law_versions.mst`). FAQ는 null. #79가 공고별 버전으로 거를 때 쓴다 |
| `embed_model` | text | `text-embedding-3-small`. 모델을 바꾸면 벡터 전부를 다시 만들어야 한다는 것을 행에 남긴다 |
| `embedding` | `vector(1536)` | |
| `tokens` | `tsvector` | `search.tokenize`(kiwi 형태소, `KEEP_TAGS`)로 나눈 토큰을 `to_tsvector('simple', …)`에 넣은 것 |

### 인덱스

- **벡터 — HNSW, `vector_cosine_ops`, `source`별 부분 인덱스 둘**
  (`… WHERE source = 'law'`, `… WHERE source = 'faq'`)
  - 지금 검색은 조문과 FAQ를 **따로** 순위 매긴다(`query.Index.search`). DB에서도 `WHERE source='law'`를 걸게 된다
  - 인덱스 하나에 필터를 걸면 HNSW가 후보 `ef_search`개(기본 40)를 먼저 고르고 그 뒤에 필터를 건다. 568행 중 조문은 88행뿐이라 k개보다 적게 돌아올 수 있다(지도 B4 「필터 × ANN」)
  - 부분 인덱스는 처음부터 그 source 행만 담는다. 안 고른 방법: pgvector 0.8 `hnsw.iterative_scan` — 세션 설정에 결과가 좌우되고 이미지의 pgvector 버전에 기대야 한다
- **`tokens` — GIN**

### `tsvector`는 저장만 하고 점수는 이 티켓에서 안 쓴다

Postgres `ts_rank`는 문서 안의 단어 빈도만 보고 IDF를 계산하지 않아 BM25가 아니다. BM25 점수를 DB에서 낼지(확장), 앱에서 낼지는 #79가 정한다. 이 티켓은 형태소 토큰을 저장하고 GIN을 붙여서 「이 단어가 들어간 청크」를 DB에서 거를 수 있게만 한다.

## 4. jw 기준을 재는 법

| 확인 | 무엇과 대조하나 |
| --- | --- |
| 적재 | 메모리 계산이 쓰는 568개 청크 ↔ DB 행. 행 수, `chunk_id` 집합, `text`가 같은지 |
| 벡터 | 각 행의 `embedding` ↔ 캐시 파일의 같은 sha256 벡터. 원소별 차이가 1e-6 이내인지 |
| 인덱스 | `pg_indexes`에 HNSW 2개·GIN 1개가 있는지, `EXPLAIN`에서 그 인덱스를 타는지 |
| 인덱스로 찾은 결과 | golden 123문항(`runs/golden.jsonl`)마다 HNSW top-k ↔ 메모리 전수 계산(`dense_rank`) top-k. 조문 k=5, FAQ k=3 |

- `EXPLAIN`: 568행이면 planner가 인덱스 대신 전수 스캔을 고를 수 있다. 그때는 `SET enable_seqscan = off`로 인덱스를 쓰게 해서 잰다. 고르는 쪽은 리포트에 그대로 적는다
- HNSW는 근사라서 top-k가 전수 계산과 다를 수 있다. 다르면 문항과 빠진 청크를 리포트에 적는다

## 5. 열린 질문 — 루프가 정하고 리포트에 적는다

1. HNSW `m`·`ef_construction`은 pgvector 기본값(16·64)으로 둔다. top-k 일치가 기준에 못 미치면 `ef_search`만 올려서 다시 잰다
2. `law_mst` 값은 `law-008243-20260615.jsonl`이 어느 MST인지에서 온다. `law_versions`에서 시행일 2026-06-15 행의 MST를 쓴다. 착수 때 실제 DB에 `286965 | 2026-06-15` 행이 있었다. 그 행이 없는 DB(테스트 DB 등)에서는 null로 넣고 리포트에 적는다
3. kiwipiepy 버전은 `tokens`를 다시 만들어야 하는지 판단하는 근거라 리포트에 적는다

## 6. 이번에 안 하는 것

- **`query.Index`·#139 답 생성의 검색을 DB로 바꾸는 것** — #79(pre-filter → hybrid → RRF)의 일이다
- **DB에서 BM25 점수 계산** — §3. #79
- **L3 공고문 청크** — #72(공고문 수집)가 시작 전이다
- **다른 법령 조문** — #135가 시작 전이다
- **다른 청킹 후보 적재** — `runs/73/selected.json`이 고른 후보 하나만 넣는다
- **법령 여러 버전의 조문** — 지금 공고 84건이 전부 MST 286965 하나를 쓴다(#78)

## 7. 위험

- **적재는 실제 DB(`cheongyak`, 5433)에 한다.** alembic 0004가 그 DB에 적용된다. PR이 머지되지 않으면 DB에 0004가 남는다 — #71·#78도 같은 방식이었다. 테스트는 `conftest.pg_test_url`이 만드는 `cheongyak_test_<pid>` DB를 쓴다
- **임베딩 API 호출.** 568개 텍스트와 golden 질문은 캐시에 있을 것으로 본다. 캐시에 없는 것만 부르고 그 횟수를 리포트 첫 줄에 적는다
