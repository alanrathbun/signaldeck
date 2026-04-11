from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def build_gqrx_command(
    command: list[str] | None = None,
    config_path: str | None = None,
) -> list[str]:
    """Build the gqrx startup command."""
    cmd = list(command) if command else [shutil.which("gqrx") or "gqrx"]
    if config_path:
        cfg = Path(os.path.expanduser(config_path))
        if cfg.exists() and "-c" not in cmd and "--conf" not in cmd:
            cmd.extend(["-c", str(cfg)])
    return cmd


async def wait_for_gqrx(
    host: str,
    port: int,
    *,
    timeout_s: float = 12.0,
    poll_interval_s: float = 0.5,
    probe_fn: Callable[[], asyncio.Future | None] | None = None,
) -> bool:
    """Wait for gqrx rigctl to begin responding."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if probe_fn is not None:
            if await probe_fn():
                return True
        else:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=1.0,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return True
            except Exception:
                pass
        await asyncio.sleep(poll_interval_s)
    return False


async def ensure_gqrx_running(
    host: str,
    port: int,
    *,
    auto_start: bool = True,
    command: list[str] | None = None,
    config_path: str | None = None,
    startup_timeout_s: float = 12.0,
    poll_interval_s: float = 0.5,
    probe_fn: Callable[[], asyncio.Future | None] | None = None,
    spawn_fn: Callable[[list[str]], subprocess.Popen] | None = None,
) -> bool:
    """Start local gqrx if needed and wait for the rigctl socket.

    Returns True when SignalDeck launched a new gqrx process.
    """
    if probe_fn is not None and await probe_fn():
        return False

    if not auto_start or host not in _LOCAL_HOSTS:
        return False

    cmd = build_gqrx_command(command=command, config_path=config_path)
    logger.info("Starting gqrx: %s", " ".join(cmd))

    if spawn_fn is not None:
        proc = spawn_fn(cmd)
    else:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.warning("Could not start gqrx: %s", exc)
            return False

    ready = await wait_for_gqrx(
        host,
        port,
        timeout_s=startup_timeout_s,
        poll_interval_s=poll_interval_s,
        probe_fn=probe_fn,
    )
    if ready:
        return True

    if proc.poll() is not None:
        logger.warning("gqrx exited during startup with status %s", proc.returncode)
    else:
        logger.warning("gqrx did not open %s:%d within %.1fs", host, port, startup_timeout_s)
    return False
