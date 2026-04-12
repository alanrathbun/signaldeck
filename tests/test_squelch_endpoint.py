import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
async def client(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "scanner": {},
    }
    app = create_app(config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_squelch_open_no_gqrx(client):
    resp = await client.get("/api/gqrx/squelch-open")
    assert resp.status_code == 503
    assert "not connected" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_squelch_open_true(client):
    from signaldeck.api.routes.scanner import _scanner_state
    mock_client = AsyncMock()
    mock_client.get_signal_strength = AsyncMock(return_value=-35.0)
    mock_client.get_squelch = AsyncMock(return_value=-60.0)
    _scanner_state["_gqrx_client"] = mock_client
    try:
        resp = await client.get("/api/gqrx/squelch-open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open"] is True
        assert data["strength_dbfs"] == -35.0
        assert data["squelch_dbfs"] == -60.0
    finally:
        _scanner_state.pop("_gqrx_client", None)


@pytest.mark.asyncio
async def test_squelch_open_false(client):
    from signaldeck.api.routes.scanner import _scanner_state
    mock_client = AsyncMock()
    mock_client.get_signal_strength = AsyncMock(return_value=-80.0)
    mock_client.get_squelch = AsyncMock(return_value=-60.0)
    _scanner_state["_gqrx_client"] = mock_client
    try:
        resp = await client.get("/api/gqrx/squelch-open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open"] is False
    finally:
        _scanner_state.pop("_gqrx_client", None)
