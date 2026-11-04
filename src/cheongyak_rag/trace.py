"""질의 한 건을 `traces` 행 하나로 남긴다 (#83).

질의 = 공고 하나 × 프로필 하나를 B9 응답까지 돌리는 한 번. `run_traced`가 `verdict.judge` →
`aggregate.build_answer` → 행 쓰기를 묶는다. 프로필 원본은 저장하지 않는다 — 같은 프로필을 묶는
해시(HMAC)만 남기고, 이유 문장에 프로필 날짜가 그대로 적혔으면 저장할 때 `[프로필 값]`으로 가린다.
반환하는 응답은 가리지 않는다.
"""

import dataclasses
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag import profile as prof
from cheongyak_rag.generate import aggregate
from cheongyak_rag.generate import verdict as vd
from cheongyak_rag.generate.verdict_report import system_sha
from cheongyak_rag.retrieval import axes

MASK = "[프로필 값]"
OK, ERROR = "ok", "error"


class MissingKey(ValueError):
    """`TRACE_HASH_KEY`가 비어 있다. 흐름을 돌리기 전에 멈춘다."""


@dataclass
class Traced:
    notice: vd.NoticeInfo
    plans: list[axes.AxisPlan]
    verdicts: list[vd.Verdict]
    answer: aggregate.Answer
    trace_id: int | None  # 행 쓰기가 실패하면 None
    trace_error: str | None = None  # 행 쓰기가 실패한 이유


def profile_hash(profile: prof.Profile, key: str) -> str:
    """HMAC-SHA256 16진수 64자. 입력은 `Profile.to_dict()`를 키 정렬한 JSON이다."""
    if not key:
        raise MissingKey("TRACE_HASH_KEY가 없다")
    body = json.dumps(profile.to_dict(), sort_keys=True)
    return hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def mask(obj, profile: prof.Profile):
    """dict · list · 글자를 따라 내려가며 프로필의 글자 값을 `[프로필 값]`으로 바꾼다.

    ponytail: 프로필 값이 글자 그대로 나온 것만 가린다. 다른 꼴(`2012년 5월 20일`)은 못 잡는다.
    """
    secrets = sorted(
        {v for v in profile.to_dict().values() if isinstance(v, str) and v}, key=len, reverse=True
    )

    def walk(x):
        if isinstance(x, str):
            for s in secrets:
                x = x.replace(s, MASK)
            return x
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [walk(v) for v in x]
        return x

    return walk(obj)


def steps(notice: vd.NoticeInfo, plans: list[axes.AxisPlan], verdicts: list[vd.Verdict]) -> dict:
    """흐름 기록: 공고일 · 법령 버전 · 축 켜고 끈 이유(B3·B4) · 하위 질의마다 검색~판정(B5~B7)."""
    fresh = [v for v in verdicts if not v.cached and not v.no_context]
    return {
        "as_of": notice.as_of.isoformat(),
        "law_mst": notice.facts.law_mst,
        "axes": [{"id": p.id, "name": p.name, "on": p.on, "reason": p.reason} for p in plans],
        "queries": [
            {
                "axis": v.axis,
                "query": v.query,
                "context_labels": v.context_labels,
                "model_verdict": v.original_verdict or v.verdict,
                "verdict": v.verdict,
                "forced": v.forced,
                "guarded": v.guarded,
                "invalid_citations": v.invalid_citations,
                "input_tokens": v.input_tokens,
                "output_tokens": v.output_tokens,
                "usd": v.usd,
                "cached": v.cached,
                "no_context": v.no_context,
                "error": v.error,
            }
            for v in verdicts
        ],
        "total": {
            "llm_calls": len(fresh),
            "input_tokens": sum(v.input_tokens for v in fresh),
            "output_tokens": sum(v.output_tokens for v in fresh),
            "usd": sum(v.usd for v in fresh),
        },
    }


_INSERT = sa.text(
    "INSERT INTO traces (house_manage_no, pblanc_no, profile_hash, status, error, verdict, model,"
    " system_sha, seconds, steps, answer) VALUES (:house_manage_no, :pblanc_no, :profile_hash,"
    " :status, :error, :verdict, :model, :system_sha, :seconds, CAST(:steps AS jsonb),"
    " CAST(:answer AS jsonb)) RETURNING id"
)


def write(engine: Engine, row: dict) -> int:
    """`traces`에 행 하나를 쓰고 id를 돌려준다. `steps`·`answer`는 dict 그대로 받는다."""
    params = {
        **row,
        "steps": json.dumps(row["steps"], ensure_ascii=False),
        "answer": None if row["answer"] is None else json.dumps(row["answer"], ensure_ascii=False),
    }
    with engine.begin() as conn:
        return conn.execute(_INSERT, params).scalar_one()


def run_traced(
    engine: Engine,
    embedder,
    client,
    model: str,
    house_manage_no: str,
    profile: prof.Profile,
    pblanc_no: str | None = None,
    cache=None,
    *,
    key: str,
    **judge_kw,
) -> Traced:
    """`verdict.judge` → `aggregate.build_answer` → 행 쓰기.

    흐름 중간에 예외가 나면 `status='error'` 행을 쓰고 그 예외를 다시 올린다. 행 쓰기만 실패하면
    응답은 그대로 돌려주고 실패 이유를 `trace_error`에 담는다.
    """
    digest = profile_hash(profile, key)  # 키가 없으면 흐름을 돌리기 전에 멈춘다
    base = {
        "house_manage_no": house_manage_no,
        "profile_hash": digest,
        "model": model,
        "system_sha": system_sha(),
    }
    t0 = time.perf_counter()
    try:
        notice, plans, verdicts = vd.judge(
            engine, embedder, client, model, house_manage_no, profile, pblanc_no, cache, **judge_kw
        )
        answer = aggregate.build_answer(engine, notice, plans, verdicts, profile)
    except Exception as e:
        row = base | {
            "pblanc_no": pblanc_no,
            "status": ERROR,
            "error": mask(f"{type(e).__name__}: {e}", profile),
            "verdict": None,
            "seconds": time.perf_counter() - t0,
            "steps": {},
            "answer": None,
        }
        try:
            write(engine, row)
        except SQLAlchemyError as we:
            e.add_note(f"trace 행도 못 썼다: {type(we).__name__}")
        raise
    row = base | {
        "pblanc_no": notice.pblanc_no,
        "status": OK,
        "error": None,
        "verdict": answer.verdict,
        "seconds": time.perf_counter() - t0,
        "steps": mask(steps(notice, plans, verdicts), profile),
        "answer": mask(dataclasses.asdict(answer), profile),
    }
    try:
        trace_id, trace_error = write(engine, row), None
    except SQLAlchemyError as e:
        trace_id, trace_error = None, f"{type(e).__name__}: {getattr(e, 'orig', e)}"
    return Traced(notice, plans, verdicts, answer, trace_id, trace_error)
