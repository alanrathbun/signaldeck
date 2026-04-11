"""Tests for /api/process/* — process lifecycle endpoints.

We don't actually shell out to systemctl in these tests; we monkeypatch
`_run_systemctl` and `_probe_supervisor` so the test runs on any box
(including CI without a user systemd bus) and stays fast.
"""
import os

import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app
from signaldeck.api.routes import process as process_routes


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [{"label": "Test", "start_mhz": 88, "end_mhz": 108}],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "_start_time": "2026-04-10T00:00:00+00:00",
    }
    return create_app(config)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        # Clear the supervisor probe cache between tests so monkeypatches take
        # effect immediately.
        process_routes._invalidate_supervisor_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _patch_supervisor(monkeypatch, **overrides):
    """Install a fake _probe_supervisor that returns a managed+systemd state
    by default, plus any field overrides the test wants."""
    state = {
        "kind": "systemd-user",
        "managed": True,
        "unit": "signaldeck.service",
        "active_state": "active",
        "sub_state": "running",
        "load_state": "loaded",
        "main_pid": os.getpid(),
        "reason": "",
    }
    state.update(overrides)

    async def fake_probe():
        return state

    monkeypatch.setattr(process_routes, "_probe_supervisor", fake_probe)
    return state


@pytest.fixture
def patch_systemctl_ok(monkeypatch):
    """Make the fire-and-forget systemctl call a no-op so tests don't spawn
    real subprocesses."""
    calls = []

    async def fake_run(*args, timeout=5.0):
        calls.append(args)
        return 0, "", ""

    monkeypatch.setattr(process_routes, "_run_systemctl", fake_run)
    return calls


async def test_process_status_reports_pid_and_uptime(client, monkeypatch):
    _patch_supervisor(monkeypatch)
    resp = await client.get("/api/process/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pid"] == os.getpid()
    assert data["running"] is True
    assert data["can_control"] is True
    assert data["supervisor"]["kind"] == "systemd-user"
    # uptime should be a non-negative number given the fake _start_time.
    assert data["uptime_seconds"] is not None
    assert data["uptime_seconds"] >= 0


async def test_process_status_greys_out_controls_for_remote_viewer(app, monkeypatch):
    """Remote viewers (non-loopback, no auth) should see can_control=False
    with a reason, so the UI buttons stay disabled and remote Stop/Restart
    never even gets attempted."""
    _patch_supervisor(monkeypatch)
    async with app.router.lifespan_context(app):
        process_routes._invalidate_supervisor_cache()
        transport = ASGITransport(app=app, client=("192.168.1.42", 55555))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/process/status")
            assert resp.status_code == 200
            data = resp.json()
            # Supervisor is managed — this is purely about the caller being remote.
            assert data["supervisor"]["managed"] is True
            assert data["can_control"] is False
            assert "localhost" in data["control_reason"].lower()


async def test_process_status_unmanaged_when_unit_missing(client, monkeypatch):
    _patch_supervisor(
        monkeypatch,
        kind="none",
        managed=False,
        unit=None,
        active_state=None,
        sub_state=None,
        load_state=None,
        main_pid=None,
        reason="signaldeck.service is not installed",
    )
    resp = await client.get("/api/process/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_control"] is False
    assert data["supervisor"]["managed"] is False
    assert "not installed" in data["supervisor"]["reason"]


async def test_process_restart_returns_409_when_unmanaged(client, monkeypatch, patch_systemctl_ok):
    _patch_supervisor(monkeypatch, managed=False, reason="not managed")
    resp = await client.post("/api/process/restart", json={})
    assert resp.status_code == 409
    # The fire-and-forget systemctl call must NOT have been scheduled.
    assert patch_systemctl_ok == []


async def test_process_restart_accepts_and_invokes_systemctl(client, monkeypatch, patch_systemctl_ok):
    _patch_supervisor(monkeypatch)
    resp = await client.post("/api/process/restart", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["action"] == "restart"
    # The fire-and-forget task runs on the event loop; yield to let it
    # execute before asserting.
    import asyncio
    for _ in range(10):
        if patch_systemctl_ok:
            break
        await asyncio.sleep(0.01)
    assert any(args[:2] == ("restart", "signaldeck.service") for args in patch_systemctl_ok)


async def test_process_stop_and_start_accepted(client, monkeypatch, patch_systemctl_ok):
    _patch_supervisor(monkeypatch)
    for verb in ("start", "stop"):
        resp = await client.post(f"/api/process/{verb}", json={})
        assert resp.status_code == 200, f"{verb} -> {resp.text}"
        assert resp.json()["action"] == verb


async def test_process_control_rejected_from_non_loopback_without_auth(app, monkeypatch, patch_systemctl_ok):
    """The auth-or-loopback gate should refuse a non-loopback client when
    the auth manager is not installed."""
    _patch_supervisor(monkeypatch)
    # AuthMiddleware returns 401 for /api/* without auth when get_auth_manager
    # is None, but only if auth is actually configured. In these tests auth
    # is disabled, so the middleware passes requests through and our
    # _require_authorized guard has to catch the non-loopback caller.
    async with app.router.lifespan_context(app):
        process_routes._invalidate_supervisor_cache()
        transport = ASGITransport(app=app, client=("10.0.0.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/process/restart", json={})
            assert resp.status_code == 403
            assert patch_systemctl_ok == []
