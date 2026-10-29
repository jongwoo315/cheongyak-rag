"""공고 하나와 프로필 하나로 켜진 축의 하위 질의마다 판정을 낸다 (#80).

python -m cheongyak_rag.generate.verdict <house_manage_no> --profile runs/80/profiles/full.json

#79 `axes`가 켠 축마다 조문·FAQ를 찾고(B5), 판정 LLM이 요건 정의 + 프로필 값 + 근거로 판정값 5개 중
하나를 낸다(B6). 코드 guardrail(B7)이 근거 0개 · 문맥에 없는 인용 · `chunks`에 없는 인용 ·
남은 인용이 0개인 판정을 걸러낸다. 꺼진 축은 LLM을 부르지 않는다. 응답은 #139의 `GenCache`에 둔다.
"""

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag import profile as prof
from cheongyak_rag.config import settings
from cheongyak_rag.generate.answer import (
    MAX_COMPLETION_TOKENS,
    GenCache,
    HardApiError,
    _label,
    check_model,
    cost_usd,
    make_client,
)
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.chunk import Chunk
from cheongyak_rag.retrieval.embed import CACHE_DIR, Embedder

VERDICTS = ("ELIGIBLE", "INELIGIBLE", "CONDITIONAL", "NEED_INFO", "UNVERIFIABLE")
TITLE_CHARS = 40

# 축 7개의 요건 정의. 기대 조(`axes.AXES`)의 제목을 보고 썼다
AXIS_DEFS = {
    "homeless": (
        "신청자가 속한 세대의 구성원 전원이 주택을 소유하지 않았는지(무주택세대구성원)와"
        " 무주택 기간을 본다."
        " 주택 소유 여부는 제53조로 판정한다. 무주택 기간은 프로필 계산 결과를 쓴다."
    ),
    "account": (
        "청약통장(주택청약종합저축)의 가입 기간 · 예치금 · 납입 조건이"
        " 공고의 주택형과 지역 요건을 채우는지 본다."
        " 제9조 · 제10조(가입 및 납입조건)와 제27조 · 제28조(1순위 요건)를 본다."
    ),
    "residence": (
        "공고의 공급지역에 거주하는지와 거주 기간이 요건을 채우는지 본다."
        " 제4조(주택의 공급대상)와 제34조(해당 지역 거주자 우선공급)를 본다."
    ),
    "income_asset": (
        "특별공급의 소득 기준과 자산 기준을 채우는지 본다."
        " 제35조 · 제41조 · 제43조 · 제46조가 유형별 소득 · 자산 기준을 정한다."
    ),
    "rewin": (
        "투기과열지구 · 청약과열지역 · 분양가상한제 주택에 당첨된 적이 있어"
        " 재당첨이 제한되는지 본다."
        " 제54조가 제한 대상 주택과 제한 기간을 정한다."
    ),
    "householder": (
        "세대주 요건을 채우는지 본다. 투기과열지구 · 청약과열지역의 1순위(제28조)와"
        " 노부모 부양 특별공급(제46조)은 세대주만 신청할 수 있다. 제2조의 정의도 본다."
    ),
    "special_type": (
        "하위 질의에 적힌 특별공급 유형의 신청 자격을 채우는지 본다."
        " 제35조부터 제47조까지가 유형별 자격을 정한다. 한 번에 유형 하나만 판정한다."
    ),
}

_AXIS_LINES = "\n".join(f"- {a.name}({a.id}): {AXIS_DEFS[a.id]}" for a in axes.AXES)

SYSTEM = f"""\
너는 「주택공급에 관한 규칙」으로 청약 신청 자격을 판정하는 도우미다. 사용자 메시지에 축 하나의 \
하위 질의, 공고 값, 신청자 프로필, 문맥(규칙 조문과 국토교통부 FAQ)이 있다. \
하위 질의 하나에 판정 하나를 낸다. \
문맥에 있는 내용과 프로필 값으로만 판정하고, 문맥에 없는 지식은 쓰지 않는다.

판정값 5개:
- ELIGIBLE: 프로필에 있는 값이 요건을 채운다고 문맥으로 확인된다. 요건에 어긋나는 값이 \
없다는 것만으로는 ELIGIBLE이 아니다.
- INELIGIBLE: 프로필 값이 요건을 못 채운다고 문맥으로 확인된다. `reason`에 이유를 쓴다.
- CONDITIONAL: 지금은 요건을 못 채우지만 공고 이후에 신청자가 행동하면 \
(전입, 통장 가입, 세대주 변경 등) 채운다. 필요한 행동을 `conditions`에 문장으로 쓴다.
- NEED_INFO: 요건을 채우는지 가릴 값이 프로필에 없어서 \
채운다고도 못 채운다고도 할 수 없다. 그 정보만 있으면 지금 시점의 판정이 정해진다. \
무엇을 물어야 하는지 `need_info`에 문장으로 쓴다.
- UNVERIFIABLE: 문맥에서 이 요건의 근거를 찾지 못했거나 문맥의 규정끼리 부딪힌다. \
`reason`에 이유를 쓴다.
CONDITIONAL과 NEED_INFO는 이렇게 가른다. 정보를 더 받으면 판정이 정해지면 NEED_INFO이고, \
정보가 다 있어도 신청자가 행동해야 채우면 CONDITIONAL이다.

판정 절차:
1. 문맥에서 요건을 찾고, 그 요건을 신청자가 채우는지 가릴 때 필요한 프로필 칸을 정한다.
2. 필요한 칸의 값이 null이거나 `missing`에 있으면 모르는 값이다. 프로필에 그 칸 자체가 없어도 \
모르는 값이다. 모르는 값이 하나라도 필요하면 NEED_INFO이다.
3. 필요한 칸이 전부 값이 있을 때만 ELIGIBLE이나 INELIGIBLE을 쓴다. 요건의 내용을 설명하는 것이나 \
공고의 규제 표시만으로는 신청자가 요건을 채운다는 판정이 되지 않는다.
4. 프로필에 대응하는 칸이 없는 정보는 거주지역 · 거주기간, 소득 · 자산, 재당첨 이력, \
특별공급 유형별 자격이다. 이 정보가 필요하면 프로필이 꽉 차 있어도 NEED_INFO이다. \
가점용 칸(미혼 자녀 수, 직계존속 수 등)으로 대신 대조하지 않는다.
예: 재당첨 제한 대상 주택인지는 공고로 알 수 있다. 신청자가 제한 기간 안에 당첨된 적이 있는지는 \
프로필에 없으므로 NEED_INFO이다. 거주 기간 요건도 신청자의 거주 지역 · 기간이 프로필에 없으므로 \
NEED_INFO이다.

규칙:
- `citations`에 판정의 근거로 쓴 문맥 라벨을 `제34조` `Q47` 꼴로 적는다. 문맥에 있는 라벨만 쓴다.
- UNVERIFIABLE이 아닌 판정은 NEED_INFO를 포함해 `citations`가 1개 이상이어야 한다. \
NEED_INFO는 그 정보를 요구하는 규정을 인용한다.
- `reason`은 모든 판정에 한 문장으로 쓴다. ELIGIBLE · INELIGIBLE은 어느 프로필 칸의 값을 \
어느 요건과 대조했는지 적는다.
- 프로필 계산 결과(무주택 기간, 통장 가입 기간, 가점)는 공고일 기준으로 이미 계산한 값이다. \
다시 계산하지 않는다.
- 쓰지 않는 `conditions` · `need_info`는 빈 배열로 둔다.

축 7개의 요건:
{_AXIS_LINES}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "need_info": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "reason", "conditions", "need_info", "citations"],
    "additionalProperties": False,
}


@dataclass
class Verdict:
    axis: str
    axis_name: str
    query: str
    verdict: str | None = None  # 호출이 실패했으면 None
    reason: str = ""
    conditions: list[str] = field(default_factory=list)
    need_info: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # 두 단계 대조를 통과한 라벨
    invalid_citations: list[str] = field(default_factory=list)
    titles: dict[str, str] = field(default_factory=dict)  # 인용한 라벨 → 조 제목 · FAQ 질문
    forced: bool = False  # 인용이 모두 기각돼 코드가 UNVERIFIABLE로 바꿨다
    original_verdict: str | None = None  # forced일 때 모델이 낸 판정
    no_context: bool = False  # 근거가 0개라 호출하지 않았다
    context_labels: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None


@dataclass(frozen=True)
class NoticeInfo:
    house_manage_no: str
    pblanc_no: str
    name: str
    as_of: date  # 공고일
    facts: axes.Facts


def cache_path_for(model: str) -> Path:
    return CACHE_DIR / f"verdict-{model}.jsonl"


def cache_key(model: str, messages: list[dict]) -> str:
    raw = f"{model}\n{messages[0]['content']}\n{messages[1]['content']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── 메시지 ───────────────────────────────────────────────────────────────


def profile_payload(profile: prof.Profile, score: prof.ProfileScore) -> dict:
    """프로필 원본과 공고일 기준 계산 결과. 무주택 · 통장 기간은 #77이 날짜 계산을 끝낸 값이다."""
    d = score.to_dict()
    return {
        "profile": profile.to_dict(),
        "score": {k: d[k] for k in ("as_of", "values", "scores", "missing")},
    }


def _notice_lines(n: NoticeInfo) -> list[str]:
    names = dict(axes.REGULATION_FLAGS)
    flags = " · ".join(f"{names[c]} {'참' if v else '거짓'}" for c, v in n.facts.flags.items())
    types = " · ".join(
        f"{name} {n.facts.by_type[key]}" for key, name in axes.SPECIAL_TYPES if n.facts.by_type[key]
    )
    return [
        f"- 공고명: {n.name}",
        f"- 공고일: {n.as_of.isoformat()}",
        f"- 공급지역: {n.facts.area or '모름'}",
        f"- 규제 표시: {flags}",
        f"- 특별공급 세대수 합: {n.facts.special}" + (f" ({types})" if types else ""),
    ]


def build_messages(axis, hits: axes.QueryHits, notice: NoticeInfo, payload: dict) -> list[dict]:
    """[system, user]. 순서는 고정이다: 축 · 하위 질의 → 공고 → 프로필 → 문맥(조 → FAQ)."""
    blocks = [f"[{c.label}] {c.text}" for c in hits.law + hits.faq]
    user = "\n".join(
        [
            f"축: {axis.name} ({axis.id})",
            f"하위 질의: {hits.query}",
            "",
            "공고:",
            *_notice_lines(notice),
            "",
            "프로필:",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "",
            "문맥:",
            "",
            "\n\n".join(blocks),
        ]
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# ── 응답 · guardrail ─────────────────────────────────────────────────────


def _parse(content: str | None) -> dict:
    """응답 content를 schema 꼴로. 어긋나면 ValueError."""
    if not content:
        raise ValueError("빈 응답")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}") from e

    def strings(key):
        return isinstance(data.get(key), list) and all(isinstance(x, str) for x in data[key])

    ok = (
        isinstance(data, dict)
        and data.get("verdict") in VERDICTS
        and isinstance(data.get("reason"), str)
        and strings("conditions")
        and strings("need_info")
        and strings("citations")
    )
    if not ok:
        raise ValueError(f"스키마 위반: {content[:120]}")
    return data


def _title(c: Chunk) -> str:
    head = c.meta.get("title") or c.text.partition("\n")[0]
    return " ".join(head.split())[:TITLE_CHARS]


def present_in_chunks(engine: Engine, mst: str | None, chunks: list[Chunk]) -> set[str]:
    """`chunks`에서 다시 조회해 있는 라벨. 조문은 공고의 MST 행만, FAQ는 `faq` 행을 본다."""
    found: set[str] = set()
    for source, group in (("law", [c for c in chunks if c.source == "law"]),
                          ("faq", [c for c in chunks if c.source == "faq"])):  # fmt: skip
        if not group or (source == "law" and mst is None):
            continue
        sql = "SELECT label FROM chunks WHERE source = :s AND label IN :labels"
        params = {"s": source, "labels": [c.label for c in group]}
        if source == "law":
            sql += " AND law_mst = :m"
            params["m"] = mst
        stmt = sa.text(sql).bindparams(sa.bindparam("labels", expanding=True))
        with engine.connect() as conn:
            found |= {r[0] for r in conn.execute(stmt, params)}
    return found


def _call(client, model: str, messages: list[dict]) -> dict:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "verdict", "strict": True, "schema": SCHEMA},
        },
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )
    return {
        "content": resp.choices[0].message.content,
        "input_tokens": resp.usage.prompt_tokens,
        "output_tokens": resp.usage.completion_tokens,
        # 재시도 대기를 뺀 마지막 시도의 시간. 감싼 클라이언트가 없으면 전체 시간
        "latency_s": round(getattr(client, "last_attempt_s", None) or time.perf_counter() - t0, 3),
    }


def judge_one(
    axis,
    hits: axes.QueryHits,
    notice: NoticeInfo,
    payload: dict,
    client,
    model: str,
    cache,
    engine: Engine,
) -> Verdict:
    """하위 질의 하나의 판정. API 예외는 `error`에 남기고 `HardApiError`만 위로 올린다."""
    context = hits.law + hits.faq
    out = Verdict(axis.id, axis.name, hits.query, context_labels=[c.label for c in context])
    if not context:  # 근거가 없으면 묻지 않는다
        out.verdict, out.no_context = "UNVERIFIABLE", True
        out.reason = "검색된 조문·FAQ가 없어 판정할 근거가 없다"
        return out
    messages = build_messages(axis, hits, notice, payload)
    key = cache_key(model, messages)
    value = cache.get(key) if cache is not None else None
    data = None
    if value is not None:
        try:
            data = _parse(value["content"])
            out.cached = True
        except ValueError:
            value = None  # 스키마를 고친 뒤 못 읽게 된 옛 응답은 다시 부른다
    if value is None:
        try:
            value = _call(client, model, messages)
        except HardApiError:
            raise
        except Exception as e:  # noqa: BLE001 — 하위 질의 하나의 실패로 일괄 실행을 멈추지 않는다
            out.error = f"{type(e).__name__}: {e}"
            return out
    out.input_tokens, out.output_tokens = value["input_tokens"], value["output_tokens"]
    out.usd = cost_usd(model, out.input_tokens, out.output_tokens)
    out.latency_s = value["latency_s"]
    if data is None:
        try:
            data = _parse(value["content"])
        except ValueError as e:
            out.error = str(e)
            return out
        if cache is not None:
            cache.put(
                key, value
            )  # 읽히는 응답만 둔다 — 잘린 응답이 굳어 다시 안 불리는 것을 막는다
    out.verdict, out.reason = data["verdict"], data["reason"]
    out.conditions, out.need_info = data["conditions"], data["need_info"]

    by_label = {c.label: c for c in context}
    cites = list(dict.fromkeys(_label(c) for c in data["citations"]))
    in_context = [c for c in cites if c in by_label]
    real = present_in_chunks(engine, notice.facts.law_mst, [by_label[c] for c in in_context])
    out.citations = [c for c in in_context if c in real]
    out.invalid_citations = [c for c in cites if c not in out.citations]
    out.titles = {c: _title(by_label[c]) for c in cites if c in by_label}
    if out.verdict != "UNVERIFIABLE" and not out.citations:
        out.original_verdict, out.verdict, out.forced = out.verdict, "UNVERIFIABLE", True
    return out


# ── 공고 하나 ────────────────────────────────────────────────────────────


def _notice_date(engine: Engine, house_manage_no: str, pblanc_no: str) -> date:
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT rcrit_pblanc_de FROM notices WHERE house_manage_no = :h AND pblanc_no = :p"
            ),
            {"h": house_manage_no, "p": pblanc_no},
        ).first()
    if row is None or row[0] is None:
        raise axes.NoticeNotFound(f"공고 {house_manage_no}:{pblanc_no}의 공고일이 없다")
    return row[0]


def judge(
    engine: Engine,
    embedder,
    client,
    model: str,
    house_manage_no: str,
    profile: prof.Profile,
    pblanc_no: str | None = None,
    cache=None,
    *,
    k: int = 5,
    faq_k: int = 3,
    search_cache: axes.Cache | None = None,
) -> tuple[NoticeInfo, list[axes.AxisPlan], list[Verdict]]:
    """공고 하나 × 프로필 하나 → (공고 정보, 축 7개 계획, 켜진 하위 질의마다 판정).

    공고가 없으면 `NoticeNotFound`, 프로필이 모순이면 `ProfileError`를 그대로 올린다.
    """
    pblanc_no, name, facts = axes.load_facts(engine, house_manage_no, pblanc_no)
    notice = NoticeInfo(
        house_manage_no, pblanc_no, name, _notice_date(engine, house_manage_no, pblanc_no), facts
    )
    payload = profile_payload(profile, prof.score(profile, notice.as_of))
    plans = axes.plan_from_facts(facts)
    results = axes.search(
        engine,
        embedder,
        house_manage_no,
        pblanc_no,
        k=k,
        faq_k=faq_k,
        plans=[p for p in plans if p.on],
        cache=search_cache,
    )  # fmt: skip  — 꺼진 축은 search에 넘기지 않는다
    by_id = {p.id: p for p in plans}
    verdicts = [
        judge_one(by_id[r.id], h, notice, payload, client, model, cache, engine)
        for r in results
        for h in r.hits
    ]
    return notice, plans, verdicts


# ── CLI ──────────────────────────────────────────────────────────────────


def format_verdict(v: Verdict) -> str:
    head = f"질의: {v.query}"
    if v.error:
        return f"{head}\n판정 실패: {v.error}"
    flags = []
    if v.cached:
        flags.append("캐시")
    if v.no_context:
        flags.append("근거 0개라 호출 안 함")
    if v.forced:
        flags.append(f"인용이 모두 기각돼 코드가 바꿈 — 모델 판정 {v.original_verdict}")
    out = [head, f"판정: {v.verdict}" + (f" ({', '.join(flags)})" if flags else "")]
    if v.reason:
        out.append(f"이유: {v.reason}")
    out += [f"조건: {x}" for x in v.conditions]
    out += [f"필요한 정보: {x}" for x in v.need_info]
    cites = " · ".join(f"{c}({v.titles[c]})" if c in v.titles else c for c in v.citations)
    out.append(f"인용: {cites or '없음'}")
    if v.invalid_citations:
        out.append("기각된 인용: " + ", ".join(v.invalid_citations))
    return "\n".join(out)


def format_report(notice: NoticeInfo, plans: list[axes.AxisPlan], verdicts: list[Verdict]) -> str:
    out = [
        f"공고: {notice.name} · 법령 버전(MST) {notice.facts.law_mst or '없음'}"
        f" · 공고일 {notice.as_of.isoformat()}",
        "",
        "축",
        *[f"- {p.line}" for p in plans],
    ]
    for p in plans:
        if p.on:
            out += ["", f"## {p.name}"]
            out += [format_verdict(v) for v in verdicts if v.axis == p.id]
    # 캐시에서 읽은 판정은 돈이 안 든다. 호출한 판정(실패 포함)만 토큰과 비용을 센다
    fresh = [v for v in verdicts if not v.cached and not v.no_context]
    out += [
        "",
        f"판정 {len(verdicts)}개 · 호출 {len(fresh)} · 캐시 {sum(v.cached for v in verdicts)}"
        f" · 토큰 입력 {sum(v.input_tokens for v in fresh):,}"
        f" 출력 {sum(v.output_tokens for v in fresh):,}"
        f" · ${sum(v.usd for v in fresh):.4f}",
    ]
    return "\n".join(out)


def load_profile(path: str) -> prof.Profile:
    return prof.Profile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    embedder=None,
    client=None,
    cache_path: Path | None = None,
) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.generate.verdict")
    ap.add_argument("house_manage_no")
    ap.add_argument("--profile", required=True, help="프로필 JSON (#77 칸)")
    ap.add_argument("--pblanc-no", help="공고번호. 생략하면 그 관리번호의 첫 공고")
    ap.add_argument("--model", default=settings.openai_gen_model)
    args = ap.parse_args(argv)
    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError) as e:  # ProfileError · JSONDecodeError는 ValueError다
        print(f"프로필을 못 읽었다: {e}", file=sys.stderr)
        return 2
    try:
        check_model(args.model)
        client = RetryingClient(client or make_client())
    except HardApiError as e:
        print(e, file=sys.stderr)
        return 1
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        notice, plans, verdicts = judge(
            engine,
            embedder or Embedder(settings.openai_embed_model),
            client,
            args.model,
            args.house_manage_no,
            profile,
            args.pblanc_no,
            GenCache(cache_path or cache_path_for(args.model)),
        )
        print(format_report(notice, plans, verdicts))
        return 1 if any(v.error for v in verdicts) else 0
    except (axes.NoticeNotFound, prof.ProfileError) as e:
        print(e, file=sys.stderr)
        return 2
    except HardApiError as e:
        print(f"멈춤: {e}", file=sys.stderr)
        return 1
    except SQLAlchemyError as e:
        print(f"DB 오류: {type(e).__name__}: {getattr(e, 'orig', e)}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
