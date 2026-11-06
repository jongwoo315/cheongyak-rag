# #84 리뷰 — PR #17

**대상:** `main...HEAD` — 21 commits(이 리뷰의 fix 11개 포함), 37 files, +5630 −0
**plan:** docs/plans/84-1105-plan-web.md

단어장(`docs/concepts.md` `## 용어`) 검사: 「쓰지 말 말」이 diff에 나온 곳 없음. `요청`은 HTTP 요청·요청 제한 뜻으로만 쓰였고 `질의`를 가리키지 않는다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/web_report.py:119` | `judge`가 페이지 84개·쌍 18개가 다 들어왔는지 보지 않아, 측정이 중간에 끊겨도 F 0이면 `통과`로 나온다 | fix `7d3fb08` |
| 2 | Important | `src/cheongyak_rag/api.py:172` | 체크리스트 항목의 `error`(예외 문구: 요청 id·조직 정보 가능)가 200 본문으로 브라우저에 나간다 | fix `15cba4a` |
| 3 | Important | `src/cheongyak_rag/api.py:167` | 하위 질의가 전부 실패해도 200에 `verdict` null이라 화면이 「판정을 낼 근거가 없다」로 읽힌다(장애가 근거 없음으로 보임) | fix `00bfcb0` |
| 4 | Important | `src/cheongyak_rag/api.py:139` | 모순된 프로필(미래 날짜 등)은 422지만 `run_traced` 안에서 걸려 `status='error'` trace 행이 남는다 | fix `567667e` |
| 5 | Important | `src/cheongyak_rag/api.py:159` | `SQLAlchemyError` 분기에 로그가 없어 스키마·코드 결함이 503 뒤에 묻힌다 | fix `2a46d24` |
| 6 | Important | `web/lib/api.ts:20` | 목록 API가 404면 「공고 0건」으로 그려져 `API_BASE_URL` 오설정이 데이터 없음으로 보인다 | fix `a5fba48` |
| 7 | Important | `web/components/VerdictForm.tsx:63` | 「서버에 저장되지 않습니다」 안내가 사실과 다르다 — trace 행에 프로필 해시와 판정 결과가 남는다 | fix `b41b104` |
| 8 | Important | `web/components/VerdictForm.tsx:104` | 「1분 가까이」는 어디서도 측정하지 않은 값이다(18쌍은 전부 캐시 적중, 최대 2.9초) | fix `2cc0014` |
| 9 | Important | `src/cheongyak_rag/web_report.py:256` | 징후 2 범례가 plan의 미완 조건(다시 잰 뒤에도 G1 1 이상)을 빼서 `judge`가 내는 구간을 다 설명하지 못한다 | fix `598ae7c` `57ba4b0` |
| 10 | Important | `src/cheongyak_rag/api.py:139` | `load_facts`가 `notice_law_versions`와 inner join이라, 법령 버전이 안 이어진 공고는 존재해도 「공고 없음」 404로 나온다 | defer — 고칠 곳은 `retrieval/axes.py`(판정 흐름 코드)라 plan 범위 밖이다. 측정한 공고 6건은 전부 판정이 나왔다(쌍 18개). 84건 전부에 법령 버전이 이어져 있는지는 이 세션에서 확인하지 않았다 |
| 11 | Important | `web/components/VerdictForm.tsx:53` | 200인데 본문이 JSON이 아니거나 모양이 틀리면 빈 객체를 `Answer`로 취급해 `Result`가 렌더 중 예외를 낸다 | defer — #85. 응답 본문은 FastAPI가 만든 것을 라우트 핸들러가 그대로 넘기므로 이 경로는 중간 프록시가 붙는 배포 때 생긴다. 로컬에서는 나오지 않는다. 쓰거나 지우는 데이터는 없다 |
| 12 | Important | `web/app/api/verdict/[houseManageNo]/route.ts:13` | FastAPI 호출에 시간 제한이 없고 `catch`가 원인을 로그에 안 남겨, 시간 초과도 「연결하지 못했다」(502)로 나오고 사용자가 다시 눌러 판정이 겹친다 | defer — #85(요청 제한·비용 상한과 같은 자리). 겹친 판정은 `traces` 행과 LLM 호출을 더 쓴다(데이터를 쓴다) — plan이 로컬 한정으로 정한 범위다 <!-- style-exempt --> |
| 13 | Important | `src/cheongyak_rag/api.py:141` | `_LOCK`에 대기 시간 제한이 없어, 브라우저가 떠난 뒤에도 대기한 판정이 줄줄이 돌고 스레드풀이 차면 목록 API도 멈춘다 | defer — #85. 코드의 `ponytail:` 주석이 이 한계를 이미 적었다. 대기한 판정은 `traces` 행과 LLM 호출을 쓴다(데이터를 쓴다) |
| 14 | Important | `src/cheongyak_rag/web_report.py:26` | H를 세는 캐시 파일 이름이 `gpt-5.4-mini`·`text-embedding-3-small`로 고정돼, 서버가 다른 모델로 뜨면 H가 0인 채 `통과`가 나온다 | push-back — plan 징후 3이 이 두 파일을 이름으로 못박았고, 두 이름은 `config.py` 기본값(`gpt-5.4-mini`·`text-embedding-3-small`)과 같다. `.env`로 모델을 바꿨는지는 확인하지 않았다. 설정이 바뀌면 plan을 고쳐야 하는 일이라 이 티켓에서 측정 코드만 바꾸지 않는다 |
| 15 | Suggestion | `web/e2e/measure.spec.ts:75` | 화면에 오류(422·503)가 뜬 쌍이 `shown: false`로 적혀 리포트에는 「120초 안에 안 뜸」으로 읽히고 오류 문구는 `raw.json`에만 남는다 | 기록만 |
| 16 | Suggestion | `runs/84/last_run.json` | 리포트·`last_run.json`은 `5a67783`에서 만든 것이라 이후 fix 커밋 코드로 다시 안 만들었다. fix는 18쌍의 판정·경로·체크리스트 값을 바꾸지 않는다(항목 오류가 있는 쌍이 없었다). 공유 DB의 `traces`를 다시 세면 다른 세션의 행이 섞일 수 있어 다시 돌리지 않았다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/api.py:104` | `get_verdict_deps`가 입력 검증보다 먼저 돌아 키·모델 문제가 있으면 422·404 요청도 503이 되고, 동시에 처음 들어온 두 요청이 `GenCache`를 둘 만든다 | 기록만 |
| 18 | Suggestion | `web/components/VerdictForm.tsx:32` | 판정 뒤 입력을 고쳐도 이전 결과가 그대로 남아 새 값의 결과로 읽힌다 | 기록만 |
| 19 | Suggestion | `web/lib/profile.ts:32` | 저장된 값이 문자열이 아니거나 개수가 숫자가 아니면 `toPayload`가 `NaN`→`null`로 조용히 빼거나 `.trim()`에서 던진다(입력 칸이 막아 정상 경로에서는 안 나온다) | 기록만 |
| 20 | Suggestion | `src/cheongyak_rag/api.py:70` | 목록은 `(house_manage_no, pblanc_no)`마다 한 행인데 상세는 첫 `pblanc_no`만 돌려줘, 한 관리번호에 공고번호가 둘이면 링크가 겹친다(현재 84건은 전부 1:1) | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/api.py:30` | 주석·docstring 정확도: 「처음 요청 때 한 번」(실제는 성공했을 때만 재사용), 키 확인 이유가 CLI 설명을 옮긴 것, `trace_error`가 고정 문구라는 점 | 기록만 |
| 22 | Suggestion | `tests/test_api_verdict.py` | 테스트 빈칸: `_LOCK` 직렬화, `get_verdict_deps` 성공·캐시 경로, 라우트 핸들러 502·상태 코드 통과, `Result` 오류 상태 렌더, 375px에서 결과가 뜬 뒤 폭, 15칸 이름이 `Profile`과 같은지, `toPayload` 단위. `web/`에 단위 테스트 실행기가 없다 | 기록만 (오류 본문 고정 문구 두 건은 `5ed7dbd`에서 더했다) |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 통과 기준 1: HTTP API 3개 | 예 | `src/cheongyak_rag/api.py` 라우트 3개 · `tests/test_api_notices.py` · `tests/test_api_verdict.py` |
| 통과 기준 2: 422·404·503·200+`trace_error`, 판정은 `def` | 예 | `tests/test_api_verdict.py` 14 passed (422 알 수 없는 칸·날짜·모순, 404 trace 행 0, 503 키 없음, 503 하드 오류·DB 오류, 200+`trace_error`) |
| 통과 기준 3: `web/` Next.js, 버전 고정, lock 커밋 | 예 | `web/package.json`(정확한 버전) · `web/package-lock.json` · `.gitignore` |
| 통과 기준 4: `API_BASE_URL`, 브라우저는 라우트 핸들러만 | 예 | `web/lib/api.ts:5` · `web/.env.example` · `web/app/api/verdict/[houseManageNo]/route.ts` |
| 통과 기준 5: `/`·SSR 공고 페이지·404 | 예(기계 확인은 징후 1) | `docs/84-web.md` F 0 · L 84. 404 페이지는 `web/app/not-found.tsx`, 이 세션에서 HTTP로는 확인하지 않음 |
| 통과 기준 6: 입력 칸 15개, `sessionStorage` | 예 | `web/lib/profile.ts` FIELDS 15개 · `web/e2e/screen.spec.ts` |
| 통과 기준 7: 결과 화면과 `data-testid` | 예 | `web/components/Result.tsx` · 징후 2 G2 0 |
| 통과 기준 8: 375px 가로 스크롤 없음 | 예(공고 페이지 1개, 결과 없는 상태) | `web/e2e/screen.spec.ts` |
| 통과 기준 9: pytest·ruff·`npm run build` | 예 | 이 세션: `1064 passed`(마지막 fix 직후 전체), `ruff check` 통과, `ruff format --check` 174 files already formatted, `npm run build` 컴파일 성공 |
| 통과 기준 10: README | 예 | `README.md` `### 화면 띄우기` |
| 징후 1: F 0 · L 84 | 판정 불가(측정 당시 코드 기준 값만 적음) | `docs/84-web.md` F 0/84 · L 84 → 통과 구간 조건과 같은 값 |
| 징후 2: G1 0 · G2 0 | 판정 불가(같은 이유) | `docs/84-web.md` G1 0 · G2 0, 중앙값 1.8초 · 최대 2.9초(전부 캐시 적중) |
| 징후 3: H 0 · T = 18 | 판정 불가(같은 이유) | `docs/84-web.md` H 0 · T 18 |

위 세 징후의 값은 `5a67783` 시점 코드로 쟀다. 이후 fix는 판정 흐름 코드(`verdict`·`aggregate`·`trace`)를 바꾸지 않았고 18쌍의 응답 값도 바꾸지 않지만, 리포트를 최종 코드로 다시 만들지는 않았다(지적 16).
