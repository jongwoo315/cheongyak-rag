568행을 적재했고, 벡터가 캐시와 다른 행은 0개, 설계한 인덱스는 3개가 있고, HNSW top-k가 전수 계산과 같은 문항은 조문 100.0%·FAQ 100.0%, 캐시에 없던 청크는 0개다.

# #74 검색 색인 적재 결과

실행 2026-10-28T00:15:51+09:00 · 청킹 후보 `article` · 임베딩 모델 `text-embedding-3-small`

## 1. 실패 징후 측정값

| 지표 | 측정값 | 구간 |
| --- | --- | --- |
| 1. 적재와 인덱스 (jw 기준) | 행 568/568 · 집합 차이 빠짐 0·남음 0 · `text` 다른 행 0 · 벡터 다른 행 0 · 인덱스 chunks_embedding_faq_hnsw, chunks_embedding_law_hnsw, chunks_pkey, chunks_tokens_gin · `enable_seqscan=off`에서 부분 인덱스를 탄 쪽: law 예, faq 예 | 통과 |
| 2. HNSW top-k = 전수 top-k인 문항 비율 | 조문 100.0% (123/123) · FAQ 100.0% (123/123) | 통과 |
| 3. k개보다 적게 돌아온 문항 수 | 0문항 (조문 0 · FAQ 0) | 통과 |
| 4. 캐시에 없던 청크 텍스트 | 0개 (골든 질문 캐시 미스 0개 · 임베딩 API 호출 0회는 판정에 안 쓴다) | 통과 |
| 5. 재실행 | 행 568→568 · 바뀐 chunk_id 0개 · 내용이 바뀐 행 0개 | 통과 |
| 6. 빈 `tokens` 행 | 0개 | 통과 |

구간 기준과 경계는 plan §실패 징후와 같다.

### 읽는 법

- 2·3번의 top-k는 `enable_seqscan=off`로 HNSW를 강제해서 쟀다. 기본 설정의 planner는 전수 스캔을 고를 수 있고 그 결과는 정확하므로, 기본 경로의 일치 비율은 따로 재지 않았다
- 1번 벡터 대조의 기준은 `Embedder` 캐시(실행 때 읽은 `embed-<모델>.jsonl`)다. float4 저장과 문자열 직렬화로 값이 달라졌는지만 본다. 청크 텍스트는 `query.Index`와 같은 함수로 만들었으므로 `text` 대조도 저장 과정에서 바뀌었는지만 본다
- 5번 재실행은 한 프로세스 안에서 같은 입력으로 두 번 적재해 `text`·벡터·`tokens`를 비교한다. 프로세스를 따로 두 번 돌린 비교는 PR 본문에 있다
- 참고(판정에 안 쓴다): kiwi 토큰과 tsvector 낱말이 다른 청크 14개. Postgres `simple` 파서가 `시·도`나 공백이 든 토큰을 둘로 쪼개서다. 끝의 점(`2.` → `2`)은 같은 낱말로 셌다

## 2. 어긋난 곳

- 없다

### HNSW top-k가 전수 계산과 다른 문항 (0건)

- 없다

## 3. EXPLAIN 원문

행이 적으면 planner가 인덱스 대신 전수 스캔을 고를 수 있다. 위 표의 top-k는 `enable_seqscan=off`에서 쟀다(`nearest(force_index=True)`).

### law · 기본 설정

```
Limit  (cost=294.78..294.79 rows=5 width=16)
  ->  Sort  (cost=294.78..295.00 rows=88 width=16)
        Sort Key: ((embedding <=> '[…]'::vector))
        ->  Seq Scan on chunks  (cost=0.00..293.32 rows=88 width=16)
              Filter: (source = 'law'::text)
```

### law · enable_seqscan=off

```
Limit  (cost=356.66..374.22 rows=5 width=16)
  ->  Index Scan using chunks_embedding_law_hnsw on chunks  (cost=356.66..665.76 rows=88 width=16)
        Order By: (embedding <=> '[…]'::vector)
```

### faq · 기본 설정

```
Limit  (cost=300.50..300.51 rows=3 width=16)
  ->  Sort  (cost=300.50..301.70 rows=480 width=16)
        Sort Key: ((embedding <=> '[…]'::vector))
        ->  Seq Scan on chunks  (cost=0.00..294.30 rows=480 width=16)
              Filter: (source = 'faq'::text)
```

### faq · enable_seqscan=off

```
Limit  (cost=1471.10..1480.52 rows=3 width=16)
  ->  Index Scan using chunks_embedding_faq_hnsw on chunks  (cost=1471.10..2977.60 rows=480 width=16)
        Order By: (embedding <=> '[…]'::vector)
```

## 4. 열린 질문에서 고른 값 (설계 §5)

- HNSW `m`·`ef_construction`: pgvector 기본값(16·64) 그대로. `ef_search`는 기본 40이고 올리지 않았다
- `law_mst`: 286965 — `law_versions`에서 시행일 2026-06-15 행의 MST
- pgvector 0.8.5(HNSW 동작 기준) · kiwipiepy 0.24.0(`tokens`를 다시 만들어야 하는지 볼 때 쓰는 버전)
- 임베딩 API 호출 0회
