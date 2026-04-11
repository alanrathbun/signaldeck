"""Handshake-level auth tests for the /ws/* endpoints."""
import pytest
from starlette.testclient import TestClient

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
            "lan_allowlist": ["127.0.0.0/8"],
            "trust_x_forwarded_for": False,
            "remember_token_days": None,
        },
    }


def test_ws_audio_remote_no_cookie_rejected(tmp_path):
    """Starlette's TestClient uses 'testclient' as the client host, which is
    not in the LAN allowlist. Without a remember-me cookie, the handshake
    must close with code 1008."""
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/audio") as ws:
                ws.send_json({"type": "ping"})
                ws.receive_json()
        assert exc.value.code == 1008


def test_ws_audio_with_valid_cookie_accepts(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        mgr = get_auth_manager()
        db = get_db()
        import asyncio
        raw = asyncio.run(
            mgr.create_remember_token(db, user_agent="test", ip="1.1.1.1")
        )

        client.cookies.set("sd_remember", raw)
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json({"type": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"


def test_ws_signals_remote_no_cookie_rejected(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/signals") as ws:
                ws.receive_json()
        assert exc.value.code == 1008


def test_ws_waterfall_remote_no_cookie_rejected(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/waterfall") as ws:
                ws.receive_json()
        assert exc.value.code == 1008
