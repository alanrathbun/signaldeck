import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def tmp_config(tmp_path: Path) -> dict:
    """Provide a minimal test configuration dict."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return {
        "devices": {"auto_discover": False, "gain": 40},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [
                {"label": "Test", "start_mhz": 88, "end_mhz": 108},
            ],
        },
        "audio": {
            "sample_rate": 48000,
            "recording_dir": str(data_dir / "recordings"),
            "format": "wav",
        },
        "storage": {
            "database_path": str(data_dir / "signaldeck.db"),
        },
        "logging": {"level": "DEBUG"},
    }
