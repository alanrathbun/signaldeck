from fastapi import APIRouter

from signaldeck.api.server import get_config

router = APIRouter(tags=["scanner"])

# Scanner state (in-memory, managed by the CLI start command)
_scanner_state = {
    "status": "running",  # set by CLI on startup
    "mode": "sweep",
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
