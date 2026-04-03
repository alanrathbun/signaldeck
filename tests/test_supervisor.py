import asyncio
import pytest
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

async def test_supervisor_run_and_capture_stdout():
    config = ProcessConfig(command=["echo", "hello\nworld"], name="test_echo")
    supervisor = ProcessSupervisor()
    lines = []
    async def on_line(line: str):
        lines.append(line)
    await supervisor.run_once(config, on_output=on_line)
    assert any("hello" in l for l in lines)

async def test_supervisor_long_running_start_stop():
    config = ProcessConfig(
        command=["python3", "-u", "-c",
                 "import time, sys\nfor i in range(100):\n    print(f'line {i}', flush=True)\n    time.sleep(0.1)\n"],
        name="test_counter",
    )
    supervisor = ProcessSupervisor()
    lines = []
    async def on_line(line: str):
        lines.append(line)
    await supervisor.start_process(config, on_output=on_line)
    await asyncio.sleep(0.5)
    await supervisor.stop_process("test_counter")
    assert len(lines) >= 3
    assert "line 0" in lines[0]

async def test_supervisor_process_not_found():
    supervisor = ProcessSupervisor()
    await supervisor.stop_process("nonexistent")

async def test_supervisor_is_running():
    config = ProcessConfig(command=["sleep", "10"], name="test_sleep")
    supervisor = ProcessSupervisor()
    assert not supervisor.is_running("test_sleep")
    await supervisor.start_process(config, on_output=lambda l: None)
    assert supervisor.is_running("test_sleep")
    await supervisor.stop_process("test_sleep")
    await asyncio.sleep(0.1)
    assert not supervisor.is_running("test_sleep")

async def test_supervisor_stop_all():
    supervisor = ProcessSupervisor()
    for i in range(3):
        config = ProcessConfig(command=["sleep", "10"], name=f"proc_{i}")
        await supervisor.start_process(config, on_output=lambda l: None)
    assert sum(1 for i in range(3) if supervisor.is_running(f"proc_{i}")) == 3
    await supervisor.stop_all()
    await asyncio.sleep(0.1)
    assert sum(1 for i in range(3) if supervisor.is_running(f"proc_{i}")) == 0
