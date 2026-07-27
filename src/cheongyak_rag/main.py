from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cheongyak_rag.db import get_session

app = FastAPI(title="주택청약 RAG", version="0.1.0")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@app.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    """DB 연결과 pgvector 설치 여부까지 확인한다.

    앱만 뜨고 DB가 죽은 상태를 health 통과시키지 않기 위함.
    """
    await session.execute(text("SELECT 1"))
    vector_installed = await session.scalar(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    )
    return {
        "status": "ok",
        "db": "ok",
        "pgvector": "ok" if vector_installed else "missing",
    }
