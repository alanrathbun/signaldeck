import pytest
from httpx import AsyncClient, ASGITransport
from starlette.middleware.base import BaseHTTPMiddleware

from signaldeck.api.server import create_app, get_db
from signaldeck.api.auth import AuthManager


class _RemoteIPMiddleware(BaseHTTPMiddleware):
    """Force all requests to appear as a remote (non-LAN) IP for auth tests."""
    async def dispatch(self, request, call_next):
        request.scope["client"] = ("203.0.113.1", 0)
        return await call_next(request)


@pytest.fixture
def app_with_auth(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024, "sweep_ranges": []},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": True,
            "credentials_path": str(tmp_path / "credentials.yaml"),
        },
    }
    return create_app(config)


@pytest.fixture
def app_no_auth(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024, "sweep_ranges": []},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }
    return create_app(config)


async def test_health_always_accessible(app_with_auth):
    """Health endpoint doesn't require auth."""
    async with app_with_auth.router.lifespan_context(app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200


async def test_api_requires_token_when_auth_enabled(app_with_auth):
    """API endpoints return 401 without auth token (from a remote IP)."""
    # Simulate a remote (non-LAN) client so the LAN bypass doesn't fire.
    app_with_auth.add_middleware(_RemoteIPMiddleware)
    async with app_with_auth.router.lifespan_context(app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/signals")
            assert resp.status_code == 401


async def test_api_accessible_with_valid_token(app_with_auth):
    """API works with valid bearer token."""
    async with app_with_auth.router.lifespan_context(app_with_auth):
        from signaldeck.api.server import get_auth_manager
        mgr = get_auth_manager()
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/signals",
                                     headers={"Authorization": f"Bearer {mgr.api_token}"})
            assert resp.status_code == 200


async def test_no_auth_when_disabled(app_no_auth):
    """Without auth config, all endpoints are open."""
    async with app_no_auth.router.lifespan_context(app_no_auth):
        transport = ASGITransport(app=app_no_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/signals")
            assert resp.status_code == 200


async def test_login_endpoint(app_with_auth):
    """Can login with correct credentials."""
    async with app_with_auth.router.lifespan_context(app_with_auth):
        from signaldeck.api.server import get_auth_manager
        mgr = get_auth_manager()
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/login", json={
                "username": "admin",
                "password": mgr._initial_password,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "session_token" in data


async def test_login_wrong_password(app_with_auth):
    """Login fails with wrong password."""
    async with app_with_auth.router.lifespan_context(app_with_auth):
        transport = ASGITransport(app=app_with_auth)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong",
            })
            assert resp.status_code == 401
