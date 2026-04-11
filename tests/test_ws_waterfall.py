import numpy as np
import pytest
from starlette.testclient import TestClient
from signaldeck.api.server import create_app
from signaldeck.api.websocket.waterfall import fft_broadcast


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


def test_waterfall_websocket_connect(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/waterfall") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_fft_broadcast_message():
    power_db = np.full(1024, -90.0)
    msg = fft_broadcast(center_freq_hz=100e6, sample_rate=2e6, power_db=power_db)
    assert msg["type"] == "fft"
    assert msg["center_freq_mhz"] == 100.0
    assert len(msg["data"]) == 1024
    assert msg["freq_start"] == 100e6 - 1e6
    assert msg["freq_end"] == 100e6 + 1e6
