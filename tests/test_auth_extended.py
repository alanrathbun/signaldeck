import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": []},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {"enabled": True, "credentials_path": str(tmp_path / "creds.yaml")},
    }
    return create_app(config)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _get_token(client):
    """Login and return the API token."""
    from signaldeck.api.server import get_auth_manager
    mgr = get_auth_manager()
    password = mgr._initial_password
    resp = await client.post("/api/auth/login", json={
        "username": "admin", "password": password
    })
    return resp.json()["api_token"]


@pytest.mark.asyncio
class TestAuthExtended:
    async def test_get_token(self, client):
        token = await _get_token(client)
        resp = await client.get("/api/auth/token",
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["api_token"] == token

    async def test_get_token_unauthenticated(self, client):
        resp = await client.get("/api/auth/token")
        assert resp.status_code == 401

    async def test_regenerate_token(self, client):
        token = await _get_token(client)
        resp = await client.post("/api/auth/regenerate-token",
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        new_token = resp.json()["api_token"]
        assert new_token != token
        # Old token should no longer work
        resp2 = await client.get("/api/auth/token",
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp2.status_code == 401

    async def test_toggle_auth_off(self, client):
        token = await _get_token(client)
        resp = await client.post("/api/auth/toggle",
                                 json={"enabled": False},
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_toggle_auth_on(self, client):
        token = await _get_token(client)
        await client.post("/api/auth/toggle",
                          json={"enabled": False},
                          headers={"Authorization": f"Bearer {token}"})
        resp = await client.post("/api/auth/toggle",
                                 json={"enabled": True},
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
