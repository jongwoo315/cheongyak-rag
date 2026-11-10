# 72 리뷰 — PR #19

**대상:** `main...HEAD` — 12 commits(구현 7 + 리뷰 fix 5), 17 files, +2066 −0
**plan:** docs/plans/72-1109-plan-notice-doc.md

리뷰 대상 코드는 구현 마지막 커밋 `cc58719`다. 아래 위치 칸의 줄 번호는 fix 뒤 HEAD 기준이다.
리뷰는 `pr-review-toolkit`의 code-reviewer · pr-test-analyzer · silent-failure-hunter · comment-analyzer 네 에이전트로 했다.

## 지적

| # | 심각도 | 위치 | 내용 | 처리 |
| --- | --- | --- | --- | --- |
| 1 | Critical | `src/cheongyak_rag/ingest/notice_doc.py:350` | 지난 목록 `manifest.jsonl`에 깨진 줄이 하나만 있어도 `_read_manifest`가 빈 목록을 돌려줘, 이어지는 쓰기가 지난 줄 전부를 경고 없이 지운다(예: 84줄 + 잘린 마지막 줄에서 `--limit 5` 실행 → 5개 공고 줄만 남음) | fix `7a23f10` |
| 2 | Important | `src/cheongyak_rag/ingest/notice_doc.py:334` | 공고의 링크 두 개 중 뒤쪽 링크를 저장하다 예외가 나면 첫 링크는 파일로 저장됐는데 목록에서 사라지고, 실패 줄은 링크 URL 없는 오류 한 줄로 뭉개진다(디스크 가득 참 재현) | fix `32f9062` |
| 3 | Important | `src/cheongyak_rag/ingest/notice_doc.py:281` | HTTP 200인데 본문이 0바이트인 첨부가 `other`(격리)로 세어져 오류 수 0 → 「0 → 통과」로 읽힌다 | fix `3445766` |
| 4 | Important | `docs/concepts.md:117` | 「셋 중 하나라도 아니면 `error`」라고 적었는데 코드는 앞 바이트가 `%PDF-`가 아니면 `hwp`·`other`로 격리한다 | fix `42f0062` |
| 5 | Important | `tests/test_notice_doc_fetch.py:178` | 크기 제한 테스트가 상세 페이지 쪽에서 먼저 막혀(한도를 100으로 패치해 페이지도 넘음) 받는 도중 끊는 분기(`len(buf) > MAX_BYTES`)를 한 번도 타지 않았다. 그 분기를 지워도 테스트가 통과했다 | fix `91585d0` |
| 6 | Important | `tests/test_notice_doc_fetch.py:322` | 120초 제한 테스트가 `time.monotonic` 전체를 패치해 30초짜리 페이지 제한에서 먼저 걸렸다(첨부 요청 0건). 첨부 쪽 제한을 지워도 통과했다 | fix `91585d0` |
| 7 | Important | `tests/test_notice_doc_fetch.py:145` | PDF가 안 열린 오류 줄이 `new_downloads`에 1로 세어지는 동작(받았으나 저장 안 함)을 고정하는 assert가 없다 | fix `91585d0` |
| 8 | Important | `src/cheongyak_rag/ingest/notice_doc.py:154` | 전체 시간 제한(`ReadTimeout`)도 429·5xx·연결 오류와 같이 재시도돼, 느린 첨부 하나가 120초 × 5회 ≈ 10분을 쓴다. 통과 기준 7은 재시도 대상을 「429·5xx·연결 오류」로 적었다 | push-back — 시간 초과는 `httpx.TransportError`로 연결 오류에 든다고 읽었다. 실제 실행 74건에서 시간 초과는 0건이라 비용이 실제로 난 적이 없다. 바꿀지는 jw가 정한다(바꾸면 `test_total_time_limit_counts_as_timeout_and_retries`가 고정한 동작도 같이 바뀐다) |
| 9 | Important | `src/cheongyak_rag/ingest/notice_doc.py:321` | 실패 징후 2는 LH 10건 밖에서 `no_link`가 나오면 그 공고 HTML의 `pop_btn_txt` 부분을 리포트에 붙이라고 했는데, 그 부분을 저장·출력하는 코드가 없다. 지금은 `note`에 다른 외부 링크만 남는다 | defer — 이번 실행은 LH 10건 밖 `no_link`가 0건이라 붙일 HTML이 없었다. 나오는 날 해당 공고만 다시 받아 `runs/72/notes.md`에 붙이면 리포트 5절에 실린다. 자동화는 그 날 필요할 때 더한다 |
| 10 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:454` | 재실행에서 상세 페이지 받기가 실패하면 지난 `no_link` 줄(`url` 없음)이 `error` 줄 옆에 남는다. 결과 표 숫자는 맞지만 「링크 없음 공고」 목록과 오류 목록에 같은 공고가 같이 나온다 | 기록만 |
| 11 | Suggestion | `src/cheongyak_rag/ingest/notice_doc_report.py:280` | `--limit N`으로 수집한 뒤에는 목록 84줄과 요약 N건이 안 맞아 리포트가 늘 exit 1로 멈춘다. 실패 징후 1의 「그 공고만 한 번 더 받는다」를 `--limit`으로 하면 걸린다 | 기록만 |
| 12 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:249` | `atchmnflSeqNo`·`atchmnflSn`을 숫자인지 확인하지 않고 파일 경로에 넣는다(`%2F` 같은 값이면 폴더 밖에 쓴다). 출처가 청약홈 HTML이라 가능성은 낮다 | 기록만 |
| 13 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:80` | `PK\x03\x04`로 시작하는 zip·docx도 `hwpx`, 결과 `hwp`로 센다(설계 §2를 따른 것). 헤더 확장자가 `zip`이면 `ext_mismatch`만 켜진다 | 기록만 |
| 14 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:321` | 점검 안내처럼 링크도 `pop_btn_txt`도 없는 200 페이지가 `no_link`로 세어져 오류 수에 안 든다. 리포트의 「LH 10건 밖 no_link」와 링크 있는 공고 수 차이로는 드러난다 | 기록만 |
| 15 | Suggestion | `src/cheongyak_rag/ingest/notice_doc_report.py:44` | `MEANING["error"]`(개념 표와 리포트에 그대로 실림)가 오류 원인 일부만 적었다. 링크에 번호가 없는 경우 · NetFUNNEL이 첨부 대신 온 경우 · 상세 페이지 받기 실패 · `pblanc_url` 비어 있음 · 빈 본문(#3 fix)도 `error`다. 같은 줄 143의 「링크 있는 공고」는 `전체 − no_link`라 상세 페이지 받기에 실패한 공고도 들어간다 | 기록만 |
| 16 | Suggestion | `src/cheongyak_rag/ingest/notice_doc_report.py:5` | 「구간 문구는 plan 문장 그대로다」라고 했지만 1~3 구간의 「리포트에」가 빠졌다. 3~4번째 줄 입력 목록에도 `runs/72/notes.md`가 없다 | 기록만 |
| 17 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:247` | `_collect_link` docstring이 「못 받았으면 None」이라 했지만 PDF 열기 실패는 받았기 때문에 바이트 수를 돌려주고, NetFUNNEL 첨부·빈 본문은 받았어도 `None`이다 | 기록만 |
| 18 | Suggestion | `tests/test_notice_doc_fetch.py:236` | 테스트 빈틈: 같은 크기·다른 sha256 파일 재사용 · 이전 `hwp`/`other` 줄 재사용 · 링크에 번호 없음 · 「헤더에 파일 이름 없음」 note · `pblanc_url` 빈 공고 · `test_notice_doc_cli.py`가 다른 테스트 모듈에서 import · 네트워크 차단 fixture 없음 · `"4" in error` assert가 느슨함 | 기록만 |
| 19 | Suggestion | `src/cheongyak_rag/ingest/notice_doc.py:471` | 실행이 중간에 끊기면 목록은 남지만 `last_run.json`은 이전 값이다. 리포트가 결과 수 불일치로 막아 주지만 수가 우연히 같으면 통과한다 | 기록만 |
| 20 | Suggestion | `docs/plans/72-1109-design-notice-doc.md:37` | 단어장 검사: 「쓰지 말 말」 중 첨부파일 · 공고 PDF · 건너뛰기 · 스킵은 diff의 코드·주석·docstring·README·리포트에 0건이다. 「조용히 건너뛰면」은 일반 동사로 쓴 한 곳이다(main 세션이 쓴 설계 문서). 「첨부」(9곳)는 단어장의 「공고문」 뜻 칸이 쓰는 말이다 | 기록만 |

## plan 대조

| plan 기준 | 코드가 만족하나 | 증거 |
| --- | --- | --- |
| 1. 실제 DB `notices` 84건을 읽어(쓰지 않는다) 공고마다 상세 페이지·첨부를 받아 저장하고 `manifest.jsonl`·`runs/72/last_run.json`을 쓰고 exit 0. 공고 하나가 실패해도 계속하고 `error`로 남긴다 | 예 | `runs/72/last_run.json` notices 84; `notice_doc.py:_load_notices`가 SELECT만; `tests/test_notice_doc_cli.py::test_one_notice_crashing_does_not_stop_the_rest`; 전체 1184 passed |
| 2. 파일 이름 `<houseManageNo>_<pblancNo>_<atchmnflSeqNo>_<atchmnflSn>.<ext>`, `ext`는 앞 바이트로 정한다 | 예 | `data/raw/notices/2026000103_2026000103_1797255_9.pdf` 등 74개; `tests/test_notice_doc_fetch.py::test_rfc5987_header_saves_pdf_with_open_check` |
| 3. `filename*`와 `filename` 두 꼴을 읽고 둘 다 있으면 `filename*`; 헤더 없으면 앞 바이트로만 정하고 「헤더 없음」을 적는다 | 예 | `tests/test_notice_doc_parse.py::test_parse_disposition`, `test_notice_doc_fetch.py::test_both_header_forms_follow_filename_star`, `::test_no_header_uses_magic_bytes_and_notes_it` |
| 4. 목록 한 줄의 칸 + 링크 없는 공고는 `url` null · `no_link` · 다른 외부 링크를 `note`에 | 예 | `notice_doc.py:_row`; `tests/test_notice_doc_fetch.py::test_no_link_notice_keeps_one_row_with_other_links_in_note`; `docs/72-notice-doc.md` 링크 없음 10건 |
| 5. 두 번째 실행에서 파일이 있고 크기·sha256이 같으면 다시 받지 않는다. 새 다운로드 0, 결과별 공고 수 같음 | 예 | `runs/72/last_run.json` new_downloads 0, `docs/72-notice-doc.md` 4절(첫 실행 74 → 0, 결과별 수 같음); `::test_rerun_does_not_download_again` |
| 6. 리포트가 `docs/72-notice-doc.md`를 쓰고 첫 줄이 결론 한 문장, 이하 표·목록·재실행·실행 시간·바이트 | 예 | `docs/72-notice-doc.md:1`; `tests/test_notice_doc_report.py::test_first_line_is_one_sentence_conclusion` |
| 7. 요청 사이 0.5초, 429·5xx·연결 오류 1·2·4·8초 최대 4번, 50MB 초과 중단, 시간 제한 페이지 30초·첨부 120초 | 예 | `notice_doc.py:27-33`; `::test_429_then_success_backs_off`(sleep 목록 `[0.5, 0.5, 1, 0.5]`), `::test_5xx_four_retries_then_error`, fix `91585d0`로 크기·시간 제한 테스트가 첨부 분기를 탄다. 시간 초과 재시도는 지적 8 |
| 8. 테스트가 네트워크를 쓰지 않고 fixture 두 개와 다룰 것 아홉 가지 | 예 | `httpx.MockTransport` 사용, 네트워크 차단 fixture는 없다(지적 18); `tests/fixtures/notice_doc_with_link.html`·`notice_doc_no_link.html` |
| 9. 전체 테스트 통과, `ruff check` · `ruff format --check` 통과 | 예 | 1184 passed; `All checks passed!`; `199 files already formatted` |
| 실패 징후 1: 링크 있는 공고 중 `error` 공고 수 (0 → 통과) | 판정 불가 | 값만 적는다: 74건 중 error 0건, 링크 있는 공고 수 74(착수 때와 같음) — `docs/72-notice-doc.md:11`. 지적 3 fix 전 코드로 쟀다. 빈 본문 응답은 이 실행에 없었다 |
| 실패 징후 2: LH 10건 밖 `no_link` (0 → 통과) | 판정 불가 | 값만 적는다: 0건 — `docs/72-notice-doc.md:12`. HTML 붙이기는 지적 9(defer) |
| 실패 징후 3·4: 텍스트 없는 PDF 건수 · `hwp`·`other` 건수 (오류 아님, baseline 없음) | 예 | 0건 · hwp 0 · other 0 — `docs/72-notice-doc.md:13-14` |
| 범위 밖: DB 쓰기·마이그레이션·판정·검색·웹 코드 변경 없음 | 예 | `git diff --stat main...HEAD`에 `src/` 아래 새 파일 둘(`ingest/notice_doc.py`·`ingest/notice_doc_report.py`)뿐이고 기존 파일 변경 없음 |

fix 뒤 전체 테스트를 다시 돌렸다: 1184 passed, `ruff check` · `ruff format --check` 통과. 실제 청약홈 실행(74건)은 fix 전 코드로 한 번이라 fix 뒤 코드로 다시 재지 않았다(plan 환경 절이 청약홈 요청을 늘리지 말라고 했다).
