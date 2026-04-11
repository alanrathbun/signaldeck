import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from signaldeck.api.server import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


def _log_dir() -> Path:
    config = get_config()
    return Path(config.get("logging", {}).get("log_dir", "data/logs"))


def _session_log() -> str | None:
    config = get_config()
    return config.get("_session_log_file")


@router.get("")
async def list_logs():
    """List available log files, newest first."""
    log_path = _log_dir()
    if not log_path.exists():
        return []
    files = sorted(log_path.glob("signaldeck-*.log"), reverse=True)
    return [
        {
            "name": f.name,
            "size": f.stat().st_size,
            "created": f.stat().st_mtime,
        }
        for f in files
    ]


@router.get("/current")
async def get_current_log():
    """Return contents of the current session log."""
    session_log = _session_log()
    if not session_log or not Path(session_log).exists():
        raise HTTPException(status_code=404, detail="No active session log")
    return {"name": Path(session_log).name, "content": Path(session_log).read_text()}


@router.get("/{filename}")
async def get_log(filename: str):
    """Return contents of a specific log file."""
    log_path = _log_dir() / filename
    if not log_path.resolve().is_relative_to(_log_dir().resolve()):
        raise HTTPException(status_code=404, detail="Log file not found")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"name": filename, "content": log_path.read_text()}


@router.delete("")
async def delete_logs():
    """Delete all log files except the current session log."""
    log_path = _log_dir()
    session_log = _session_log()
    session_name = Path(session_log).name if session_log else None
    deleted = 0
    for f in log_path.glob("signaldeck-*.log"):
        if f.name != session_name:
            f.unlink()
            deleted += 1
    return {"deleted": deleted}
