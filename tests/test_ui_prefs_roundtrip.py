"""Tests for ui.live_visible_cols round-trip through /api/settings."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app


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


async def test_put_settings_accepts_ui_live_visible_cols(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            cols = ["frequency", "modulation", "hits", "last_seen"]
            resp = await c.put(
                "/api/settings",
                json={"ui": {"live_visible_cols": cols}},
            )
            assert resp.status_code == 200

            # Round-trip
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("ui", {}).get("live_visible_cols") == cols


async def test_persist_writes_ui_block(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    path = tmp_path / "user_settings.yaml"
    monkeypatch.setattr(scanner_routes, "_USER_CONFIG_PATH", path)

    config = {
        "devices": {"gain": 40},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "auto",
        },
        "audio": {},
        "logging": {"level": "INFO"},
        "ui": {
            "live_visible_cols": ["frequency", "modulation"],
        },
    }
    scanner_routes._persist_user_config(config)

    import yaml
    with open(path) as f:
        persisted = yaml.safe_load(f)
    assert persisted["ui"]["live_visible_cols"] == ["frequency", "modulation"]
