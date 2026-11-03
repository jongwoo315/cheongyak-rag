"""축별 판정을 경로별 판정으로 합치고(B8) 근거 원문이 붙은 응답을 만든다(B9) (#81).

B8은 결정론적 규칙이다: 우선순위 `INELIGIBLE` > `UNVERIFIABLE` > `NEED_INFO` > `CONDITIONAL` >
`ELIGIBLE`에서 가장 앞의 값이 결과다. LLM · 네트워크를 부르지 않는다.
"""

from dataclasses import dataclass, field

from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.retrieval import axes

PRIORITY = ("INELIGIBLE", "UNVERIFIABLE", "NEED_INFO", "CONDITIONAL", "ELIGIBLE")
_RANK = {v: i for i, v in enumerate(PRIORITY)}
APPLICABLE = ("ELIGIBLE", "CONDITIONAL")

# 일반공급 판정에 들어가는 축. 특별공급 경로는 여기에 소득·자산 축과 유형 질의를 더한다
GENERAL_AXES = ("homeless", "account", "residence", "rewin", "householder")
INCOME_AXIS = "income_asset"
TYPE_AXIS = "special_type"
GENERAL_KEY = "general"
GENERAL_NAME = "일반공급"

# 유형 질의 문장 → 유형 이름. 못 찾으면 질의 문장을 그대로 경로 키로 쓴다
_TYPE_BY_QUERY = {axes.Q_SPECIAL.format(type=name): name for _, name in axes.SPECIAL_TYPES}
_TYPE_BY_QUERY[axes.Q_SPECIAL_NO_TYPE] = "유형 미상"


@dataclass
class Route:
    """신청 경로 하나의 합친 판정. `key`는 `general` 또는 특별공급 유형 이름이다."""

    key: str
    name: str
    verdict: str | None  # 합칠 판정이 하나도 없으면 None
    axes: list[str] = field(default_factory=list)  # 합친 판정이 나온 축 id
    n: int = 0  # 합친 하위 질의 수


@dataclass
class Aggregate:
    general: Route
    special: list[Route]
    verdict: str | None  # 전역 판정 = 일반공급 판정
    applicable: list[Route]  # ELIGIBLE · CONDITIONAL인 경로


def merge(values) -> str | None:
    """우선순위에서 가장 앞의 값. 비어 있으면 None."""
    best = min((_RANK[x] for x in values), default=None)
    return None if best is None else PRIORITY[best]


def _route(key: str, name: str, items: list[tuple[str, str]]) -> Route:
    return Route(
        key, name, merge(x for _, x in items), list(dict.fromkeys(a for a, _ in items)), len(items)
    )


def aggregate(plans: list[axes.AxisPlan], verdicts: list[vd.Verdict]) -> Aggregate:
    """켜진 축의 판정만 합친다. `verdict=None`(호출 실패)은 `UNVERIFIABLE`로 센다.

    ponytail: 세대주 축이 특별공급 유형 일부(노부모 부양)에만 걸리는 차이는 반영하지 않았다.
    세대주 축은 모든 경로에 들어간다. 유형마다 다르게 걸어야 하면 `GENERAL_AXES`를 경로별로 나눈다.
    """
    on = {p.id for p in plans if p.on}
    general: list[tuple[str, str]] = []
    income: list[tuple[str, str]] = []
    types: dict[str, list[tuple[str, str]]] = {}
    for v in verdicts:
        if v.axis not in on:
            continue
        item = (v.axis, v.verdict or "UNVERIFIABLE")
        if v.axis in GENERAL_AXES:
            general.append(item)
        elif v.axis == INCOME_AXIS:
            income.append(item)
        elif v.axis == TYPE_AXIS:
            types.setdefault(_TYPE_BY_QUERY.get(v.query, v.query), []).append(item)
    base = _route(GENERAL_KEY, GENERAL_NAME, general)
    special = [_route(t, f"특별공급 {t}", general + income + items) for t, items in types.items()]
    return Aggregate(
        base, special, base.verdict, [r for r in (base, *special) if r.verdict in APPLICABLE]
    )
