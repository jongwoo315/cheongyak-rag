"""#77 검증 도구 — 점수표 원문 대조, 부분 프로필 범위의 soundness·tightness 측정.

`profile.py`가 낸 값이 맞는지 따로 재는 코드라 `profile.py`와 분리했다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from cheongyak_rag import profile

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
