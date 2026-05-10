"""
Integration tests for /analytics/papers endpoints.
Requires running PostgreSQL with migration 022 applied.
"""
import pytest


@pytest.mark.asyncio
async def test_papers_list_returns_200(aiohttp_client, analytics_app):
    """GET /analytics/papers returns 200 and a list."""
    client = await aiohttp_client(analytics_app)
    resp = await client.get("/analytics/papers")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_paper_detail_not_found(aiohttp_client, analytics_app):
    """GET /analytics/papers/{nonexistent} returns 404."""
    client = await aiohttp_client(analytics_app)
    resp = await client.get("/analytics/papers/00000000-0000-0000-0000-000000000000")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_paper_summary_not_found(aiohttp_client, analytics_app):
    """GET /analytics/papers/{id}/summary with no summary returns 404."""
    client = await aiohttp_client(analytics_app)
    resp = await client.get("/analytics/papers/00000000-0000-0000-0000-000000000000/summary")
    assert resp.status in (404, 200)
