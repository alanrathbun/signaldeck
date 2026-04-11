import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app
from signaldeck.api.routes import scanner as scanner_routes

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


async def test_settings_exposes_scan_profiles(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "available_scan_profiles" in data["scanner"]
    assert "resolved_sweep_ranges" in data["scanner"]


async def test_settings_does_not_refresh_devices_by_default(client, monkeypatch):
    called = False

    async def fake_enumerate_async(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(scanner_routes.DeviceManager, "enumerate_async", fake_enumerate_async)

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    assert called is False


async def test_settings_can_refresh_devices_when_requested(client, monkeypatch):
    called = False

    async def fake_enumerate_async(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(scanner_routes.DeviceManager, "enumerate_async", fake_enumerate_async)

    resp = await client.get("/api/settings?refresh_devices=true")
    assert resp.status_code == 200
    assert called is True


# ---- Device role stickiness ----

async def test_device_roles_round_trip_through_settings(client, monkeypatch, tmp_path):
    """PUT /api/settings must persist scanner_device/tuner_device and GET
    must hand them back — the bug was that the frontend reset them to 'none'
    because they weren't populated from the backend response."""
    # Redirect persistence into tmp so we don't touch the real file.
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH", tmp_path / "user_settings.yaml"
    )
    resp = await client.put(
        "/api/settings",
        json={"scanner_device": "29414763", "tuner_device": "localhost:7356"},
    )
    assert resp.status_code == 200
    assert "scanner_device=29414763" in resp.json()["changed"]

    resp = await client.get("/api/settings")
    devices = resp.json()["devices"]
    assert devices.get("scanner_device") == "29414763"
    assert devices.get("tuner_device") == "localhost:7356"

    # Persisted file contains the keys, NOT the literal string 'none'.
    persisted = (tmp_path / "user_settings.yaml").read_text()
    assert "scanner_device: '29414763'" in persisted or "scanner_device: 29414763" in persisted
    assert "'none'" not in persisted
    assert "\nnone" not in persisted


async def test_device_roles_none_clears_preference(client, monkeypatch, tmp_path):
    """Sending 'none' should clear the persisted preference instead of
    writing the literal string 'none' — the real bug in production."""
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH", tmp_path / "user_settings.yaml"
    )

    # First, set a real value.
    resp = await client.put(
        "/api/settings",
        json={"scanner_device": "29414763", "tuner_device": "localhost:7356"},
    )
    assert resp.status_code == 200

    # Then send 'none' — this is what a buggy frontend used to do on every save.
    resp = await client.put(
        "/api/settings",
        json={"scanner_device": "none", "tuner_device": "none"},
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings")
    devices = resp.json()["devices"]
    assert devices.get("scanner_device") in (None, "")
    assert devices.get("tuner_device") in (None, "")

    persisted = (tmp_path / "user_settings.yaml").read_text()
    assert "scanner_device" not in persisted
    assert "tuner_device" not in persisted
