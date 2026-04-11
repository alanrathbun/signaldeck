import logging
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter
from fastapi import Query
from pydantic import BaseModel

from signaldeck.api.server import get_config, get_db
from signaldeck.engine.device_manager import DeviceManager
from signaldeck.engine.scan_presets import get_scan_profile_catalog, resolve_scan_profile_keys, resolve_sweep_ranges

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])

# Scanner state (in-memory, managed by the CLI start command)
_scanner_state = {
    "status": "idle",  # starts idle; set to "running" by auto_start or UI button
    "mode": "sweep",
    "backend": "soapysdr",  # "soapysdr" or "gqrx"
    "active_devices": 0,
    "scanner_device": None,
    "tuner_device": None,
    "current_range": None,
}


def set_scanner_state(status: str, mode: str = "sweep", active_devices: int = 1) -> None:
    """Called by the CLI to update scanner state."""
    _scanner_state["status"] = status
    _scanner_state["mode"] = mode
    _scanner_state["active_devices"] = active_devices
    if status != "running":
        _scanner_state["current_range"] = None


@router.get("/scanner/status")
async def scanner_status():
    config = get_config()
    scanner_cfg = config.get("scanner", {})
    return {
        **_scanner_state,
        "scan_ranges": resolve_sweep_ranges(scanner_cfg),
        "scan_profiles": resolve_scan_profile_keys(scanner_cfg),
        "available_scan_profiles": get_scan_profile_catalog(),
        "squelch_offset": scanner_cfg.get("squelch_offset"),
        "fft_size": scanner_cfg.get("fft_size"),
        "gain": config.get("devices", {}).get("gain"),
    }


class StartScannerRequest(BaseModel):
    mode: str = "sweep"


@router.post("/scanner/start")
async def scanner_start(data: StartScannerRequest = None):
    if data is None:
        data = StartScannerRequest()
    _scanner_state["status"] = "running"
    _scanner_state["mode"] = data.mode
    return {"status": "running", "mode": data.mode, "message": f"Scanner running in {data.mode} mode"}


@router.post("/scanner/stop")
async def scanner_stop():
    _scanner_state["status"] = "idle"
    _scanner_state["current_range"] = None
    return {"status": "idle", "message": "Scanner paused"}


@router.get("/status")
async def get_status():
    """Return system status for the Status page."""
    from signaldeck.api.websocket.live_signals import _clients as ws_clients
    config = get_config()
    db = get_db()
    db_stats = await db.get_stats()
    return {
        "scanner": _scanner_state,
        "device_status": config.get("_runtime_devices", {}),
        "db_stats": db_stats,
        "ws_clients": len(ws_clients),
        "session_log": config.get("_session_log_file"),
        "start_time": config.get("_start_time"),
    }


@router.get("/settings")
async def get_settings(refresh_devices: bool = Query(default=False)):
    """Return full configuration for the settings page."""
    config = get_config()
    scanner_cfg = config.get("scanner", {})
    devices_cfg = config.setdefault("devices", {})

    # Refresh visible device inventory so the UI can pick up gqrx or SDRs
    # that came online after SignalDeck started.
    if refresh_devices:
        try:
            mgr = DeviceManager()
            available = await mgr.enumerate_async(
                gqrx_auto_detect=devices_cfg.get("gqrx_auto_detect", True),
                gqrx_instances=devices_cfg.get("gqrx_instances", []),
            )
            hw_devices = [d for d in available if d.driver not in ("audio", "gqrx")]
            gqrx_devices = [d for d in available if d.driver == "gqrx"]
            devices_cfg["discovered"] = [
                {"label": d.label, "driver": d.driver, "serial": d.serial}
                for d in hw_devices
            ]
            devices_cfg["gqrx_instances"] = [
                {"host": d.serial.split(":")[0], "port": int(d.serial.split(":")[1])}
                for d in gqrx_devices
            ]
        except Exception as e:
            logger.warning("Device refresh failed in settings endpoint: %s", e)

    return {
        "devices": devices_cfg,
        "scanner": {
            **scanner_cfg,
            "scan_profiles": resolve_scan_profile_keys(scanner_cfg),
            "resolved_sweep_ranges": resolve_sweep_ranges(scanner_cfg),
            "available_scan_profiles": get_scan_profile_catalog(),
        },
        "audio": config.get("audio", {}),
        "storage": config.get("storage", {}),
        "auth": {
            "enabled": config.get("auth", {}).get("enabled", False),
        },
        "logging": {
            "level": config.get("logging", {}).get("level", "INFO"),
        },
    }


class ScanRangeUpdate(BaseModel):
    label: str = ""
    start_mhz: float
    end_mhz: float
    step_khz: float | None = None
    priority: int | None = None


class SettingsUpdate(BaseModel):
    gain: float | None = None
    squelch_offset: float | None = None
    min_signal_strength: float | None = None
    dwell_time_ms: float | None = None
    fft_size: int | None = None
    scan_profiles: list[str] | None = None
    scan_ranges: list[ScanRangeUpdate] | None = None
    # Audio settings
    sample_rate: int | None = None
    recording_dir: str | None = None
    # Logging settings
    log_level: str | None = None
    # Device role settings
    scanner_device: str | None = None
    tuner_device: str | None = None
    # Audio mode
    audio_mode: Literal["auto", "gqrx", "pcm_stream"] | None = None


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

    if data.scan_profiles is not None:
        config["scanner"]["scan_profiles"] = [str(profile) for profile in data.scan_profiles]
        changed.append(f"scan_profiles={len(data.scan_profiles)} profiles")

    if data.scan_ranges is not None:
        config["scanner"]["sweep_ranges"] = [
            {
                "label": r.label,
                "start_mhz": r.start_mhz,
                "end_mhz": r.end_mhz,
                **({"step_khz": r.step_khz} if r.step_khz is not None else {}),
                **({"priority": r.priority} if r.priority is not None else {}),
            }
            for r in data.scan_ranges
        ]
        changed.append(f"scan_ranges={len(data.scan_ranges)} ranges")

    if data.sample_rate is not None:
        config.setdefault("audio", {})["sample_rate"] = data.sample_rate
        changed.append(f"sample_rate={data.sample_rate}")

    if data.recording_dir is not None:
        config.setdefault("audio", {})["recording_dir"] = data.recording_dir
        changed.append(f"recording_dir={data.recording_dir}")

    if data.log_level is not None:
        config.setdefault("logging", {})["level"] = data.log_level
        logging.getLogger().setLevel(getattr(logging, data.log_level.upper(), logging.INFO))
        changed.append(f"log_level={data.log_level}")

    # Device roles: treat 'none' / '' as "clear the preference" so we never
    # write the literal string 'none' into user_settings.yaml.
    if data.scanner_device is not None:
        devices_cfg = config.setdefault("devices", {})
        if data.scanner_device in ("", "none"):
            devices_cfg.pop("scanner_device", None)
            changed.append("scanner_device=<cleared>")
        else:
            devices_cfg["scanner_device"] = data.scanner_device
            changed.append(f"scanner_device={data.scanner_device}")

    if data.tuner_device is not None:
        devices_cfg = config.setdefault("devices", {})
        if data.tuner_device in ("", "none"):
            devices_cfg.pop("tuner_device", None)
            changed.append("tuner_device=<cleared>")
        else:
            devices_cfg["tuner_device"] = data.tuner_device
            changed.append(f"tuner_device={data.tuner_device}")

    if data.audio_mode is not None:
        config["scanner"]["audio_mode"] = data.audio_mode
        changed.append(f"audio_mode={data.audio_mode}")

    # Persist settings to user config file so they survive restarts
    if changed:
        _persist_user_config(config)

    return {"status": "updated", "changed": changed}


_USER_CONFIG_PATH = Path("config/user_settings.yaml")


def _persist_user_config(config: dict) -> None:
    """Write the user-customizable settings to a YAML file."""
    devices_cfg = config.get("devices", {})
    scanner_device = devices_cfg.get("scanner_device")
    tuner_device = devices_cfg.get("tuner_device")
    # Guard against a literal 'none' sneaking into the file via older clients.
    if scanner_device in ("", "none"):
        scanner_device = None
    if tuner_device in ("", "none"):
        tuner_device = None
    user_cfg = {
        "devices": {
            "gain": devices_cfg.get("gain", 40),
            "scanner_device": scanner_device,
            "tuner_device": tuner_device,
        },
        "scanner": {
            "squelch_offset": config["scanner"].get("squelch_offset", 10),
            "min_signal_strength": config["scanner"].get("min_signal_strength", -50),
            "dwell_time_ms": config["scanner"].get("dwell_time_ms", 50),
            "fft_size": config["scanner"].get("fft_size", 1024),
            "scan_profiles": resolve_scan_profile_keys(config.get("scanner", {})),
            "sweep_ranges": config["scanner"].get("sweep_ranges", []),
            "audio_mode": config["scanner"].get("audio_mode", "auto"),
        },
        "audio": {
            "sample_rate": config.get("audio", {}).get("sample_rate", 48000),
            "recording_dir": config.get("audio", {}).get("recording_dir", "data/recordings"),
        },
        "logging": {
            "level": config.get("logging", {}).get("level", "INFO"),
        },
    }
    # Remove None values from devices
    user_cfg["devices"] = {k: v for k, v in user_cfg["devices"].items() if v is not None}
    try:
        _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_CONFIG_PATH, "w") as f:
            yaml.dump(user_cfg, f, default_flow_style=False, sort_keys=False)
        logger.info("Settings persisted to %s", _USER_CONFIG_PATH)
    except Exception as e:
        logger.error("Failed to persist settings: %s", e)
