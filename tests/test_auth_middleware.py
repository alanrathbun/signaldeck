"""End-to-end tests for the new AuthMiddleware with LAN bypass + remember-me."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

from signaldeck.api.server import create_app, get_auth_manager, get_db


def _config_with_auth(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": True,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "lan_allowlist": [
                "127.0.0.0/8",
                "10.0.0.0/8",
                "192.168.0.0/16",
                "100.64.0.0/10",
            ],
            "trust_x_forwarded_for": False,
            "remember_token_days": None,
        },
    }


class _ClientIPRewriter(BaseHTTPMiddleware):
    """Test helper: rewrite request.scope['client'] to simulate any origin IP.

    The simulated IP is read from the X-Test-Client-IP header so each
    request can choose its own.
    """
    async def dispatch(self, request, call_next):
        override = request.headers.get("x-test-client-ip")
        if override:
            request.scope["client"] = (override, 0)
        return await call_next(request)


@pytest.fixture
def app(tmp_path):
    app = create_app(_config_with_auth(tmp_path))
    # Install the IP rewriter OUTSIDE of the existing middleware stack so it
    # runs first and AuthMiddleware sees the rewritten client.
    app.add_middleware(_ClientIPRewriter)
    return app


async def _client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_is_public(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/health",
                headers={"x-test-client-ip": "8.8.8.8"},  # Remote, no auth
            )
            assert resp.status_code == 200


async def test_loopback_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "127.0.0.1"},
            )
            assert resp.status_code == 200


async def test_lan_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "192.168.1.50"},
            )
            assert resp.status_code == 200


async def test_tailscale_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "100.94.221.106"},
            )
            assert resp.status_code == 200


async def test_remote_client_without_credentials_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
            )
            assert resp.status_code == 401


async def test_remote_client_with_bearer_token_passes(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={
                    "x-test-client-ip": "203.0.113.42",
                    "authorization": f"Bearer {mgr.api_token}",
                },
            )
            assert resp.status_code == 200


async def test_remote_client_with_invalid_bearer_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={
                    "x-test-client-ip": "203.0.113.42",
                    "authorization": "Bearer not-a-real-token",
                },
            )
            assert resp.status_code == 401


async def test_remote_client_with_valid_remember_cookie_passes(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="test", ip="203.0.113.42")

        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": raw},
            )
            assert resp.status_code == 200


async def test_remote_client_with_invalid_cookie_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": "fake-token"},
            )
            assert resp.status_code == 401


async def test_remote_client_with_revoked_cookie_gets_401(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="test", ip="203.0.113.42")

        # Revoke the token
        import hashlib
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        row = await db.get_remember_token_by_hash(token_hash)
        await db.revoke_remember_token(row["id"])

        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": raw},
            )
            assert resp.status_code == 401


async def test_auth_login_path_is_public(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            # POST with wrong creds — we just want to verify the middleware
            # didn't 401 before the route handler got a chance to return 401.
            resp = await c.post(
                "/api/auth/login",
                headers={"x-test-client-ip": "203.0.113.42"},
                json={"username": "admin", "password": "wrong"},
            )
            # The route should respond with 401 (bad creds), NOT be blocked
            # by middleware. A pass-through-to-route 401 is what we want;
            # a middleware 401 would have a different detail message, but
            # either way the status is 401. So assert that the body contains
            # the route's own error message shape.
            assert resp.status_code == 401
            # Route-level 401 uses "Invalid credentials", middleware uses
            # "Not authenticated". We want the route's message here.
            assert "Invalid credentials" in resp.text


async def test_auth_sessions_path_is_protected(app):
    """/api/auth/sessions requires auth even though it's under /api/auth/."""
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/auth/sessions",
                headers={"x-test-client-ip": "203.0.113.42"},
            )
            # Task 8 hasn't added the route yet — 401 (middleware blocked) or
            # 404 (middleware passed, route not found) are both acceptable.
            # What we must NOT see is 200 (middleware bypassed).
            assert resp.status_code in (401, 404)
