# #85 리뷰 — PR #18

**대상:** `main...HEAD` — 16 commits, 40 files, +5259 −64 (이 리뷰 파일 제외)
**plan:** docs/plans/85-1109-plan-deploy-vercel.md

단어장: `docs/concepts.md` `## 용어` 절의 「쓰지 말 말」을 diff에서 찾았다. 코드·주석·docstring 두 곳이 걸려 고쳤다(#8·#9). 나머지는 plan·design 문서와 main 세션이 넣은 용어 행이라 기록만 했다(#10·#11).

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Important | `src/cheongyak_rag/deploy_load.py:73` | 원본 DB에 옮길 테이블이 없으면(빈 DB·잘못된 `DATABASE_URL`) 테이블 목록이 비어 행 수 대조가 0 = 0으로 「전부 같다」를 찍고 0으로 끝난다. `pg_dump`에도 `-t`가 안 붙어 `traces`까지 덤프한다 | fix `e7f0a66` |
| 2 | Important | `docs/85-deploy.md:48` | `CACHE_DIR`을 api에 안 넣으면 기본 위치 `data/cache`가 Vercel에서 쓸 수 없는 경로라 첫 판정이 500으로 끝난다. 표가 필수라고 안 적었고 바로 아래 `OPENAI_*` 행이 「안 넣어도 된다」라 빼도 되는 값으로 읽힌다 | fix `48db629` |
| 3 | Important | `docs/85-deploy.md:122` | 「18쌍을 두 번 측정하면 한도 50을 넘는다」는 틀렸다. 두 번은 36건이라 한도 안이고 세 번째(54건)부터 넘는다 | fix `2893e72` |
| 4 | Important | `docs/85-deploy.md:148` | 캐시 없는 측정의 원본으로 가리킨 `runs/85/cold/last_run.json`은 로컬 모드(G2 2, 구간 미완)로 계산돼 있어 문서의 G2' 0·판정값 1/3을 그 파일에서 찾을 수 없다 | fix `f022422` |
| 5 | Important | `.env.example:21` | 「비우면 `<repo>/data/cache`」는 틀렸다. `CACHE_DIR=`처럼 빈 값을 주면 현재 디렉터리(`.`)가 된다 | fix `f2a1f15` |
| 6 | Important | `src/cheongyak_rag/api.py:174` | 하루 한도를 `run_traced` 앞에서 올려서, OpenAI 장애(503)·DB 오류·체크리스트 전부 실패(503) 같이 판정을 못 받고 끝난 질의도 한도를 쓴다. 장애 동안 50번 누르면 복구 뒤에도 그날 429가 난다. 잠금 대기 초과(503)만 되돌린다 | push-back — plan 통과 기준 3이 올리는 자리를 「404·422 뒤, `run_traced` 앞」으로 정했고 `docs/85-deploy.md:36`이 「판정 중 오류는 센다」를 의도된 정책으로 적었다. 한도의 목적이 LLM 비용 상한인데 오류 종류마다 LLM을 이미 불렀는지 가려 되돌리면 호출이 나간 질의를 돌려주게 된다. 장애 때 한도가 소진되는 비용은 받아들이고, 배포 측정에서 실제로 문제가 되면 후속 티켓에서 다시 본다 | <!-- style-exempt -->
| 7 | Important | `web/app/api/verdict/[houseManageNo]/route.ts:24` | 504(`TimeoutError`)·502 분기와 `VerdictForm.tsx`의 「200인데 JSON이 아닌 본문」 처리를 실행해 보는 테스트가 없다. `npm run build`는 이 로직을 돌리지 않는다. `tests/test_vercel_config.py`는 `maxDuration` 문자열만 본다 | defer — plan 통과 기준 5·6이 웹은 `npm run build`만 요구하고 새 npm 패키지를 금지했다. Playwright `page.route`로 200+HTML·504·429를 모킹하는 spec은 이 PR 범위 밖이다. 배포 측정(#85 PR 뒤)이 실제 사이트에서 같은 분기를 지나간다 |
| 8 | Suggestion | `src/cheongyak_rag/api.py:175` | 주석의 「뒤 요청이」가 단어장 「질의」의 쓰지 말 말(요청)이다 | fix `d3f2b27` |
| 9 | Suggestion | `alembic/versions/0006_verdict_daily_count.py:1` | docstring의 「판정 요청 수」가 같은 쓰지 말 말이다 | fix `e02a674` |
| 10 | Suggestion | `docs/concepts.md:115` | 「하루 판정 한도」 용어 행의 뜻이 「판정 요청 수」로 쓰지 말 말(요청)을 쓴다. 「질의 수」가 단어장에 맞다 | 기록만 — main 세션이 넣은 행이라 plan이 루프가 용어 행을 고치지 않게 했다 |
| 11 | Suggestion | `docs/plans/85-1109-design-deploy-vercel.md:44` | design·plan 문서에 「요청」(질의 뜻)·「요청 제한」(하루 판정 한도 뜻)이 여러 곳 있다(design 44·45·50·90행, plan 97·105행) | 기록만 — 착수 전에 쓴 plan·design 문서라 건드리지 않는다 |
| 12 | Suggestion | `src/cheongyak_rag/api.py:64` | `_take_one_of_todays_limit`와 `_give_back_one`이 각자 `today_kst()`를 불러서, 잠금을 기다리다 한국 자정을 넘으면 다음 날 행에서 뺀다(전날 수가 1 많게 남는다). 429로 올라간 수도 되돌리지 않아 한도 초과 뒤의 수는 「받은 판정 수」가 아니라 「시도 수」다 | 기록만 — 하루 1건 어긋나는 정도다 | <!-- style-exempt -->
| 13 | Suggestion | `src/cheongyak_rag/api.py:140` | `get_verdict_deps`의 `with _LOCK:`는 timeout이 없다. 인스턴스가 막 떠서 캐시가 빌 때 질의 둘이 오면 두 번째 질의가 첫 질의의 판정이 끝날 때까지 기다리고(최대 300초) 그 뒤 `VerdictDeps`를 하나 더 만든다 | 기록만 | <!-- style-exempt -->
| 14 | Suggestion | `src/cheongyak_rag/deploy_load.py:177` | 엉뚱한 대상 URL이면 「행이 있으면 거부」보다 `alembic upgrade head`가 먼저 돌아 그 DB에 테이블이 만들어진다 | 기록만 — plan 순서(① upgrade)를 따랐다 |
| 15 | Suggestion | `web/e2e/measure.spec.ts:127` | 테스트 전체 timeout이 30분이라 `MEASURE_WAIT_MS=240000`에서 결과가 안 뜬 쌍이 4개를 넘으면 `raw.json`(마지막에 한 번 씀)이 남지 않는다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/deploy_load.py:126` | `pg_dump`의 stderr를 `load.communicate()` 뒤에 읽어 stderr가 64KB를 넘으면 교착한다. 적재 뒤 `count_rows`에서 DB 오류가 나면 traceback만 나오고 「데이터는 이미 들어갔다」 안내가 없다. `docker`가 없으면 `FileNotFoundError` traceback이다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/web_report.py:134` | `/health`가 JSON이지만 dict가 아니면 `health_ok`의 `body.get`이 `AttributeError`로 죽는다. 배포 모드 G2'(`_same_shape`)는 일부 항목이 `error`여도 항목 수가 같으면 통과한다 | 기록만 | <!-- style-exempt -->
| 18 | Suggestion | `web/app/api/verdict/[houseManageNo]/route.ts:8` | `VERDICT_TIMEOUT_MS`가 음수·너무 큰 수면 `AbortSignal.timeout`이 `RangeError`를 던져 모두 502로 나온다. `0`은 문서와 달리 기본값으로 간다 | 기록만 |
| 19 | Suggestion | `web/components/VerdictForm.tsx:57` | `typeof a.general !== "object"`는 `null`을 통과시킨다. `{"general": null, ...}` 200이면 `Result`가 렌더 중에 터진다 | 기록만 — FastAPI 응답 모양상 `general`이 null인 경로는 없다(추정) |
| 20 | Suggestion | `web/components/VerdictForm.tsx:19` | 504 문구가 「잠시 뒤 다시 시도」라고만 해서, FastAPI는 계속 돌고 한도는 이미 쓴 상태에서 재시도하면 한도가 또 든다는 것을 알리지 않는다 | 기록만 |
| 21 | Suggestion | `src/cheongyak_rag/api.py:203` | 브라우저로 나가는 503 `detail`에 `DB 오류: ProgrammingError`처럼 예외 클래스 이름이 들어간다. 같은 파일의 다른 503은 내부 원인을 숨긴다 | 기록만 |
| 22 | Suggestion | `src/cheongyak_rag/deploy_load.py:9` | docstring에서 못 덤프하는 쪽은 `psql`이 아니라 `pg_dump`다. `config.py:32`·`docs/85-deploy.md:158`의 60초 근거(빈 캐시 판정 최대 19.5초)는 로컬 DB에서 잰 값이라 Neon 왕복 지연이 빠진 하한이다 | 기록만 | <!-- style-exempt -->
| 23 | Suggestion | `tests/test_api_verdict.py:185` | 한도 카운터의 원자성(동시 질의), 자정 경계 give-back, 503 뒤 한도 소비, `fetch_health`·`main --deploy`, `copy_data`의 `pg_dump 실패` 분기, 설치 없이 `import app`, 문서의 측정 명령이 실제 CLI 플래그와 맞는지를 확인하는 테스트가 없다 | 기록만 |
| 24 | Suggestion | `src/cheongyak_rag/web_report.py:1` | 모듈 docstring 사용법에 `--only-notice`가 없다. `web/e2e/measure.spec.ts:2`의 주석이 `runs/84`를 고정 경로처럼 쓴다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. `cache_dir`(`CACHE_DIR`) — 기본 `<repo>/data/cache`, 캐시 셋이 모두 따른다 | 예 | `config.py:29`, `embed.py:25`·`answer.py:131`·`verdict.py:199` · `tests/test_config_deploy.py` |
| 2. `DATABASE_URL`의 `postgres://`·`postgresql://`를 `postgresql+psycopg://`로, 쿼리 문자열 유지 | 예 | `config.py:38-45` · `tests/test_config_deploy.py` |
| 3. 하루 판정 한도 — 테이블·설정·404/422 뒤 `run_traced` 앞에서 올림·429·Asia/Seoul | 예 | `0006_verdict_daily_count.py` · `api.py:51-76,174` · `tests/test_api_verdict.py`(한도 2에서 3번째 429·`run_traced` 2번만) · `tests/test_daily_count_migration.py` |
| 4. `_LOCK.acquire(timeout=...)`·`verdict_lock_timeout_s`·503, 기본값은 Task 1 측정 근거(240초 이하) | 예 | `api.py:176-178` · `config.py:34`(60초) · `docs/85-deploy.md` 징후 2(최대 19.5초) |
| 5. `route.ts` — `AbortSignal.timeout`·`VERDICT_TIMEOUT_MS`·504/502·`console.error` | 예(코드). 동작을 실행하는 테스트는 없음(#7) | `route.ts:8,24,33-44` · `web/.env.example` · `npm run build` 통과(PR 본문 주장, 이 세션에서 다시 안 돌림) |
| 6. `VerdictForm.tsx` — 200이어도 본문이 JSON이 아니면 오류 문구 | 예(코드). 실행 테스트 없음(#7) | `VerdictForm.tsx:49-61` |
| 7. Vercel 설정 — `app.py`·`vercel.json`·`web/vercel.json`·`.python-version`·`.vercelignore`·`web/.vercelignore`·`import app` | 예 | 파일 존재 · `tests/test_vercel_config.py` |
| 8. Neon 적재 스크립트 — 원본 거부·4단계·테이블 목록 동적·대상 행 있으면 거부·URL 안 찍음·임시 DB 테스트 | 예(#1 수정 후) | `deploy_load.py` · `tests/test_deploy_load.py` 12개 통과 |
| 9. 배포 측정 모드 — `measure.spec.ts` 환경 변수·`web_report` `--run-dir`·`--deploy`·`--api-url`·`--report`·문서에 명령 | 예 | `web_report.py` · `tests/test_web_report.py` · `docs/85-deploy.md` §배포 사이트 측정 |
| 10. `docs/85-deploy.md`(절차·환경 변수 표·리허설 결과)·README `### 배포` | 예 | `docs/85-deploy.md` · `README.md` (#2~#4 수정 후) |
| 11. `.env.example`에 `CACHE_DIR`·`VERDICT_DAILY_LIMIT`·`VERDICT_LOCK_TIMEOUT_S` | 예(#5 수정 후) | `.env.example:20-26` |
| 12. `uv run pytest -q`·`ruff check`·`ruff format --check`·`cd web && npm run build` | 아래 마지막 줄 참고 | 리뷰 시작 때 pytest 1114 passed·ruff 통과. fix 뒤 결과는 맨 아래 |
| 실패 징후 1 — 리허설 A ok·F 0·L 84·G1 0·G2' 0·판정값 18 | 판정 불가(이 세션이 다시 안 잼) | `docs/85-deploy.md` 징후 1 표 · `runs/85/rehearsal/last_run.json` (PR 본문 주장) |
| 실패 징후 2 — 빈 캐시 3쌍, 가장 긴 쌍 200초 이하 | 값만: 19.5초 / 17.5초 / 16.5초 | `runs/85/cold/raw.json` · 문서 수치는 `raw.json`과 맞는 것을 확인(주석 검토) |
| 실패 징후 3 — 한도 2에서 3번째 429, 404·422는 안 센다 | 예 | `tests/test_api_verdict.py` |

**검증 (fix 뒤):** `uv run pytest -q` 1115 passed (fix #1의 테스트 1개 추가) · `uv run ruff check` 통과 · `uv run ruff format --check` 188개 통과. `cd web && npm run build`는 웹 코드를 안 바꿨고 이 세션에서 다시 안 돌렸다.
