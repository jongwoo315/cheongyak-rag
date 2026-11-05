"""화면이 부르는 HTTP API (#84). 공고 조회 둘과 판정 하나.

Next.js는 이 API만 부른다. 판정은 CLI와 같은 `trace.run_traced`를 부른다.
"""

from functools import lru_cache
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings

router = APIRouter(prefix="/api")


@lru_cache
def get_engine() -> Engine:
    """동기 `Engine` 하나. 테스트는 `app.dependency_overrides`로 갈아 끼운다."""
    return sa.create_engine(settings.database_url, pool_pre_ping=True)


EngineDep = Annotated[Engine, Depends(get_engine)]

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
