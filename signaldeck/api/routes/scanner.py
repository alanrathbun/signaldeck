import logging
from pathlib import Path

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from signaldeck.api.server import get_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])

# Scanner state (in-memory, managed by the CLI start command)
_scanner_state = {
    "status": "running",  # set by CLI on startup
    "mode": "sweep",
    "backend": "soapysdr",  # "soapysdr" or "gqrx"
    "active_devices": 0,
}


def set_scanner_state(status: str, mode: str = "sweep", active_devices: int = 1) -> None:
    """Called by the CLI to update scanner state."""
    _scanner_state["status"] = status
    _scanner_state["mode"] = mode
    _scanner_state["active_devices"] = active_devices


@router.get("/scanner/status")
async def scanner_status():
    config = get_config()
    return {
        **_scanner_state,
        "scan_ranges": config.get("scanner", {}).get("sweep_ranges", []),
        "squelch_offset": config.get("scanner", {}).get("squelch_offset"),
        "fft_size": config.get("scanner", {}).get("fft_size"),
        "gain": config.get("devices", {}).get("gain"),
    }


@router.post("/scanner/start")
async def scanner_start():
    _scanner_state["status"] = "running"
    return {"status": "running", "message": "Scanner is running (managed by engine)"}


@router.post("/scanner/stop")
async def scanner_stop():
    _scanner_state["status"] = "idle"
    return {"status": "idle", "message": "Scanner paused"}


@router.get("/settings")
async def get_settings():
    """Return full configuration for the settings page."""
    config = get_config()
    return {
        "devices": config.get("devices", {}),
        "scanner": config.get("scanner", {}),
        "audio": config.get("audio", {}),
        "storage": config.get("storage", {}),
        "auth": {
            "enabled": config.get("auth", {}).get("enabled", False),
        },
    }


class ScanRangeUpdate(BaseModel):
    label: str = ""
    start_mhz: float
    end_mhz: float


class SettingsUpdate(BaseModel):
    gain: float | None = None
    squelch_offset: float | None = None
    min_signal_strength: float | None = None
    dwell_time_ms: float | None = None
    fft_size: int | None = None
    scan_ranges: list[ScanRangeUpdate] | None = None


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    """Update runtime configuration. Changes take effect on next scan cycle.

    Changes are applied to the in-memory config. To persist across restarts,
    save to a custom config YAML file.
    """
    config = get_config()
    changed = []

    if data.gain is not None:
        config["devices"]["gain"] = data.gain
        changed.append(f"gain={data.gain}")

    if data.squelch_offset is not None:
        config["scanner"]["squelch_offset"] = data.squelch_offset
        changed.append(f"squelch_offset={data.squelch_offset}")

    if data.min_signal_strength is not None:
        config["scanner"]["min_signal_strength"] = data.min_signal_strength
        changed.append(f"min_signal_strength={data.min_signal_strength}")

    if data.dwell_time_ms is not None:
        config["scanner"]["dwell_time_ms"] = data.dwell_time_ms
        changed.append(f"dwell_time_ms={data.dwell_time_ms}")

    if data.fft_size is not None:
        config["scanner"]["fft_size"] = data.fft_size
        changed.append(f"fft_size={data.fft_size}")

    if data.scan_ranges is not None:
        config["scanner"]["sweep_ranges"] = [
            {"label": r.label, "start_mhz": r.start_mhz, "end_mhz": r.end_mhz}
            for r in data.scan_ranges
        ]
        changed.append(f"scan_ranges={len(data.scan_ranges)} ranges")

    # Persist settings to user config file so they survive restarts
    if changed:
        _persist_user_config(config)

    return {"status": "updated", "changed": changed}


_USER_CONFIG_PATH = Path("config/user_settings.yaml")


def _persist_user_config(config: dict) -> None:
    """Write the user-customizable settings to a YAML file."""
    user_cfg = {
        "devices": {
            "gain": config.get("devices", {}).get("gain", 40),
        },
        "scanner": {
            "squelch_offset": config["scanner"].get("squelch_offset", 10),
            "min_signal_strength": config["scanner"].get("min_signal_strength", -50),
            "dwell_time_ms": config["scanner"].get("dwell_time_ms", 50),
            "fft_size": config["scanner"].get("fft_size", 1024),
            "sweep_ranges": config["scanner"].get("sweep_ranges", []),
        },
    }
    try:
        _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_CONFIG_PATH, "w") as f:
            yaml.dump(user_cfg, f, default_flow_style=False, sort_keys=False)
        logger.info("Settings persisted to %s", _USER_CONFIG_PATH)
    except Exception as e:
        logger.error("Failed to persist settings: %s", e)
