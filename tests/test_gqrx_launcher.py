import asyncio
from pathlib import Path

import pytest

from signaldeck.engine.gqrx_launcher import build_gqrx_command, ensure_gqrx_running


def test_build_gqrx_command_adds_config(tmp_path: Path):
    conf = tmp_path / "gqrx.conf"
    conf.write_text("[remote_control]\nenabled=true\n")
    cmd = build_gqrx_command(command=["gqrx"], config_path=str(conf))
    assert cmd == ["gqrx", "-c", str(conf)]


@pytest.mark.asyncio
async def test_ensure_gqrx_running_skips_when_probe_already_ready():
    calls = []

    async def probe():
        calls.append("probe")
        return True

    started = await ensure_gqrx_running(
        "localhost",
        7356,
        probe_fn=probe,
        spawn_fn=lambda cmd: (_ for _ in ()).throw(RuntimeError("should not spawn")),
    )
    assert started is False
    assert calls == ["probe"]


@pytest.mark.asyncio
async def test_ensure_gqrx_running_starts_local_process():
    class DummyProc:
        returncode = None

        def poll(self):
            return None

    state = {"ready": False, "spawned": None, "probes": 0}

    async def probe():
        state["probes"] += 1
        if state["probes"] >= 2:
            state["ready"] = True
        return state["ready"]

    def spawn(cmd):
        state["spawned"] = cmd
        return DummyProc()

    started = await ensure_gqrx_running(
        "localhost",
        7356,
        command=["gqrx"],
        config_path="/tmp/missing.conf",
        startup_timeout_s=1.0,
        poll_interval_s=0.01,
        probe_fn=probe,
        spawn_fn=spawn,
    )
    assert started is True
    assert state["spawned"] == ["gqrx"]


@pytest.mark.asyncio
async def test_ensure_gqrx_running_does_not_start_remote_host():
    spawned = False

    async def probe():
        return False

    def spawn(cmd):
        nonlocal spawned
        spawned = True
        raise AssertionError("should not spawn")

    started = await ensure_gqrx_running(
        "192.168.1.10",
        7356,
        probe_fn=probe,
        spawn_fn=spawn,
    )
    assert started is False
    assert spawned is False
