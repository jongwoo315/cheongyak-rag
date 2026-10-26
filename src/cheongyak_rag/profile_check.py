"""#77 검증 도구 — 점수표 원문 대조, 부분 프로필 범위의 soundness·tightness 측정.

`profile.py`가 낸 값이 맞는지 따로 재는 코드라 `profile.py`와 분리했다.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from cheongyak_rag import profile
from cheongyak_rag.profile import Profile

ROOT = Path(__file__).resolve().parents[2]
RAW_LAW = ROOT / "data" / "raw" / "law-008243-20260615.json"

# 원문 표의 행 수. 파싱이 행을 빠뜨리면 대조가 공허하게 참이 된다
EXPECTED_ROWS = {"homeless": 16, "dependents": 7, "savings": 17}
_BLOCKS = {1: "homeless", 2: "dependents", 3: "savings"}  # 표의 가로 구분선(├)으로 나뉜 덩어리

Row = tuple[str, int, int | None, int]  # (항목, 하한, 상한 미포함, 점수)


def _flatten(x):
    for v in x:
        if isinstance(v, list):
            yield from _flatten(v)
        else:
            yield v


def parse_bracket(text: str) -> tuple[int, int | None]:
    """구간 문자열 → (하한, 상한 미포함). 예: `8년 이상～9년 미만`, `6개월 미만`, `6명이상`."""
    nums = [
        int(n) * 12 if unit == "년" else int(n)
        for n, unit in re.findall(r"(\d+)\s*(년|개월|명)", text)
    ]
    over, under = "이상" in text, "미만" in text
    if over and under:
        return nums[0], nums[1]
    if under:
        return 0, nums[0]
    if over:
        return nums[0], None
    return nums[0], nums[0] + 1  # `3명`처럼 딱 그 값


def parse_table(lines: list[str]) -> list[Row]:
    """별표 1의 가점 산정기준 상자 표를 (항목, 하한, 상한, 점수) 행으로 읽는다.

    표는 2열 배치다. 줄마다 `│`로 나눠 칸 3·4(왼쪽 구간·점수)와 5·6(오른쪽)을 읽는다.
    """
    rows: list[Row] = []
    block = 0
    for line in lines:
        if line.startswith("├"):
            block += 1
        elif line.startswith("│") and "─" not in line and block in _BLOCKS:
            cells = [c.strip() for c in line.split("│")]
            for span, score in ((cells[3], cells[4]), (cells[5], cells[6])):
                if span and score.isdigit():
                    lo, hi = parse_bracket(span)
                    rows.append((_BLOCKS[block], lo, hi, int(score)))
    return rows


def load_raw_rows(path: Path = RAW_LAW) -> list[Row]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    for unit in raw["법령"]["별표"]["별표단위"]:
        if unit.get("별표구분") == "별표" and unit.get("별표번호") == "0001":
            return parse_table(list(_flatten(unit["별표내용"])))
    raise ValueError("별표 1을 찾지 못했다")


def constant_rows() -> list[Row]:
    tables = (
        ("homeless", profile.HOMELESS_TABLE),
        ("dependents", profile.DEPENDENTS_TABLE),
        ("savings", profile.SAVINGS_TABLE),
    )
    return [(key, lo, hi, score) for key, table in tables for lo, hi, score in table]


def table_mismatches(parsed: list[Row], consts: list[Row]) -> list[tuple[str, Row]]:
    """원문에만 있는 행과 상수에만 있는 행. 둘이 같으면 빈 목록이다."""
    a, b = Counter(parsed), Counter(consts)
    return [("원문에만", r) for r in (a - b)] + [("상수에만", r) for r in (b - a)]


# ── 부분 프로필 범위 측정 ────────────────────────────────────────────────

ITEMS = ("homeless", "dependents", "savings")
FIELDS = tuple(f.name for f in dataclasses.fields(Profile))
# 칸 하나를 모를 때 점수가 달라질 수 있는 항목
DEPENDS = {
    "birth_date": ("homeless", "savings"),
    "married": ITEMS,
    "marriage_date": ("homeless",),
    "homeless_now": ("homeless",),
    "ever_owned": ("homeless",),
    "homeless_since": ("homeless",),
    "is_household_head": ("dependents",),
    "children_unmarried": ("dependents",),
    "children_30plus_1y": ("dependents",),
    "ascendants_3y": ("dependents",),
    "ascendants_any_owner": ("dependents",),
    "savings_join_date": ("savings",),
    "spouse_has_savings": ("savings",),
    "spouse_savings_join_date": ("savings",),
}


def _pick(rng: random.Random, lo: date, hi: date) -> date:
    return lo + timedelta(days=rng.randint(0, max(0, (hi - lo).days)))


def random_complete(rng: random.Random, as_of: date, minimal: bool = False) -> Profile:
    """서로 모순이 없는 무작위 완전 프로필.

    기본은 점수에 안 쓰이는 칸도 채운다. `minimal`이면 안 쓰이는 칸을 비워
    「missing이 비면 한 값으로 정해진다」를 같이 시험한다.
    `married=False`면 혼인신고일을 비운다(혼인 이력 없음으로 읽는다 — profile.py `_missing`).
    """
    young = rng.random() < 0.35
    latest = profile._latest_birth(profile.MIN_AGE, as_of)
    birth = latest - timedelta(
        days=rng.randint(0, 365 * 8) if young else rng.randint(365 * 8, 365 * 60)
    )
    adult = profile.add_years(birth, 19)

    married = rng.random() < 0.55
    marriage = None
    if married:
        at = profile.add_years(birth, rng.randint(18, 45)) + timedelta(days=rng.randint(0, 364))
        marriage = min(as_of, at)
    homeless_now = rng.random() < 0.85
    owned = rng.random() < 0.4
    since = _pick(rng, adult, as_of) if owned else None
    if minimal and not homeless_now:
        marriage, owned, since = None, None, None

    asc = rng.randint(0, 3)
    head, owner = rng.random() < 0.6, rng.random() < 0.3
    if minimal and asc == 0:
        head = owner = None
    elif minimal and not head:
        owner = None

    join = (
        _pick(rng, birth, adult - timedelta(days=1))
        if rng.random() < 0.3
        else _pick(rng, adult, as_of)
    )
    spouse_has = rng.random() < 0.7 if married else (None if minimal else False)
    spouse_join = _pick(rng, profile.add_years(as_of, -40), as_of) if spouse_has else None
    return Profile(
        birth_date=birth,
        married=married,
        marriage_date=marriage,
        homeless_now=homeless_now,
        ever_owned=owned,
        homeless_since=since,
        is_household_head=head,
        children_unmarried=rng.randint(0, 4),
        children_30plus_1y=rng.randint(0, 2),
        ascendants_3y=asc,
        ascendants_any_owner=owner,
        savings_join_date=join,
        spouse_has_savings=spouse_has,
        spouse_savings_join_date=spouse_join,
    )


def erase(rng: random.Random, p: Profile) -> Profile:
    """채워진 칸을 무작위로 지운다. 지우는 비율은 프로필마다 다르다."""
    q = rng.choice((0.15, 0.4, 0.7, 0.9))
    blank = {f: None for f in FIELDS if getattr(p, f) is not None and rng.random() < q}
    return dataclasses.replace(p, **blank)


def exact(p: Profile, as_of: date, items=ITEMS) -> dict[str, int]:
    """완전 프로필의 실제 항목 점수. 범위 엔진을 거치지 않고 규칙 함수를 바로 부른다."""
    p = profile._resolve(p, as_of)
    out = {}
    for item in items:
        if item == "homeless":
            out[item] = (
                0
                if p.homeless_now is False
                else profile._homeless_score(
                    p.birth_date, p.marriage_date, p.ever_owned, p.homeless_since, as_of
                )
            )
        elif item == "dependents":
            counted = p.is_household_head is True and p.ascendants_any_owner is not True
            members = (
                int(bool(p.married))
                + p.children_unmarried
                + p.children_30plus_1y
                + (p.ascendants_3y if counted else 0)
            )
            out[item] = profile.dependents_points(members)
        else:
            own = profile._savings_own_points(p.savings_join_date, p.birth_date, as_of)
            bonus = profile.spouse_bonus(p.spouse_savings_join_date, as_of)
            out[item] = min(profile.SAVINGS_MAX, own + bonus)
    return out


def _range_of(score, item: str) -> profile.Range:
    return getattr(score, item)


def soundness(n: int = 2000, seed: int = 77, shrink: bool = False) -> dict:
    """무작위 완전 프로필에서 칸을 지운 프로필의 범위가 실제 점수를 놓친 건수.

    `shrink`는 측정 도구 자체를 시험하려고 범위의 위쪽을 1 깎는 스위치다.
    """
    rng = random.Random(seed)
    bad, erased = [], 0
    for i in range(n):
        as_of = date(2024, 3, 1) + timedelta(days=rng.randint(0, 1035))
        full = random_complete(rng, as_of, minimal=rng.random() < 0.5)
        part = erase(rng, full)
        erased += sum(getattr(full, f) is not None and getattr(part, f) is None for f in FIELDS)
        got, actual = profile.score(part, as_of), exact(full, as_of)
        actual["total"] = sum(actual.values())
        for item in (*ITEMS, "total"):
            r = _range_of(got, item)
            hi = r.hi - 1 if shrink and r.hi > r.lo else r.hi
            if not r.lo <= actual[item] <= hi:
                blank = [f for f in FIELDS if getattr(part, f) is None and getattr(full, f)]
                bad.append(
                    {
                        "i": i,
                        "as_of": as_of.isoformat(),
                        "item": item,
                        "range": [r.lo, hi],
                        "actual": actual[item],
                        "erased": blank,
                        "full": full.to_dict(),
                    }
                )
    return {
        "n": n,
        "seed": seed,
        "violations": len(bad),
        "examples": bad[:5],
        "avg_erased": erased / n,
    }


def _candidates(name: str, as_of: date):
    kind = profile._KINDS[name]
    if kind == "bool":
        return (True, False)
    if kind == "count":
        return range(profile.MAX_COUNT + 1)
    first = profile._earliest(as_of)
    return (first + timedelta(days=d) for d in range((as_of - first).days + 1))  # 하루 단위


def tightness(bases: int = 10, seed: int = 77, as_of: date = date(2026, 10, 23)) -> dict:
    """칸 하나만 모를 때 범위가 전수 대입의 실제 최소·최대와 같은 비율.

    완전 프로필에서 칸 하나를 지우고, 그 칸의 가능한 값(날짜는 하루 단위, 수는 0~10, 불리언은 둘)을
    전부 넣어 모순이 없는 것의 실제 점수를 센다. (칸, 항목) 쌍마다 범위의 lo·hi가 둘 다 같으면
    맞다. 칸을 지웠을 때 다른 칸이 비어 완성이 안 되는 값이 있으면(혼인 여부를 지웠는데 혼인신고일이
    없는 경우) 한 칸만 모르는 경우가 안 만들어지므로 그 칸은 뺀다. 칸이 항목에 아예 영향을 안 줘서
    범위와 전수 결과가 둘 다 한 점이면 재는 것이 없으므로 센 쌍에서 뺀다.
    """
    rng = random.Random(seed)
    pairs: dict[tuple[str, str], dict] = {}
    skipped = Counter()
    for _ in range(bases):
        full = random_complete(rng, as_of)
        for name in FIELDS:
            if getattr(full, name) is None:
                continue
            got = profile.score(dataclasses.replace(full, **{name: None}), as_of)
            seen: dict[str, list[int]] = {it: [] for it in DEPENDS[name]}
            closed = False
            for v in _candidates(name, as_of):
                try:
                    cand = profile._resolve(dataclasses.replace(full, **{name: v}), as_of)
                except profile.ProfileError:
                    continue
                if profile._missing(cand):
                    closed = True
                    break
                for item, pts in exact(cand, as_of, DEPENDS[name]).items():
                    seen[item].append(pts)
            if closed or not any(seen.values()):
                skipped[name] += 1
                continue
            for item, pts in seen.items():
                r = _range_of(got, item)
                lo, hi = min(pts), max(pts)
                if lo == hi and r.lo == r.hi:
                    continue
                cell = pairs.setdefault((name, item), {"measured": 0, "tight": 0, "loose": []})
                cell["measured"] += 1
                if (r.lo, r.hi) == (lo, hi):
                    cell["tight"] += 1
                else:
                    cell["loose"].append({"range": [r.lo, r.hi], "enumerated": [lo, hi]})
    measured = sum(c["measured"] for c in pairs.values())
    tight = sum(c["tight"] for c in pairs.values())
    return {
        "bases": bases,
        "seed": seed,
        "measured": measured,
        "tight": tight,
        "ratio": tight / measured if measured else 0.0,
        "pairs": [{"field": f, "item": i, **c} for (f, i), c in sorted(pairs.items())],
        "loose": [
            {"field": f, "item": i, **x} for (f, i), c in sorted(pairs.items()) for x in c["loose"]
        ][:10],
        "skipped": dict(skipped),
    }
