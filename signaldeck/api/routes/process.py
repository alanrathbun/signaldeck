"""Process lifecycle endpoints.

Reports whether SignalDeck is running under a supervisor (systemd --user
specifically) and lets the dashboard Stop / Start / Restart the service
through that supervisor.

Why a supervisor is required:
    SignalDeck embeds its uvicorn web server in the same asyncio loop that
    owns the SDR scan loop. "Restart from inside the dashboard" is therefore
    a contradiction: the process that would need to fork+exec a new copy is
    also the process that serves the HTTP response acknowledging the
    restart. A supervisor (systemd --user) owns the lifecycle so we can ask
    it to stop/start us and actually survive the transition.

Control endpoints (start/stop/restart) are gated: either the caller is
authenticated via the existing auth middleware, or the request arrived from
a loopback address. This keeps the default single-user setup convenient
without silently handing process control to anyone on the LAN if the user
binds the dashboard to 0.0.0.0.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from signaldeck.api.server import get_auth_manager, get_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["process"])

_UNIT_NAME = "signaldeck.service"

# Cache the supervisor probe briefly so the status-polling UI doesn't spawn
# a systemctl subprocess on every tick.
_supervisor_cache: dict = {"value": None, "expires": 0.0}
_SUPERVISOR_CACHE_TTL_S = 5.0


def _loopback(request: Request) -> bool:
    """Return True if the request came from a loopback address."""
    client = request.client
    if client is None:
        return False
    host = client.host
    if host is None:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        # Unix sockets or weird transports — treat as local.
        return host in ("", "localhost")


def _require_authorized(request: Request) -> None:
    """Allow the request if auth is on and the middleware let it through,
    or if it originated from loopback. Raise 403 otherwise."""
    if get_auth_manager() is not None:
        # AuthMiddleware already gated this request; if we got here the
        # caller is authenticated.
        return
    if _loopback(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Process control is only available from localhost when auth is "
            "disabled. Enable auth in config or call from the host running "
            "SignalDeck."
        ),
    )


async def _run_systemctl(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run `systemctl --user <args>` and return (rc, stdout, stderr)."""
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return 127, "", "systemctl not found"
    proc = await asyncio.create_subprocess_exec(
        systemctl, "--user", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"systemctl timed out after {timeout}s"
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _probe_supervisor() -> dict:
    """Return a dict describing the supervisor state for the UI.

    Keys:
        kind: "systemd-user" | "none"
        managed: bool — whether *our* pid is the MainPID of the unit
        unit: unit name (only when kind == "systemd-user")
        active_state, sub_state, load_state: raw systemd state strings
        main_pid: int | None — MainPID from systemd, if any
        reason: str — human-readable explanation when managed is False
    """
    now = time.monotonic()
    if _supervisor_cache["value"] is not None and _supervisor_cache["expires"] > now:
        return _supervisor_cache["value"]

    result: dict = {
        "kind": "none",
        "managed": False,
        "unit": None,
        "active_state": None,
        "sub_state": None,
        "load_state": None,
        "main_pid": None,
        "reason": "",
    }

    rc, stdout, stderr = await _run_systemctl(
        "show", _UNIT_NAME,
        "-p", "LoadState",
        "-p", "ActiveState",
        "-p", "SubState",
        "-p", "MainPID",
    )
    if rc == 127:
        result["reason"] = "systemctl not found"
        _supervisor_cache.update(value=result, expires=now + _SUPERVISOR_CACHE_TTL_S)
        return result
    if rc != 0:
        # systemctl --user can fail with rc 1 if no user dbus is reachable.
        result["reason"] = stderr.strip() or f"systemctl exited {rc}"
        _supervisor_cache.update(value=result, expires=now + _SUPERVISOR_CACHE_TTL_S)
        return result

    props = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()

    load_state = props.get("LoadState") or None
    active_state = props.get("ActiveState") or None
    sub_state = props.get("SubState") or None
    try:
        main_pid = int(props.get("MainPID", "0")) or None
    except ValueError:
        main_pid = None

    result["load_state"] = load_state
    result["active_state"] = active_state
    result["sub_state"] = sub_state
    result["main_pid"] = main_pid

    if load_state != "loaded":
        result["reason"] = (
            f"{_UNIT_NAME} is not installed "
            f"(see deploy/systemd/README.md)"
        )
        _supervisor_cache.update(value=result, expires=now + _SUPERVISOR_CACHE_TTL_S)
        return result

    result["kind"] = "systemd-user"
    result["unit"] = _UNIT_NAME

    # We're "managed" only if the running pid matches systemd's MainPID for
    # the unit. That rules out the case where someone has the unit installed
    # but is currently running SignalDeck by hand from a shell.
    our_pid = os.getpid()
    if main_pid == our_pid:
        result["managed"] = True
    else:
        result["reason"] = (
            f"{_UNIT_NAME} is installed but this process (pid {our_pid}) is "
            f"not its MainPID ({main_pid}). Started by hand?"
        )

    _supervisor_cache.update(value=result, expires=now + _SUPERVISOR_CACHE_TTL_S)
    return result


def _invalidate_supervisor_cache() -> None:
    _supervisor_cache.update(value=None, expires=0.0)


def _uptime_seconds() -> float | None:
    start_time = get_config().get("_start_time")
    if not start_time:
        return None
    try:
        started = datetime.fromisoformat(start_time)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - started
    return max(0.0, delta.total_seconds())


def _caller_may_control(request: Request) -> tuple[bool, str]:
    """Mirror of _require_authorized that returns a reason instead of raising.

    Used by /process/status so the UI can grey out the control buttons for
    callers who would receive a 403 on the control endpoints anyway.
    """
    if get_auth_manager() is not None:
        # AuthMiddleware would have already rejected an unauthenticated call
        # before it reached this handler.
        return True, ""
    if _loopback(request):
        return True, ""
    return False, (
        "Process control is restricted to localhost when auth is disabled."
    )


@router.get("/process/status")
async def process_status(request: Request):
    """Lightweight status for the Service card on the dashboard.

    Safe to poll — caches the systemd probe for a few seconds and returns
    immediately thereafter.
    """
    supervisor = await _probe_supervisor()
    managed = supervisor.get("managed", False)
    authorized, gate_reason = _caller_may_control(request)
    return {
        "pid": os.getpid(),
        "uptime_seconds": _uptime_seconds(),
        "start_time": get_config().get("_start_time"),
        "supervisor": supervisor,
        # Convenience booleans so the UI doesn't have to know systemd shapes.
        "running": True,
        "can_control": managed and authorized,
        "control_reason": (
            ""
            if managed and authorized
            else (gate_reason if managed else supervisor.get("reason", ""))
        ),
    }


class ProcessAction(BaseModel):
    # reserved for future use (e.g., confirm=True)
    confirm: bool = False


async def _require_managed() -> None:
    supervisor = await _probe_supervisor()
    if not supervisor.get("managed"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "SignalDeck is not managed by systemd. Install "
                    "deploy/systemd/signaldeck.service to enable process "
                    "controls."
                ),
                "supervisor": supervisor,
            },
        )


async def _fire_and_forget_systemctl(verb: str) -> None:
    """Run systemctl with a short-lived wait and swallow the result.

    stop/restart will tear this process down, so the HTTP response may not
    make it back to the client. That's expected; the frontend treats a
    connection drop during restart as success and polls status back.
    """
    # Invalidate cache so the next status poll reflects the new state.
    _invalidate_supervisor_cache()
    rc, stdout, stderr = await _run_systemctl(verb, _UNIT_NAME, timeout=8.0)
    if rc != 0:
        logger.error(
            "systemctl --user %s %s failed rc=%s stderr=%s",
            verb, _UNIT_NAME, rc, stderr.strip(),
        )
    else:
        logger.info("systemctl --user %s %s ok", verb, _UNIT_NAME)


@router.post("/process/start")
async def process_start(request: Request, data: ProcessAction | None = None):
    _require_authorized(request)
    await _require_managed()
    # Starting a unit that's already active is a no-op at the systemd layer,
    # which is the behavior we want from the button.
    asyncio.create_task(_fire_and_forget_systemctl("start"))
    return {"status": "accepted", "action": "start"}


@router.post("/process/stop")
async def process_stop(request: Request, data: ProcessAction | None = None):
    _require_authorized(request)
    await _require_managed()
    asyncio.create_task(_fire_and_forget_systemctl("stop"))
    return {"status": "accepted", "action": "stop"}


@router.post("/process/restart")
async def process_restart(request: Request, data: ProcessAction | None = None):
    _require_authorized(request)
    await _require_managed()
    asyncio.create_task(_fire_and_forget_systemctl("restart"))
    return {"status": "accepted", "action": "restart"}
