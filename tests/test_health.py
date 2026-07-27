import httpx
import pytest
from httpx import ASGITransport

from cheongyak_rag.main import app


@pytest.mark.asyncio
async def test_health_reports_db_and_pgvector():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    # 마이그레이션이 돌았다면 vector 확장이 설치돼 있어야 한다.
    assert body["pgvector"] == "ok"
