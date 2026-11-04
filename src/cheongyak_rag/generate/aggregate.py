"""축별 판정을 경로별 판정으로 합치고(B8) 근거 원문이 붙은 응답을 만든다(B9) (#81).

B8은 결정론적 규칙이다: 우선순위 `INELIGIBLE` > `UNVERIFIABLE` > `NEED_INFO` > `CONDITIONAL` >
`ELIGIBLE`에서 가장 앞의 값이 결과다. B9는 `chunks`에서 인용한 조문·FAQ 원문을 읽어 붙인다.
LLM · 네트워크를 부르지 않는다. 응답은 `dataclasses.asdict` 뒤 `json.dumps`가 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag import profile as prof
from cheongyak_rag.retrieval import axes

if TYPE_CHECKING:  # verdict.py가 이 모듈을 부르므로 실행할 때는 읽지 않는다
    from cheongyak_rag.generate import verdict as vd

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


# ── B9 응답 ──────────────────────────────────────────────────────────────

LAW_NAME = "주택공급에 관한 규칙"
FAQ_NAME = "2024 주택청약 FAQ"
# 응답에 링크를 싣는 형식. 실제 요청으로 HTTP 200을 확인한 것만 둔다(`aggregate_report` 징후 4)
LINK_KINDS = ("law", "faq")
FAQ_PDF_URL = "https://www.molit.go.kr/portal/common/download/DownloadMltm2.jsp"
FAQ_PDF_PARAMS = {
    "FilePath": "portal/DextUpload/202405/20240529_165121_948.pdf",
    "FileName": "★ 2024 주택청약 FAQ.pdf",
}
# 이유 문장의 조 번호(`제53조제1항`은 `제53조`)와 FAQ 번호
_MENTION = re.compile(r"제\d+조(?:의\d+)?|(?<![A-Za-z0-9])Q\d+")


@dataclass
class Evidence:
    """인용 하나의 근거. `text`는 `chunks` 행의 원문 그대로다."""

    label: str
    kind: str  # law | faq
    title: str
    text: str
    source: str  # 사람이 읽는 출처 글자
    url: str | None  # 요청해 200을 확인한 형식만 싣는다


@dataclass
class ChecklistItem:
    """하위 질의 하나의 판정. 축 하나에 하위 질의가 여럿일 수 있다."""

    axis: str
    axis_name: str
    query: str
    verdict: str | None  # 호출이 실패했으면 None
    reason: str
    conditions: list[str]
    need_info: list[str]
    citations: list[Evidence]
    outside: list[str]  # 이유가 언급했지만 이 질의의 검색 결과에 없던 조·FAQ 번호
    note: str = ""  # 코드가 판정을 바꿨으면 그 사실
    error: str | None = None


@dataclass
class Answer:
    house_manage_no: str
    pblanc_no: str
    name: str
    as_of: str
    law_mst: str | None
    law_effective_date: str | None
    verdict: str | None  # 전역 판정 = 일반공급 판정
    general: Route
    special: list[Route]
    applicable: list[Route]
    checklist: list[ChecklistItem]
    score: dict  # 가점 범위 {total: {lo, hi}, ..., missing: [...]}
    questions: list = field(default_factory=list)  # 질문 랭킹은 #82


def link_for(kind: str, mst: str | None) -> str | None:
    """출처 링크. 조문은 공고에 적용되는 법령 버전 페이지, FAQ는 PDF 내려받기다."""
    if kind == "law":
        return f"https://www.law.go.kr/lsInfoP.do?lsiSeq={mst}" if mst else None
    return f"{FAQ_PDF_URL}?{urlencode(FAQ_PDF_PARAMS)}"


def outside_mentions(reason: str, context_labels: list[str]) -> list[str]:
    """이유가 언급한 조·FAQ 번호 중 검색 결과(`context_labels`)에 없는 것. 같은 번호는 한 번만."""
    seen = set(context_labels)
    return [m for m in dict.fromkeys(_MENTION.findall(reason or "")) if m not in seen]


def _kind(label: str) -> str:
    return "faq" if label.startswith("Q") else "law"


def read_texts(engine: Engine, mst: str | None, labels: list[str]) -> dict[str, str]:
    """`chunks`에서 라벨 → 원문. 조문은 공고의 MST 행만, FAQ는 `faq` 행을 본다."""
    if not labels:
        return {}
    stmt = sa.text(
        "SELECT label, text FROM chunks WHERE label IN :labels"
        " AND ((source = 'law' AND law_mst = :m) OR source = 'faq')"
    ).bindparams(sa.bindparam("labels", expanding=True))
    with engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(stmt, {"labels": labels, "m": mst})}


def _effective_date(engine: Engine, mst: str | None) -> str | None:
    if mst is None:
        return None
    with engine.connect() as conn:
        d = conn.execute(
            sa.text("SELECT effective_date FROM law_versions WHERE mst = :m LIMIT 1"), {"m": mst}
        ).scalar()
    return d.isoformat() if d else None


def _source(kind: str, label: str, mst: str | None, effective: str | None) -> str:
    if kind == "faq":
        return f"{FAQ_NAME} {label}"
    version = " · ".join(
        x
        for x in (f"법령 MST {mst}" if mst else "", f"시행일 {effective}" if effective else "")
        if x
    )
    return f"{LAW_NAME} {label}" + (f" ({version})" if version else "")


def _note(v: vd.Verdict) -> str:
    if v.forced:
        return f"인용이 모두 기각돼 UNVERIFIABLE로 바뀜 (모델 판정 {v.original_verdict})"
    if v.guarded:
        return f"프로필 값이 없어 NEED_INFO로 바뀜 (모델 판정 {v.original_verdict})"
    return ""


def build_answer(
    engine: Engine,
    notice: vd.NoticeInfo,
    plans: list[axes.AxisPlan],
    verdicts: list[vd.Verdict],
    profile: prof.Profile,
    *,
    link_kinds: tuple[str, ...] = LINK_KINDS,
) -> Answer:
    """공고 하나 × 프로필 하나의 응답. LLM을 부르지 않는다."""
    mst = notice.facts.law_mst
    effective = _effective_date(engine, mst)
    labels = list(dict.fromkeys(c for v in verdicts for c in v.citations))
    texts = read_texts(engine, mst, labels)

    def evidence(v: vd.Verdict, label: str) -> Evidence:
        kind = _kind(label)
        return Evidence(
            label, kind, v.titles.get(label, ""), texts.get(label, ""),
            _source(kind, label, mst, effective),
            link_for(kind, mst) if kind in link_kinds else None,
        )  # fmt: skip

    checklist = [
        ChecklistItem(
            v.axis, v.axis_name, v.query, v.verdict, v.reason, v.conditions, v.need_info,
            [evidence(v, c) for c in v.citations], outside_mentions(v.reason, v.context_labels),
            _note(v), v.error,
        )
        for v in verdicts
    ]  # fmt: skip
    agg = aggregate(plans, verdicts)
    scores = prof.score(profile, notice.as_of).to_dict()
    return Answer(
        notice.house_manage_no, notice.pblanc_no, notice.name, notice.as_of.isoformat(), mst,
        effective, agg.verdict, agg.general, agg.special, agg.applicable, checklist,
        {**scores["scores"], "missing": scores["missing"]},
    )  # fmt: skip


# ── 텍스트 ───────────────────────────────────────────────────────────────

TEXT_CHARS = 240  # 사람이 읽는 출력에서 근거 원문을 자르는 길이. 응답 데이터에는 전문이 있다


def _route_line(r: Route) -> str:
    return f"{r.name}: {r.verdict or '판정할 축 없음'}"


def _score_line(score: dict) -> str:
    def rng(x):
        return f"{x['lo']}점" if x["lo"] == x["hi"] else f"{x['lo']}~{x['hi']}점"

    parts = f"무주택기간 {rng(score['homeless'])} · 부양가족 {rng(score['dependents'])}"
    parts += f" · 통장 {rng(score['savings'])}"
    miss = f" · 모르는 칸 {', '.join(score['missing'])}" if score["missing"] else ""
    return f"가점: {rng(score['total'])} ({parts}){miss}"


def _item_lines(i: ChecklistItem, full_text: bool) -> list[str]:
    out = [f"질의: {i.query}"]
    if i.error:
        return out + [f"  판정 실패: {i.error}"]
    out.append(f"  판정: {i.verdict}" + (f" — {i.note}" if i.note else ""))
    if i.reason:
        out.append(f"  이유: {i.reason}")
    out += [f"  조건: {x}" for x in i.conditions]
    out += [f"  필요한 정보: {x}" for x in i.need_info]
    if i.outside:
        out.append(f"  검색 밖 언급: {', '.join(i.outside)} (이 질의의 검색 결과에 없던 번호다)")
    for e in i.citations:
        title = f" {e.title}" if e.title else ""
        out.append(f"  근거 {e.label}{title} — {e.source}" + (f" {e.url}" if e.url else ""))
        body = " ".join(e.text.split())
        out.append(
            f"    {body if full_text or len(body) <= TEXT_CHARS else body[:TEXT_CHARS] + '…'}"
        )
    if not i.citations:
        out.append("  근거: 없음")
    return out


def render_text(a: Answer, *, full_text: bool = False) -> str:
    """사람이 읽는 응답. 맨 위가 전역 판정 · 경로별 판정 · 신청 가능한 경로다."""
    out = [
        f"전역 판정(일반공급): {a.verdict or '판정할 축 없음'}",
        *[f"특별공급 유형별: {_route_line(r)}" for r in a.special],
        "신청 가능한 경로: " + (" · ".join(r.name for r in a.applicable) or "없음"),
        _score_line(a.score),
        f"공고: {a.name} · 공고일 {a.as_of} · {LAW_NAME} MST {a.law_mst or '없음'}"
        f" · 시행일 {a.law_effective_date or '모름'}",
        "",
        "체크리스트",
    ]
    axis = None
    for i in a.checklist:
        if i.axis != axis:
            axis = i.axis
            out += ["", f"## {i.axis_name}"]
        out += _item_lines(i, full_text)
    out += ["", "확인할 질문: " + ("없음" if not a.questions else f"{len(a.questions)}개")]
    return "\n".join(out)
