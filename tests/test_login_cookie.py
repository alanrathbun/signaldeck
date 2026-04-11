"""Tests for the login endpoint cookie-setting behavior and toggle's
first_run_password surfacing."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app, get_auth_manager


def _config(tmp_path, auth_enabled=True):
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
            "enabled": auth_enabled,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "remember_token_days": None,
        },
    }


async def test_login_sets_sd_remember_cookie(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            assert resp.status_code == 200
            # Set-Cookie header must be present
            cookies = resp.headers.get_list("set-cookie")
            assert any(ck.startswith("sd_remember=") for ck in cookies), cookies
            # Body carries the raw token for CLI/curl
            body = resp.json()
            assert "remember_token" in body
            assert body["username"] == "admin"
            # Old dead field is gone
            assert "session_token" not in body


async def test_login_cookie_max_age_when_days_null_is_10_years(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            cookies = resp.headers.get_list("set-cookie")
            sd = [c for c in cookies if c.startswith("sd_remember=")][0]
            assert "Max-Age=315360000" in sd  # 10 years
            assert "HttpOnly" in sd
            assert "Path=/" in sd
            assert "SameSite=Lax" in sd.lower() or "samesite=lax" in sd.lower()


async def test_login_cookie_max_age_when_days_is_integer(tmp_path):
    cfg = _config(tmp_path)
    cfg["auth"]["remember_token_days"] = 30
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            cookies = resp.headers.get_list("set-cookie")
            sd = [c for c in cookies if c.startswith("sd_remember=")][0]
            assert "Max-Age=2592000" in sd  # 30 * 86400


async def test_toggle_returns_first_run_password_on_initial_enable(tmp_path):
    """The first time toggle enables auth and creates the credentials file,
    it must surface the generated password so the frontend can show it."""
    app = create_app(_config(tmp_path, auth_enabled=False))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/toggle", json={"enabled": True})
            assert resp.status_code == 200
            body = resp.json()
            assert body["enabled"] is True
            # First-run password is present exactly once, and only on first run
            assert "first_run_password" in body
            assert body["first_run_password"]
            assert len(body["first_run_password"]) >= 16


async def test_toggle_does_not_return_first_run_password_on_subsequent(tmp_path):
    """Enabling again (after credentials file already exists) does NOT surface
    a password — because there is no new password, just the hashed existing one."""
    cred_path = tmp_path / "credentials.yaml"
    # Pre-seed by creating once
    from signaldeck.api.auth import AuthManager
    m = AuthManager(credentials_path=str(cred_path))
    m.initialize()

    app = create_app(_config(tmp_path, auth_enabled=False))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/toggle", json={"enabled": True})
            assert resp.status_code == 200
            body = resp.json()
            assert body["enabled"] is True
            assert "first_run_password" not in body
