import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app

@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": [{"label": "Test", "start_mhz": 88, "end_mhz": 108}]},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }
    return create_app(config)

@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data

async def test_api_returns_json(client):
    resp = await client.get("/api/signals")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")

async def test_unknown_route_returns_404(client):
    resp = await client.get("/api/nonexistent")
    assert resp.status_code == 404
