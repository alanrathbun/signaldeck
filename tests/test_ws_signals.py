import pytest
from starlette.testclient import TestClient
from signaldeck.api.server import create_app
from signaldeck.api.websocket.live_signals import signal_broadcast, signal_batch_broadcast


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


def test_websocket_connect(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/signals") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_signal_broadcast_function():
    msg = signal_broadcast(
        frequency_hz=98.5e6,
        bandwidth_hz=200e3,
        power=-30.0,
        modulation="FM",
        protocol="broadcast_fm",
    )
    assert msg["type"] == "signal"
    assert msg["frequency_mhz"] == 98.5


def test_signal_batch_broadcast_function():
    msg = signal_batch_broadcast([signal_broadcast(98.5e6, 200e3, -30.0)])
    assert msg["type"] == "signal_batch"
    assert len(msg["signals"]) == 1
