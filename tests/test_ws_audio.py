import pytest
from starlette.testclient import TestClient
from signaldeck.api.server import create_app


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
    }
    return create_app(config)


def test_audio_websocket_connect(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_audio_websocket_subscribe(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "subscribe", "frequency_hz": 98.5e6})
        data = ws.receive_json()
        assert data["type"] == "subscribed"
        assert data["frequency_hz"] == 98.5e6


def test_audio_websocket_subscribe_with_volume(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "subscribe", "frequency_hz": 162.4e6, "volume": 0.05})
        data = ws.receive_json()
        assert data["type"] == "subscribed"
        assert data["frequency_hz"] == 162.4e6
