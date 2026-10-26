"""프로필을 판정용 값과 가점(부분 입력이면 범위)으로 바꾸는 CLI와 리포트 (#77).

    uv run python -m cheongyak_rag.profile_score --profile p.json --as-of 2026-10-23
    uv run python -m cheongyak_rag.profile_score --profile p.json --notice 2026000001:2026000001
    uv run python -m cheongyak_rag.profile_score --report

`--notice`는 `notice_law_versions` view에서 공고일과 법령 버전(MST)을 읽는다. 점수표는 MST 286965의
별표 1만 받았으므로 다른 버전이 걸린 공고는 계산하지 않는다. `--report`는 샘플 프로필 3개를
공고 전부에 계산하고 점수표 대조 · FAQ 사례 · 범위 soundness · tightness를 재서
`runs/77/last_run.json`과 `docs/77-profile-score.md`를 쓴다.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag import profile
from cheongyak_rag import profile_check as check
from cheongyak_rag.config import settings
from cheongyak_rag.ingest.notice_report import _bullets, _table

EXPECTED_MST = "286965"  # 별표 1을 읽은 법령 버전 (#78: 공고 84건 전부 이 버전이다)
RUN_PATH = check.ROOT / "runs/77/last_run.json"  # 어느 디렉터리에서 돌려도 repo 안에 쓴다
OUT_PATH = check.ROOT / "docs/77-profile-score.md"
SAMPLES_PATH = check.ROOT / "runs/77/sample-profiles.json"
SEED = 77
FAQ_AS_OF = date(2026, 10, 23)  # 부양가족 사례는 날짜와 무관하다. 계산에 필요해서 하나 정했다
TIGHTNESS_AS_OF = date(2026, 10, 23)
ITEM_LABEL = {"homeless": "① 무주택", "dependents": "② 부양가족", "savings": "③ 통장"}


# ── FAQ 사례 ─────────────────────────────────────────────────────────────
# 기대값은 data/processed/faq-20240529.jsonl 답 문장의 숫자다. tests/test_profile_faq.py와 같은 값을
# 리포트용으로 한 번 더 적었다 (리포트가 테스트 파일을 가져오지 않는다).

FAQ170_ROWS = [  # (가입일, 공고일, 기간, 점수)
    (date(2001, 1, 15), date(2003, 5, 14), "2년4월0일", 3),
    (date(2006, 7, 7), date(2014, 8, 31), "8년1월25일", 3),
    (date(2014, 9, 1), date(2015, 10, 31), "1년2월0일", 2),
    (date(2015, 4, 1), date(2019, 4, 21), "4년0월21일", 3),
    (date(2019, 4, 22), date(2019, 8, 31), "0년4월10일", 1),
    (date(2019, 9, 1), date(2020, 6, 30), "0년10월0일", 1),
]


def _dependents(**fields) -> int:
    base = {"married": False, "children_unmarried": 0, "children_30plus_1y": 0, "ascendants_3y": 0}
    return profile.score(profile.Profile(**{**base, **fields}), FAQ_AS_OF).dependents.lo


def _asc(head: bool, owner: bool | None) -> int:
    """직계존속 2명이 있을 때 ②."""
    return _dependents(is_household_head=head, ascendants_3y=2, ascendants_any_owner=owner)


def _dep_text(*points: int) -> str:
    return " · ".join(f"② {v}점" for v in points)


def _faq151() -> str:
    p = profile.Profile(
        birth_date=date(1986, 5, 1),
        married=False,
        ever_married=False,
        homeless_now=True,
        ever_owned=False,
    )
    r = profile.score(p, date(2026, 5, 1))
    return f"무주택기간 {r.values['homeless_period'].value.years}년 · ① {r.homeless.lo}점"


def _faq153() -> str:
    birth = date(1980, 3, 1)
    cells = [
        profile.homeless_start(birth, None, False, None),
        profile.homeless_start(birth, date(2008, 6, 1), False, None),
        profile.homeless_start(birth, None, True, date(2014, 9, 1)),
        profile.homeless_start(birth, date(2008, 6, 1), True, date(2014, 9, 1)),
    ]
    return " · ".join(c.isoformat() for c in cells)


def _faq156() -> str:
    base = {
        "birth_date": date(1990, 1, 1),
        "married": True,
        "marriage_date": date(2012, 3, 1),
        "homeless_now": True,
    }
    clean = profile.score(profile.Profile(**base, ever_owned=False), FAQ_AS_OF)
    again = profile.score(
        profile.Profile(**base, ever_owned=True, homeless_since=date(2018, 6, 1)), FAQ_AS_OF
    )
    return f"{clean.values['homeless_start'].value} · {again.values['homeless_start'].value}"


def faq_cases() -> list[dict]:
    """(q_no, 사례, 기대, 계산, 일치). 계산은 `profile.py`를 불러 새로 센다."""
    minor_start = profile.savings_start(date(2019, 1, 1), date(2007, 1, 1))
    cases = [
        (46, "2024-01-01 전 미성년 가입 5년 + 이후 2년", "미성년 기간 인정 4년0월0일",
         f"미성년 기간 인정 {profile.period(minor_start, date(2025, 12, 31))}"),
        (151, "35세 귀화, 40세 청약, 무주택 (1986-05-01생, 공고일 2026-05-01)",
         "무주택기간 10년 · ① 22점", _faq151()),
        (153, "기산일 네 칸 (1980-03-01생, 혼인신고일 2008-06-01, 무주택자가 된 날 2014-09-01)",
         "2010-03-01 · 2008-06-01 · 2014-09-01 · 2014-09-01", _faq153()),
        (154, "세대 내 1주택 소유", "① 0점",
         f"① {profile.score(profile.Profile(homeless_now=False), FAQ_AS_OF).homeless.lo}점"),
        (156, "30세 전 최초 혼인 후 이혼·재혼", "2012-03-01 · 2018-06-01", _faq156()),
        (157, "본인은 부양가족이 아니다 (세대원 없음)", "② 5점", f"② {_dependents()}점"),
        (158, "배우자는 같은 등본에 없어도 부양가족", "② 10점", f"② {_dependents(married=True)}점"),
        (159, "미혼 자녀 2 + 30세 이상 미혼 1 (혼인한 자녀는 입력 칸이 없다)", "② 20점",
         f"② {_dependents(children_unmarried=2, children_30plus_1y=1)}점"),
        (161, "직계존속 2명, 소유자 있음 · 없음", "② 5점 · ② 15점",
         _dep_text(_asc(True, True), _asc(True, False))),
        (162, "직계존속 2명, 세대주 아님 · 세대주", "② 5점 · ② 15점",
         _dep_text(_asc(False, None), _asc(True, False))),
        (170, "배우자 통장 기간 산정 예시 6행",
         ", ".join(f"{t} {p}점" for _, _, t, p in FAQ170_ROWS),
         ", ".join(f"{profile.period(j, n)} {profile.spouse_bonus(j, n)}점"
                   for j, n, _, _ in FAQ170_ROWS)),
    ]  # fmt: skip
    return [
        {"q_no": q, "case": c, "expected": e, "actual": a, "match": e == a} for q, c, e, a in cases
    ]


def faq170_items() -> list[dict]:
    out = []
    for join, notice_de, text, points in FAQ170_ROWS:
        got, bonus = str(profile.period(join, notice_de)), profile.spouse_bonus(join, notice_de)
        out.append(
            {
                "join": join.isoformat(),
                "notice": notice_de.isoformat(),
                "expected": f"{text} {points}점",
                "actual": f"{got} {bonus}점",
                "text_ok": got == text,
                "points_ok": bonus == points,
            }  # fmt: skip
        )
    return out


# ── 측정 ─────────────────────────────────────────────────────────────────


def table_check() -> dict:
    parsed = check.load_raw_rows(check.RAW_LAW)
    mism = check.table_mismatches(parsed, check.constant_rows())
    counts = dict(Counter(r[0] for r in parsed))
    only_raw = sum(1 for kind, _ in mism if kind == "원문에만")
    return {
        "rows": counts,
        "expected_rows": check.EXPECTED_ROWS,
        "row_count_ok": counts == check.EXPECTED_ROWS,
        "mismatches": [[kind, list(row)] for kind, row in mism],
        "cells": max(only_raw, len(mism) - only_raw),
    }


def _notices(engine: Engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT v.house_manage_no, v.pblanc_no, n.house_nm, v.rcrit_pblanc_de, v.mst"
                " FROM notice_law_versions v JOIN notices n USING (house_manage_no, pblanc_no)"
                " ORDER BY v.rcrit_pblanc_de DESC, v.house_manage_no DESC"
            )
        ).all()


def calc_notices(engine: Engine, samples: list[dict]) -> dict:
    """공고 전부 × 샘플 프로필 전부를 계산한다. 계산이 안 되는 것(예외 · MST 불일치)을 센다."""
    notices = _notices(engine)
    parsed = [(s["name"], profile.Profile.from_dict(s["profile"])) for s in samples]
    results, failures = [], []
    for n in notices:
        for name, p in parsed:
            key = {"house_manage_no": n.house_manage_no, "pblanc_no": n.pblanc_no, "sample": name}
            if n.mst != EXPECTED_MST:
                failures.append({**key, "kind": "mst", "detail": f"MST {n.mst}"})
                continue
            try:
                r = profile.score(p, n.rcrit_pblanc_de)
            except Exception as e:  # noqa: BLE001 — 어떤 예외든 실패로 세고 리포트에 남긴다
                failures.append({**key, "kind": "error", "detail": f"{type(e).__name__}: {e}"})
                continue
            results.append(
                {
                    **key,
                    "house_nm": n.house_nm,
                    "rcrit_pblanc_de": n.rcrit_pblanc_de.isoformat(),
                    "total": [r.total.lo, r.total.hi],
                    "missing": list(r.missing),
                }  # fmt: skip
            )
    by_sample = []
    for name, _ in parsed:
        mine = [r for r in results if r["sample"] == name]
        by_sample.append(
            {
                "sample": name,
                "ok": len(mine),
                "failed": sum(1 for f in failures if f["sample"] == name),
                "total_lo": [
                    min((r["total"][0] for r in mine), default=None),
                    max((r["total"][0] for r in mine), default=None),
                ],
                "total_hi": [
                    min((r["total"][1] for r in mine), default=None),
                    max((r["total"][1] for r in mine), default=None),
                ],
                "missing": mine[0]["missing"] if mine else [],
            }  # fmt: skip
        )
    return {
        "calc": {
            "notices": len(notices),
            "samples": len(parsed),
            "ok": len(results),
            "failed": len(failures),
            "failures": failures[:10],
        },
        "by_sample": by_sample,
        "results": results,
    }


# ── 리포트 ───────────────────────────────────────────────────────────────


def _band_symptom1(a_ok: int, a_n: int, b: int, c: int) -> str:
    if a_ok == a_n and b == 0 and c == 0:
        return "(a) 전부 일치, (b) 0, (c) 0 → 통과"
    if b >= 1 or c >= 1:
        return "(b) 또는 (c)가 1 이상 → 미완"
    return "(a)에서 어긋난 사례가 있다 → 설계 §6 열린 질문에 걸렸으면 다시 잰다, 아니면 미완"


def _band_tightness(ratio: float) -> str:
    if ratio >= 0.95:
        return "0.95 이상 → 통과"
    return "0.80 이상 0.95 미만 → 다시 잰다" if ratio >= 0.80 else "0.80 미만 → 미완"


def _band_faq170(items: list[dict]) -> str:
    if all(i["text_ok"] for i in items):
        return "6/6 → 통과"
    if all(i["points_ok"] for i in items):
        return "점수는 6/6, 문자열만 어긋남 → 가입일 포함 여부를 다시 본다"
    return "점수가 어긋남 → 미완"


def _cell_text(entry: dict) -> str:
    return f"{entry['range']} / 전수 {entry['enumerated']}"


OPEN_QUESTIONS = """\
설계 §6이 원문이 정하지 않았다고 한 네 자리다. 고른 쪽을 테스트로 고정했다.

### 열린 질문 1 — 30세 미만 미혼 무주택자의 ① 점수

- 고른 것: 0점.
- 이유: 별표 1은 기산일(만 30세 되는 날)만 정한다. 표 첫 칸 「1년 미만 2점」은 기산일부터 센 기간에 붙는 점수이고, 기산일 전의 점수는 표에 없다. 무주택기간이 아직 시작되지 않았다.
- 다른 해석이면: 기산일 전에도 첫 칸 2점을 준다. 2000-01-01생 미혼 무주택자, 공고일 2026-10-23이면 고른 해석 0점, 다른 해석 2점이다.
- 고정한 테스트: `tests/test_profile_score.py::test_open_q1_under_30_unmarried_scores_zero`

### 열린 질문 2 — 2월 29일 출생자의 평년 생일

- 고른 것: 2월 28일.
- 이유: 윤년이 아닌 해에는 2월 29일이 없어서, 그 달의 마지막 날을 생일로 본다. 통장 가입일을 개월 수로 셀 때 31일 가입을 짧은 달 말일로 맞추는 것과 같은 규칙이다.
- 다른 해석이면: 3월 1일. 1996-02-29생 미혼 무주택자, 공고일 2026-02-28이면 고른 해석은 이날 만 30세가 돼 ① 2점, 다른 해석은 아직 만 29세라 0점이다.
- 고정한 테스트: `tests/test_profile_score.py::test_open_q2_feb29_birth_turns_30_on_feb28`

### 열린 질문 3 — 30세 되는 날 당일

- 고른 것: 생일 당일부터 만 30세로 본다. 무주택 기산일도 그 날이다. 자녀 수는 사용자가 센 값을 받는다(`children_unmarried` · `children_30plus_1y`).
- 이유: 만 나이는 출생일을 1일로 세어 생일 당일에 한 살이 오른다. 가입일 당일을 1일로 세는 FAQ 170 방식과 같은 방향이다.
- 다른 해석이면: 생일 다음 날부터 만 30세. 1996-10-23생 미혼 무주택자, 공고일 2026-10-23이면 고른 해석은 무주택기간 1일로 ① 2점, 다른 해석은 0점이다.
- 고정한 테스트: `tests/test_profile_score.py::test_open_q3_thirtieth_birthday_starts_the_count`

### 열린 질문 4 — 배우자 통장에도 제10조⑥(미성년 기간 상한)을 적용하나

- 고른 것: 적용하지 않는다. 배우자 통장은 가입일 그대로 센다.
- 이유: 배우자 생년월일을 입력으로 받지 않는다.
- 다른 해석이면: 배우자의 미성년 가입 기간에도 상한을 적용한다. 점수는 달라지지 않는다. 제10조⑥은 기간을 2년 아래로 줄이지 못하고(2023-12-31 이전 부분을 2년으로 자를 뿐이다), 가산 3점은 배우자 가입기간 2년이면 채워진다. 2년 미만이면 상한에 걸리지 않아 같은 값이다.
- 고정한 테스트: `tests/test_profile_score.py::test_open_q4_spouse_savings_ignore_minor_cap`,
  `tests/test_profile_score.py::test_spouse_bonus_same_with_or_without_minor_cap`

### 설계가 정하지 않았던 자리 (루프가 정했다)

- 배우자 통장 유무: 입력 칸 `spouse_has_savings`를 더했다. `spouse_savings_join_date`가 비어 있을 때 「통장이 없다」와 「모른다」를 가르려는 것이다. 가입일을 적으면 통장이 있고 배우자도 있는 것으로 채운다.
- `married`는 공고일 현재 배우자가 있느냐다. `ever_married` 칸을 더했다(혼인한 적이 있다, 이혼·사별 포함). `married=false`만으로는 「혼인한 적이 없다」와 「이혼·사별했다」를 못 가르는데 ① 기산일은 후자에게 혼인신고일을 쓰기 때문이다. `ever_married`가 비어 있으면 ①은 범위로 나오고 `missing`에 올라온다. 배우자가 있거나 혼인신고일이 있으면 `ever_married`는 true로 채운다. 코드 리뷰가 이 자리를 잡았다(`married=false`만 받으면 ①이 16점 틀린 값으로 확정됐다).
- 입력 범위: 공고일 현재 만 19세 이상, 혼인신고일은 만 18세 되는 날 이후, 통장 가입일은 출생일 이후. 어기면 `ProfileError`다. 모르는 날짜는 공고일 100년 전까지 본다.
- 기간 계산: 개월 수를 먼저 채우고 남은 날을 센다. 시작일에 개월을 더했을 때 그 달에 같은 날이 없으면 말일로 맞춘다(1월 31일 + 1개월 = 2월 말일).
- 제10조⑥은 공고일과 무관하게 모든 미성년 가입에 적용한다. 규칙이 2024-01-01을 경계로 정하기 때문이다.
"""  # noqa: E501 — 마크다운 줄은 줄바꿈하지 않는다


def render(run: dict) -> str:
    t, faq, f170 = run["table"], run["faq"], run["faq170"]
    snd, tight, calc = run["soundness"], run["tightness"], run["calc"]
    a_ok, a_n = faq["matched"], faq["cases"]
    first = (
        f"점수표 대조 어긋난 칸 {t['cells']}개, FAQ 사례 {a_ok}/{a_n} 일치"
        f"(FAQ 170 기간 문자열 {f170['matched']}/{f170['rows']}),"
        f" 범위 soundness 위반 {snd['violations']}건(무작위 {snd['n']}건),"
        f" 공고 {calc['notices']}건 × 샘플 {calc['samples']}개 계산 성공"
        f" {calc['ok']}/{calc['notices'] * calc['samples']}건이다."
    )
    lines = [
        first,
        "",
        "# #77 프로필 정규화 + 가점 계산 결과",
        "",
        f"실행 {run['run_at']} · 점수표 「주택공급에 관한 규칙」 별표 1 (MST {EXPECTED_MST})",
        "",
        "## 1. 실패 징후 측정값",
        "",
    ]
    items170 = f170["items"]
    rows = [
        (
            "1. jw 기준 — 사용자 입력을 판정용 값으로 바꿀 수 있나",
            f"(a) FAQ 사례 {a_ok}/{a_n} 일치 · (b) 점수표 어긋난 칸 {t['cells']}개"
            f" · (c) 계산 실패 {calc['failed']}건",
            _band_symptom1(a_ok, a_n, t["cells"], calc["failed"]),
        ),
        (
            "2. 부분 프로필 범위가 실제 값을 놓치나 (soundness)",
            f"무작위 {snd['n']}건 중 범위 밖 {snd['violations']}건 (시드 {snd['seed']})",
            "0 → 통과" if snd["violations"] == 0 else "1 이상 → 위반 사례를 아래 §4에 적었다",
        ),
        (
            "3. 범위가 쓸모 없이 넓은가 (tightness, baseline 없음 — 첫 측정)",
            f"{tight['tight']}/{tight['measured']} = {tight['ratio']:.3f}"
            f" (기준 프로필 {tight['bases']}개)",
            _band_tightness(tight["ratio"]),
        ),
        (
            "4. 기간 세는 법이 FAQ와 하루 어긋나나",
            f"FAQ 170 예시 {f170['matched']}/{f170['rows']}행이 문자열까지 일치",
            _band_faq170(items170),
        ),
        (
            "5. 점수표 파서가 행을 빠뜨렸나",
            "파싱한 행 수 {} (기대 {})".format(
                " · ".join(f"{ITEM_LABEL[k]} {t['rows'].get(k, 0)}" for k in check.EXPECTED_ROWS),
                " · ".join(str(t["expected_rows"][k]) for k in check.EXPECTED_ROWS),
            ),
            "16 · 7 · 17 → 통과" if t["row_count_ok"] else "행 수가 다르다 → 미완",
        ),
    ]
    lines += _table(["지표", "측정값", "해당 구간 (plan 문구)"], rows)

    lines += ["", "## 2. 점수표 원문 대조", ""]
    lines += _table(
        ["항목", "원문 표에서 읽은 행", "기대 행 수", "코드 상수 행"],
        [
            (
                ITEM_LABEL[k],
                t["rows"].get(k, 0),
                t["expected_rows"][k],
                len(run["constants"][k]),
            )
            for k in check.EXPECTED_ROWS
        ],
    )
    lines += ["", "어긋난 행 (원문에만 있거나 상수에만 있는 행):", ""]
    lines += _bullets([f"{kind}: {row}" for kind, row in t["mismatches"]])

    lines += ["", "## 3. FAQ 사례", ""]
    lines += _table(
        ["q_no", "사례", "기대 (FAQ 답)", "계산", "일치"],
        [(c["q_no"], c["case"], c["expected"], c["actual"], "○" if c["match"] else "✗")
         for c in faq["items"]],
    )  # fmt: skip

    lines += ["", "## 4. 범위 soundness", ""]
    lines += [
        f"무작위 완전 프로필 {snd['n']}개(시드 {snd['seed']})에서 칸을 무작위로 지운 프로필의"
        " 범위가"
        f" 지우기 전 실제 점수(항목별 · 합계)를 놓친 건수는 {snd['violations']}건이다."
        f" 프로필마다 지운 칸은 평균 {snd['avg_erased']:.1f}개다."
        " 실제 점수를 세는 쪽(`profile_check.exact`)도 기산일 · 통장 시작일 · 배우자 가산 규칙은"
        " `profile.py`와 같은 함수를 부른다."
        " 이 측정이 잡는 것은 범위 계산의 오류이고, 규칙 자체의 오류는 FAQ 사례와 손으로 센"
        " 테스트가 맡는다.",
        "",
    ]
    lines += _bullets(
        [
            f"{e['as_of']} {e['item']}: 범위 {e['range']} 실제 {e['actual']}, 지운 칸 {e['erased']}"
            for e in snd["examples"]
        ]
    )

    lines += ["", "## 5. 범위 tightness", ""]
    lines += [
        "완전 프로필에서 칸 하나만 지우고 그 칸의 가능한 값(날짜는 하루 단위, 수는 0~10,"
        " 불리언은 둘)을 전부 넣어 모순이 없는 것의 실제 최소·최대를 센다."
        " (칸, 항목) 쌍마다 범위의 lo·hi가 둘 다 같으면 맞다."
        f" 잰 쌍 {tight['measured']}개 중 {tight['tight']}개가 맞아 {tight['ratio']:.3f}이다.",
        "",
    ]
    lines += _table(
        ["칸", "항목", "잰 쌍", "맞은 쌍"],
        [(f"`{p['field']}`", ITEM_LABEL[p["item"]], p["measured"], p["tight"])
         for p in tight["pairs"]],
    )  # fmt: skip
    lines += ["", "범위와 전수 결과가 다른 쌍:", ""]
    lines += _bullets(
        [f"`{x['field']}` {ITEM_LABEL[x['item']]}: {_cell_text(x)}" for x in tight["loose"]]
    )
    skipped = tight["skipped"]
    lines += [
        "",
        "한 칸만 모르는 경우가 안 만들어져 뺀 칸(다른 칸이 비어 완성이 안 되는 값이 있다): "
        + (", ".join(f"`{k}` {v}회" for k, v in sorted(skipped.items())) or "없다"),
    ]

    lines += ["", "## 6. 공고별 계산 요약", ""]
    lines += [
        f"공고 {calc['notices']}건 × 샘플 {calc['samples']}개를 공고일 기준으로 계산했다."
        f" 성공 {calc['ok']}건, 실패 {calc['failed']}건(예외 또는 MST가 {EXPECTED_MST}가 아님).",
        "",
    ]
    lines += _table(
        [
            "샘플",
            "성공",
            "실패",
            "합계 lo (공고별 최소~최대)",
            "합계 hi (공고별 최소~최대)",
            "missing",
        ],
        [
            (
                s["sample"],
                s["ok"],
                s["failed"],
                f"{s['total_lo'][0]}~{s['total_lo'][1]}",
                f"{s['total_hi'][0]}~{s['total_hi'][1]}",
                len(s["missing"]),
            )
            for s in run["by_sample"]
        ],
    )
    lines += ["", "실패 사례:", ""]
    lines += _bullets(
        [
            f"`{f['house_manage_no']}` {f['sample']}: {f['kind']} {f['detail']}"
            for f in calc["failures"]
        ]
    )

    lines += ["", "## 7. 열린 질문", "", OPEN_QUESTIONS]
    lines += [
        "## 8. 다시 돌리는 법",
        "",
        "```bash",
        "uv run python -m cheongyak_rag.profile_score --report",
        "uv run python -m cheongyak_rag.profile_score --profile p.json --as-of 2026-10-23",
        "```",
    ]
    return "\n".join(lines) + "\n"


# ── 실행 ─────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"YYYY-MM-DD 날짜여야 한다: {text}") from None


def _score_command(args, engine: Engine | None) -> int:
    try:
        data = json.loads(args.profile.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise profile.ProfileError("프로필 JSON은 객체여야 한다")
        p = profile.Profile.from_dict(data)
    except (OSError, ValueError) as e:  # ProfileError는 ValueError다
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    extra = {}
    as_of = args.as_of
    if args.notice:
        hmn, _, pno = args.notice.partition(":")
        own = engine is None
        engine = engine or sa.create_engine(settings.database_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    sa.text(
                        "SELECT rcrit_pblanc_de, mst FROM notice_law_versions"
                        " WHERE house_manage_no = :h AND pblanc_no = :p"
                    ),
                    {"h": hmn, "p": pno},
                ).first()
        finally:
            if own:
                engine.dispose()
        if row is None:
            print(f"공고를 찾지 못했다: {args.notice}", file=sys.stderr)
            return 1
        as_of = row.rcrit_pblanc_de
        extra["notice"] = {
            "house_manage_no": hmn,
            "pblanc_no": pno,
            "rcrit_pblanc_de": as_of.isoformat(),
            "mst": row.mst,
        }
        if row.mst != EXPECTED_MST:
            why = (
                f"이 공고에 유효한 법령 버전이 MST {row.mst}이다. 점수표는 MST {EXPECTED_MST}의"
                " 별표 1만 받았으므로 계산하지 않는다"
            )
            print(why, file=sys.stderr)
            out = {"computed": False, "reason": why, "mst": row.mst, "expected_mst": EXPECTED_MST}
            print(json.dumps({**out, **extra}, ensure_ascii=False, indent=2))
            return 1
    try:
        result = profile.score(p, as_of)
    except (ValueError, OverflowError) as e:  # ProfileError와 극단적인 날짜(year 0·10000)
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    print(json.dumps({**result.to_dict(), **extra}, ensure_ascii=False, indent=2))
    return 0


def _report_command(args, engine: Engine | None) -> int:
    try:
        samples = json.loads(args.samples.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"샘플 프로필을 못 읽었다: {args.samples}: {e}", file=sys.stderr)
        return 1
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        calc = calc_notices(engine, samples)
    finally:
        if own:
            engine.dispose()
    cases = faq_cases()
    run = {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "table": table_check(),
        "constants": {k: [list(r) for r in rows] for k, rows in _constants_by_item().items()},
        "faq": {
            "cases": len(cases),
            "matched": sum(c["match"] for c in cases),
            "items": cases,
        },
        "soundness": check.soundness(args.soundness_n, seed=SEED),
        "tightness": check.tightness(bases=args.tightness_bases, seed=SEED, as_of=TIGHTNESS_AS_OF),
        **calc,
    }
    items170 = faq170_items()
    run["faq170"] = {
        "rows": len(items170),
        "matched": sum(i["text_ok"] and i["points_ok"] for i in items170),
        "items": items170,
    }
    report = render(run)
    _write(args.run, json.dumps(run, ensure_ascii=False, indent=2, default=str))
    _write(args.out, report)
    print(report.splitlines()[0])
    print(f"썼다: {args.run} · {args.out}")

    t, snd = run["table"], run["soundness"]
    bad = False
    if t["cells"] or not t["row_count_ok"]:
        print(f"점수표 대조 실패: 어긋난 칸 {t['cells']}개, 행 수 {t['rows']}", file=sys.stderr)
        bad = True
    if snd["violations"]:
        print(f"soundness 위반 {snd['violations']}건", file=sys.stderr)
        bad = True
    if run["calc"]["failed"]:
        print(f"계산 실패 {run['calc']['failed']}건", file=sys.stderr)
        bad = True
    return 1 if bad else 0


def _constants_by_item() -> dict[str, list]:
    out: dict[str, list] = {k: [] for k in check.EXPECTED_ROWS}
    for row in check.constant_rows():
        out[row[0]].append(row)
    return out


def main(argv=None, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(description="프로필을 판정용 값과 가점(범위)으로 바꾼다")
    ap.add_argument("--profile", type=Path, help="프로필 JSON (칸 이름: 값)")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--as-of", type=_date, metavar="YYYY-MM-DD", help="입주자모집공고일")
    when.add_argument(
        "--notice", metavar="HOUSE_MANAGE_NO:PBLANC_NO", help="DB 공고의 공고일을 쓴다"
    )
    ap.add_argument("--report", action="store_true", help="측정 리포트를 쓴다")
    ap.add_argument("--samples", type=Path, default=SAMPLES_PATH)
    ap.add_argument("--run", type=Path, default=RUN_PATH, help="실행 요약 JSON 경로")
    ap.add_argument("--out", type=Path, default=OUT_PATH, help="리포트 경로")
    ap.add_argument("--soundness-n", type=int, default=2000)
    ap.add_argument("--tightness-bases", type=int, default=20)
    args = ap.parse_args(argv)

    if args.report:
        return _report_command(args, engine)
    if args.profile is None or (args.as_of is None and args.notice is None):
        ap.error("--profile과 (--as-of 또는 --notice)가 필요하다. 리포트는 --report")
    return _score_command(args, engine)


if __name__ == "__main__":
    sys.exit(main())
