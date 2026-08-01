from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client):
    with patch("src.service.health_service.neo4j_driver") as mock_driver:
        mock_driver.execute_read = AsyncMock(return_value=[{"ping": 1}])
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "neo4j" in data["dependencies"]
