import asyncio
import logging

logger = logging.getLogger(__name__)


class GqrxConnectionError(Exception):
    """Raised when connection to gqrx fails or is lost."""


class GqrxClient:
    """Async TCP client for gqrx's rigctl remote control protocol."""

    def __init__(self, host: str = "localhost", port: int = 7356, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            logger.info("Connected to gqrx at %s:%d", self.host, self.port)
        except (OSError, asyncio.TimeoutError) as e:
            raise GqrxConnectionError(f"Cannot connect to gqrx at {self.host}:{self.port}: {e}") from e

    async def disconnect(self) -> None:
        if self._writer is not None:
            try:
                self._writer.write(b"q\n")
                await self._writer.drain()
            except Exception:
                pass
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
            logger.info("Disconnected from gqrx")

    async def _send_command(self, cmd: str) -> str:
        if not self.is_connected:
            raise GqrxConnectionError("Not connected to gqrx")
        try:
            logger.debug("gqrx >> %s", cmd)
            self._writer.write(f"{cmd}\n".encode())
            await self._writer.drain()
            line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self.timeout,
            )
            resp = line.decode().strip()
            logger.debug("gqrx << %s", resp)
            return resp
        except (OSError, asyncio.TimeoutError) as e:
            self._writer = None
            self._reader = None
            raise GqrxConnectionError(f"Command '{cmd}' failed: {e}") from e

    async def get_frequency(self) -> int:
        resp = await self._send_command("f")
        return int(resp)

    async def set_frequency(self, freq_hz: int) -> None:
        resp = await self._send_command(f"F {freq_hz}")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"set_frequency failed: {resp}")

    async def get_signal_strength(self) -> float:
        resp = await self._send_command("l STRENGTH")
        return float(resp)

    async def set_mode(self, mode: str, passband: int = 0) -> None:
        resp = await self._send_command(f"M {mode} {passband}")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"set_mode failed: {resp}")

    async def get_mode(self) -> tuple[str, int]:
        resp = await self._send_command("m")
        passband_line = await asyncio.wait_for(
            self._reader.readline(),
            timeout=self.timeout,
        )
        return resp, int(passband_line.decode().strip())

    async def set_squelch(self, level_dbfs: float) -> None:
        resp = await self._send_command(f"L SQL {level_dbfs}")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"set_squelch failed: {resp}")

    async def get_squelch(self) -> float:
        resp = await self._send_command("l SQL")
        return float(resp)

    async def set_audio_gain(self, gain_db: float) -> None:
        resp = await self._send_command(f"L AF {gain_db}")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"set_audio_gain failed: {resp}")

    async def start_recording(self) -> None:
        resp = await self._send_command("U RECORD 1")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"start_recording failed: {resp}")

    async def stop_recording(self) -> None:
        resp = await self._send_command("U RECORD 0")
        if resp != "RPRT 0":
            raise GqrxConnectionError(f"stop_recording failed: {resp}")
