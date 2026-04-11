"""Tests for the /api/auth/sessions endpoints: list, rename, revoke, logout."""
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app, get_auth_manager, get_db


def _config(tmp_path):
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
            "remember_token_days": None,
        },
    }


_REMOTE_IP = ("203.0.113.42", 0)  # Non-LAN IP so AuthMiddleware is enforced


async def _authed_client(app, raw_token):
    transport = ASGITransport(app=app, client=_REMOTE_IP)
    c = AsyncClient(transport=transport, base_url="http://test")
    c.cookies.set("sd_remember", raw_token)
    return c


async def test_list_sessions_requires_auth(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=_REMOTE_IP)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 401


async def test_list_sessions_returns_current_flag(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw_a = await mgr.create_remember_token(db, user_agent="Mac Safari", ip="1.1.1.1")
        raw_b = await mgr.create_remember_token(db, user_agent="iPhone Safari", ip="2.2.2.2")

        async with await _authed_client(app, raw_a) as c:
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 200
            rows = resp.json()
            assert isinstance(rows, list)
            assert len(rows) == 2
            # The row backed by raw_a is the current device
            current_rows = [r for r in rows if r.get("is_current")]
            assert len(current_rows) == 1


async def test_list_sessions_never_exposes_token_hash(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.get("/api/auth/sessions")
            rows = resp.json()
            for r in rows:
                assert "token_hash" not in r


async def test_rename_session(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1", label="old")

        async with await _authed_client(app, raw) as c:
            list_resp = await c.get("/api/auth/sessions")
            session_id = list_resp.json()[0]["id"]

            resp = await c.patch(
                f"/api/auth/sessions/{session_id}",
                json={"label": "new label"},
            )
            assert resp.status_code == 200

            list_resp = await c.get("/api/auth/sessions")
            assert list_resp.json()[0]["label"] == "new label"


async def test_rename_missing_returns_404(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.patch(
                "/api/auth/sessions/99999",
                json={"label": "nope"},
            )
            assert resp.status_code == 404


async def test_revoke_session(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw_a = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
        raw_b = await mgr.create_remember_token(db, user_agent="ua", ip="2.2.2.2")

        async with await _authed_client(app, raw_a) as c:
            list_resp = await c.get("/api/auth/sessions")
            rows = list_resp.json()
            # Revoke the OTHER session (not current)
            other = [r for r in rows if not r.get("is_current")][0]
            resp = await c.delete(f"/api/auth/sessions/{other['id']}")
            assert resp.status_code == 200

            # Only current session left
            list_resp = await c.get("/api/auth/sessions")
            assert len(list_resp.json()) == 1


async def test_logout_revokes_current_token(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.post("/api/auth/logout")
            assert resp.status_code == 200

            # Next request from same client should 401 — cookie is revoked
            # server-side (the cookie value still exists in the client, but
            # the DB row is gone).
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 401
