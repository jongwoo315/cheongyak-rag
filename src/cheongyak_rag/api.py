"""화면이 부르는 HTTP API (#84). 공고 조회 둘과 판정 하나.

Next.js는 이 API만 부른다. 판정은 CLI와 같은 `trace.run_traced`를 부른다.
"""

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cheongyak_rag import profile as prof
from cheongyak_rag import trace
from cheongyak_rag.config import settings
from cheongyak_rag.generate.answer import GenCache, HardApiError, check_model, make_client
from cheongyak_rag.generate.evaluate import RetryingClient
from cheongyak_rag.generate.verdict import _notice_date, cache_path_for
from cheongyak_rag.retrieval import axes
from cheongyak_rag.retrieval.embed import Embedder

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

# 임베더·클라이언트·캐시는 CLI처럼 한 스레드를 전제로 만들어졌다
# (지연 시간 기록, 캐시 파일 이어 쓰기).
# ponytail: 판정을 한 번에 하나씩 돌린다. 동시 판정이 필요하면 구성 요소마다 잠금을 건다.
# 서버리스 인스턴스 사이에는 이 잠금이 안 걸린다(캐시 파일이 인스턴스마다 따로라 문제는 없다)
_LOCK = threading.Lock()
NO_DETAIL = "판정 서비스를 지금 쓸 수 없다"
ITEM_FAILED = "이 질의의 판정에 실패했다"
BUSY = "다른 판정이 진행 중이다. 잠시 뒤 다시 시도해 달라"


@lru_cache
def get_engine() -> Engine:
    """동기 `Engine` 하나. 테스트는 `app.dependency_overrides`로 갈아 끼운다."""
    return sa.create_engine(settings.database_url, pool_pre_ping=True)


EngineDep = Annotated[Engine, Depends(get_engine)]

# Asia/Seoul = UTC+9, 서머타임 없음. 고정 오프셋이라 서버리스 이미지에 tz 데이터가 없어도 된다
KST = timezone(timedelta(hours=9))
_BUMP = (
    "INSERT INTO verdict_daily_count (day, count) VALUES (:d, 1)"
    " ON CONFLICT (day) DO UPDATE SET count = verdict_daily_count.count + 1 RETURNING count"
)


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


_GIVE_BACK = "UPDATE verdict_daily_count SET count = greatest(count - 1, 0) WHERE day = :d"


def _give_back_one(engine: Engine) -> None:
    """판정을 못 받고 끝난 질의(잠금 대기 초과)는 한도에서 되돌린다."""
    with engine.begin() as conn:
        conn.execute(sa.text(_GIVE_BACK), {"d": today_kst()})


def _take_one_of_todays_limit(engine: Engine) -> None:
    """오늘 판정 수를 1 올리고 한도를 넘었으면 429. 행 쓰기 한 번이라 인스턴스가 여럿이어도 맞다."""
    limit = settings.verdict_daily_limit
    with engine.begin() as conn:
        used = conn.execute(sa.text(_BUMP), {"d": today_kst()}).scalar_one()
    if used > limit:
        raise HTTPException(429, f"오늘 판정 한도({limit}건)를 다 썼다. 내일 다시 시도해 달라")


_LIST = (
    "SELECT house_manage_no, pblanc_no, house_nm, subscrpt_area_nm, rcrit_pblanc_de,"
    " rcept_bgnde, rcept_endde FROM notices"
)
_DETAIL = (
    "SELECT house_manage_no, pblanc_no, house_nm, house_secd, subscrpt_area_nm, hssply_adres,"
    " tot_suply_hshldco, rcrit_pblanc_de, rcept_bgnde, rcept_endde, przwner_presnatn_de,"
    " mvn_prearnge_ym, pblanc_url FROM notices WHERE house_manage_no = :h"
    " ORDER BY pblanc_no LIMIT 1"
)
_MODELS = (
    "SELECT model_no, house_ty, suply_ar, suply_hshldco, spsply_hshldco, lttot_top_amount"
    " FROM notice_models WHERE house_manage_no = :h AND pblanc_no = :p ORDER BY model_no"
)


def _plain(row: dict) -> dict:
    """날짜는 ISO 글자, 숫자(Decimal)는 float로 JSON에 실을 수 있게 바꾼다."""
    return {
        k: v.isoformat() if hasattr(v, "isoformat") else float(v) if hasattr(v, "as_tuple") else v
        for k, v in row.items()
    }


@router.get("/notices")
def list_notices(engine: EngineDep) -> list[dict]:
    """공고 요약. 모집공고일이 늦은 순이다."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(f"{_LIST} ORDER BY rcrit_pblanc_de DESC NULLS LAST, house_manage_no")
        ).mappings()
        return [_plain(dict(r)) for r in rows]


@router.get("/notices/{house_manage_no}")
def get_notice(house_manage_no: str, engine: EngineDep) -> dict:
    with engine.connect() as conn:
        row = conn.execute(sa.text(_DETAIL), {"h": house_manage_no}).mappings().first()
        if row is None:
            raise HTTPException(404, f"공고 {house_manage_no} 없음")
        notice = _plain(dict(row))
        models = conn.execute(
            sa.text(_MODELS), {"h": house_manage_no, "p": notice["pblanc_no"]}
        ).mappings()
        notice["models"] = [_plain(dict(m)) for m in models]
    return notice


@dataclass
class VerdictDeps:
    embedder: Any
    client: Any
    cache: GenCache
    model: str
    key: str  # trace 해시 키. 비어 있으면 판정 요청은 흐름 전에 503이다


@lru_cache
def get_verdict_deps() -> VerdictDeps:
    """`verdict.main`과 같은 임베더·클라이언트·캐시를 처음 요청 때 한 번 만든다."""
    model = settings.openai_gen_model
    with _LOCK:
        try:
            check_model(model)
            client = RetryingClient(make_client())
        except HardApiError as e:
            log.error("판정 준비 실패: %s", e)  # 키·결제 정보가 섞일 수 있어 브라우저에는 안 보낸다
            raise HTTPException(503, NO_DETAIL) from e
        return VerdictDeps(
            Embedder(settings.openai_embed_model),
            client,
            GenCache(cache_path_for(model)),
            model,
            settings.trace_hash_key,
        )


@router.post("/notices/{house_manage_no}/verdict")
def verdict(
    house_manage_no: str,
    engine: EngineDep,
    deps: Annotated[VerdictDeps, Depends(get_verdict_deps)],
    body: Annotated[dict, Body()],
) -> dict:
    """본문 = 프로필 JSON(#77 칸). 응답 = `Answer` + `trace_id` · `trace_error`.

    동기 함수라 FastAPI 스레드풀에서 돈다 — `run_traced`가 동기 `Engine`을 쓴다.
    """
    if not deps.key.strip():  # 행 없이 응답만 내면 기록이 조용히 빠진다 — 흐름 전에 멈춘다
        raise HTTPException(503, "TRACE_HASH_KEY가 없다")
    try:
        profile = prof.Profile.from_dict(body)
        # 없는 공고와 모순된 프로필은 trace 행을 만들기 전에 404·422로 멈춘다
        pblanc_no, _, _ = axes.load_facts(engine, house_manage_no)
        prof.score(profile, _notice_date(engine, house_manage_no, pblanc_no))
        _take_one_of_todays_limit(engine)  # 404·422 뒤, 흐름 전
        # 앞 판정이 길면 뒤 요청이 함수 시간 제한까지 묶이지 않도록 기다리는 시간을 자른다
        if not _LOCK.acquire(timeout=settings.verdict_lock_timeout_s):
            _give_back_one(engine)
            raise HTTPException(503, BUSY)
        try:
            traced = trace.run_traced(
                engine,
                deps.embedder,
                deps.client,
                deps.model,
                house_manage_no,
                profile,
                cache=deps.cache,
                key=deps.key,
            )
        finally:
            _LOCK.release()
    except prof.ProfileError as e:
        raise HTTPException(422, str(e)) from e
    except axes.NoticeNotFound as e:
        raise HTTPException(404, str(e)) from e
    except HardApiError as e:
        log.error("판정 중 API 오류: %s", e)
        raise HTTPException(503, NO_DETAIL) from e
    except SQLAlchemyError as e:
        log.exception(
            "판정 중 DB 오류"
        )  # 스키마·코드 결함도 여기로 와서 로그가 없으면 원인을 못 찾는다
        raise HTTPException(503, f"DB 오류: {type(e).__name__}") from e
    if traced.trace_error:
        log.error("trace 행 쓰기 실패: %s", traced.trace_error)
    answer = dataclasses.asdict(traced.answer)
    if answer["checklist"] and all(i["error"] for i in answer["checklist"]):
        # 질의가 전부 실패하면 verdict가 null이라 「판정을 낼 근거가 없다」로 읽힌다. 장애를 알린다
        log.error("체크리스트 항목 %d개 전부 판정 실패", len(answer["checklist"]))
        raise HTTPException(503, NO_DETAIL)
    for item in answer["checklist"]:
        if item["error"]:  # 예외 문구에 요청 id·조직 정보가 섞일 수 있어 브라우저에는 안 보낸다
            log.error("체크리스트 항목 판정 실패 (%s): %s", item["axis"], item["error"])
            item["error"] = ITEM_FAILED
    return {
        **answer,
        "trace_id": traced.trace_id,
        "trace_error": "trace 행을 쓰지 못했다" if traced.trace_error else None,
    }
