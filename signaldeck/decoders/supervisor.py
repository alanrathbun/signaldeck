import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

@dataclass
class ProcessConfig:
    command: list[str]
    name: str
    env: dict[str, str] = field(default_factory=dict)
    stdin_pipe: bool = False

class ManagedProcess:
    def __init__(self, config: ProcessConfig, process: asyncio.subprocess.Process) -> None:
        self.config = config
        self.process = process
        self._reader_task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.process.returncode is None

    async def start_reading(self, on_output: Callable[[str], Awaitable[None]]) -> None:
        self._reader_task = asyncio.create_task(self._read_loop(on_output))

    async def _read_loop(self, on_output: Callable[[str], Awaitable[None]]) -> None:
        try:
            while self.process.returncode is None:
                line = await self.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                if decoded:
                    await on_output(decoded)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Read error on %s: %s", self.config.name, e)

    async def stop(self) -> None:
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

class ProcessSupervisor:
    def __init__(self) -> None:
        self._processes: dict[str, ManagedProcess] = {}

    async def run_once(self, config: ProcessConfig, on_output: Callable[[str], Awaitable[None]], timeout: float = 30.0) -> int:
        process = await asyncio.create_subprocess_exec(
            *config.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if config.stdin_pipe else None,
            env={**dict(__import__("os").environ), **config.env} if config.env else None,
        )
        managed = ManagedProcess(config, process)
        await managed.start_reading(on_output)
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await managed.stop()
        return process.returncode or 0

    async def start_process(self, config: ProcessConfig, on_output: Callable[[str], Awaitable[None]]) -> ManagedProcess:
        if config.name in self._processes:
            existing = self._processes[config.name]
            if existing.running:
                await existing.stop()
        process = await asyncio.create_subprocess_exec(
            *config.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if config.stdin_pipe else None,
            env={**dict(__import__("os").environ), **config.env} if config.env else None,
        )
        managed = ManagedProcess(config, process)
        await managed.start_reading(on_output)
        self._processes[config.name] = managed
        return managed

    def is_running(self, name: str) -> bool:
        if name not in self._processes:
            return False
        return self._processes[name].running

    async def stop_process(self, name: str) -> None:
        if name not in self._processes:
            return
        managed = self._processes.pop(name)
        await managed.stop()

    async def stop_all(self) -> None:
        names = list(self._processes.keys())
        for name in names:
            await self.stop_process(name)

    async def write_stdin(self, name: str, data: bytes) -> None:
        if name not in self._processes:
            return
        managed = self._processes[name]
        if managed.process.stdin:
            managed.process.stdin.write(data)
            await managed.process.stdin.drain()
