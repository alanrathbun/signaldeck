"""Tests for audio_mode config: default, persistence, settings round-trip."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app
from signaldeck.config import load_config


def test_default_config_has_audio_mode_auto():
    cfg = load_config(None, load_user_settings=False)
    assert cfg["scanner"].get("audio_mode") == "auto"


def _config(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "auto",
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }


async def test_put_settings_accepts_audio_mode(tmp_path, monkeypatch):
    # Redirect _USER_CONFIG_PATH to tmp so tests don't clobber real config
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={"audio_mode": "pcm_stream"})
            assert resp.status_code == 200

            # Verify it round-trips
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            assert resp.json()["scanner"]["audio_mode"] == "pcm_stream"


async def test_put_settings_rejects_invalid_audio_mode(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={"audio_mode": "nonsense"})
            assert resp.status_code == 400


async def test_persist_user_config_writes_audio_mode(tmp_path, monkeypatch):
    """_persist_user_config should round-trip audio_mode to disk."""
    import signaldeck.api.routes.scanner as scanner_routes
    user_cfg_path = tmp_path / "user_settings.yaml"
    monkeypatch.setattr(scanner_routes, "_USER_CONFIG_PATH", user_cfg_path)

    config = {
        "devices": {"gain": 40},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "pcm_stream",
        },
        "audio": {},
        "logging": {"level": "INFO"},
    }
    scanner_routes._persist_user_config(config)

    import yaml
    with open(user_cfg_path) as f:
        persisted = yaml.safe_load(f)
    assert persisted["scanner"]["audio_mode"] == "pcm_stream"
