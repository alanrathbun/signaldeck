"""Tests for /api/status audio block."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app
from signaldeck.api.websocket import audio_stream


def _config(tmp_path, audio_mode="auto"):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": audio_mode,
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }


@pytest.fixture(autouse=True)
def clear_clients():
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


async def test_status_audio_no_subscribers(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            assert resp.status_code == 200
            body = resp.json()
            assert "audio" in body
            assert body["audio"]["configured_mode"] == "auto"
            assert body["audio"]["effective_mode"] == "gqrx"
            assert body["audio"]["subscriber_count"] == 0
            assert body["audio"]["remote_subscriber_count"] == 0


async def test_status_audio_with_remote_subscriber(tmp_path):
    audio_stream._audio_clients["w1"] = {
        "freq": 100e6, "is_lan": False, "remote_addr": "8.8.8.8"
    }
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            body = resp.json()
            assert body["audio"]["effective_mode"] == "pcm_stream"
            assert body["audio"]["subscriber_count"] == 1
            assert body["audio"]["remote_subscriber_count"] == 1


async def test_status_audio_manual_gqrx_overrides(tmp_path):
    audio_stream._audio_clients["w1"] = {
        "freq": 100e6, "is_lan": False, "remote_addr": "8.8.8.8"
    }
    app = create_app(_config(tmp_path, audio_mode="gqrx"))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            body = resp.json()
            assert body["audio"]["configured_mode"] == "gqrx"
            assert body["audio"]["effective_mode"] == "gqrx"  # Manual pin
