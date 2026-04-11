# gqrx Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add gqrx as an alternative SDR backend controlled via TCP rigctl protocol, supporting both sweep and bookmark scanning modes.

**Architecture:** A `GqrxClient` handles the raw TCP/rigctl protocol. A `GqrxDevice` wraps it to match the existing device interface. The scanner gets new methods for strength-based scanning. The main loop detects which device type is active and dispatches accordingly.

**Tech Stack:** Python asyncio (TCP streams), existing pytest + mock patterns, no new dependencies.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `signaldeck/engine/gqrx_client.py` | Async TCP client for rigctl protocol |
| Create | `signaldeck/engine/gqrx_device.py` | Device adapter wrapping GqrxClient |
| Create | `tests/test_gqrx_client.py` | GqrxClient unit tests with mock TCP server |
| Create | `tests/test_gqrx_device.py` | GqrxDevice unit tests |
| Create | `tests/test_scanner_gqrx.py` | strength_sweep_once and bookmark_scan_once tests |
| Modify | `signaldeck/engine/device_manager.py` | Add gqrx discovery and open logic |
| Modify | `signaldeck/engine/scanner.py` | Add strength_sweep_once, bookmark_scan_once |
| Modify | `signaldeck/main.py` | Detect gqrx device, dispatch to correct scan method |
| Modify | `config/default.yaml` | Add gqrx config keys |
| Modify | `tests/test_device_manager.py` | Test gqrx discovery and open |

---

### Task 1: GqrxClient — rigctl TCP protocol

**Files:**
- Create: `signaldeck/engine/gqrx_client.py`
- Create: `tests/test_gqrx_client.py`

- [ ] **Step 1: Write test for connect and get_frequency**

```python
# tests/test_gqrx_client.py
import asyncio
import pytest
from signaldeck.engine.gqrx_client import GqrxClient


@pytest.fixture
def mock_gqrx_server():
    """A minimal TCP server that speaks rigctl protocol."""
    responses = {}
    server = None

    class Protocol:
        def __init__(self):
            self.transport = None

        def connection_made(self, transport):
            self.transport = transport

        def data_received(self, data):
            cmd = data.decode().strip()
            if cmd in responses:
                self.transport.write((responses[cmd] + "\n").encode())
            else:
                self.transport.write(b"RPRT 1\n")

    async def start(port, resp_map):
        nonlocal server, responses
        responses = resp_map
        loop = asyncio.get_event_loop()
        server = await loop.create_server(Protocol, "127.0.0.1", port)
        return server

    async def stop():
        nonlocal server
        if server:
            server.close()
            await server.wait_closed()

    return start, stop


@pytest.mark.asyncio
async def test_connect_and_get_frequency(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17356, {"f": "162400000"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17356)
        await client.connect()
        assert client.is_connected

        freq = await client.get_frequency()
        assert freq == 162400000

        await client.disconnect()
        assert not client.is_connected
    finally:
        await stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_client.py::test_connect_and_get_frequency -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'signaldeck.engine.gqrx_client'`

- [ ] **Step 3: Implement GqrxClient with connect, disconnect, get_frequency**

```python
# signaldeck/engine/gqrx_client.py
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
            self._writer.write(f"{cmd}\n".encode())
            await self._writer.drain()
            line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self.timeout,
            )
            return line.decode().strip()
        except (OSError, asyncio.TimeoutError) as e:
            self._writer = None
            self._reader = None
            raise GqrxConnectionError(f"Command '{cmd}' failed: {e}") from e

    async def get_frequency(self) -> int:
        resp = await self._send_command("f")
        return int(resp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_client.py::test_connect_and_get_frequency -v`
Expected: PASS

- [ ] **Step 5: Write tests for set_frequency, get_signal_strength, set_mode, get_mode**

Add to `tests/test_gqrx_client.py`:

```python
@pytest.mark.asyncio
async def test_set_frequency(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17357, {"F 162400000": "RPRT 0"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17357)
        await client.connect()
        await client.set_frequency(162400000)  # should not raise
        await client.disconnect()
    finally:
        await stop()


@pytest.mark.asyncio
async def test_get_signal_strength(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17358, {"l STRENGTH": "-42.5"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17358)
        await client.connect()
        strength = await client.get_signal_strength()
        assert strength == pytest.approx(-42.5)
        await client.disconnect()
    finally:
        await stop()


@pytest.mark.asyncio
async def test_set_and_get_mode(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17359, {"M FM 0": "RPRT 0", "m": "FM\n12500"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17359)
        await client.connect()
        await client.set_mode("FM")  # should not raise
        # Note: get_mode reads two lines (mode, passband)
        mode, passband = await client.get_mode()
        assert mode == "FM"
        assert passband == 12500
        await client.disconnect()
    finally:
        await stop()


@pytest.mark.asyncio
async def test_squelch(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17360, {"L SQL -40.0": "RPRT 0", "l SQL": "-40.0"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17360)
        await client.connect()
        await client.set_squelch(-40.0)
        level = await client.get_squelch()
        assert level == pytest.approx(-40.0)
        await client.disconnect()
    finally:
        await stop()


@pytest.mark.asyncio
async def test_recording(mock_gqrx_server):
    start, stop = mock_gqrx_server
    await start(17361, {"U RECORD 1": "RPRT 0", "U RECORD 0": "RPRT 0"})
    try:
        client = GqrxClient(host="127.0.0.1", port=17361)
        await client.connect()
        await client.start_recording()
        await client.stop_recording()
        await client.disconnect()
    finally:
        await stop()


@pytest.mark.asyncio
async def test_connection_error():
    client = GqrxClient(host="127.0.0.1", port=19999, timeout=0.5)
    with pytest.raises(GqrxConnectionError):
        await client.connect()


@pytest.mark.asyncio
async def test_command_when_disconnected():
    client = GqrxClient(host="127.0.0.1", port=19999)
    with pytest.raises(GqrxConnectionError):
        await client.get_frequency()
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_client.py -v`
Expected: FAIL — missing methods

- [ ] **Step 7: Implement remaining GqrxClient methods**

Add to `signaldeck/engine/gqrx_client.py`, inside the `GqrxClient` class:

```python
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
        # gqrx returns mode on first line, passband on second
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
```

- [ ] **Step 8: Run all GqrxClient tests**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_client.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add signaldeck/engine/gqrx_client.py tests/test_gqrx_client.py
git commit -m "feat: add GqrxClient rigctl TCP protocol client"
```

---

### Task 2: GqrxDevice — Device Adapter

**Files:**
- Create: `signaldeck/engine/gqrx_device.py`
- Create: `tests/test_gqrx_device.py`

- [ ] **Step 1: Write tests for GqrxDevice**

```python
# tests/test_gqrx_device.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from signaldeck.engine.gqrx_device import GqrxDevice
from signaldeck.engine.device_manager import DeviceInfo


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.is_connected = True
    return client


@pytest.fixture
def device(mock_client):
    info = DeviceInfo(label="gqrx @ localhost:7356", driver="gqrx", serial="localhost:7356")
    return GqrxDevice(mock_client, info)


def test_is_gqrx(device):
    assert device.is_gqrx is True


def test_tune_calls_set_frequency(device, mock_client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(device.tune(162_400_000))
    mock_client.set_frequency.assert_called_once_with(162400000)


def test_noop_methods_do_not_raise(device):
    """set_gain, set_sample_rate, start_stream, stop_stream are no-ops."""
    device.set_gain(40)
    device.set_sample_rate(2_000_000)
    device.start_stream()
    device.stop_stream()


def test_read_samples_returns_none(device):
    assert device.read_samples(1024) is None


def test_get_signal_strength(device, mock_client):
    import asyncio
    mock_client.get_signal_strength.return_value = -42.5
    strength = asyncio.get_event_loop().run_until_complete(device.get_signal_strength())
    assert strength == -42.5


def test_close_disconnects(device, mock_client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(device.close())
    mock_client.disconnect.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_device.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GqrxDevice**

```python
# signaldeck/engine/gqrx_device.py
import logging
from signaldeck.engine.device_manager import DeviceInfo

logger = logging.getLogger(__name__)


class GqrxDevice:
    """SDR device adapter that controls gqrx via its rigctl TCP client."""

    def __init__(self, client, info: DeviceInfo) -> None:
        self._client = client
        self.info = info

    @property
    def is_gqrx(self) -> bool:
        return True

    async def tune(self, frequency_hz: float) -> None:
        await self._client.set_frequency(int(frequency_hz))
        logger.debug("gqrx tuned to %.6f MHz", frequency_hz / 1e6)

    def set_gain(self, gain_db: float) -> None:
        pass  # gqrx manages gain internally

    def set_sample_rate(self, rate: float) -> None:
        pass  # gqrx manages sample rate internally

    def start_stream(self) -> None:
        pass  # no IQ stream access

    def stop_stream(self) -> None:
        pass  # no IQ stream access

    def read_samples(self, num_samples: int):
        return None  # no IQ access via rigctl

    async def get_signal_strength(self) -> float:
        return await self._client.get_signal_strength()

    async def set_mode(self, mode: str) -> None:
        await self._client.set_mode(mode)

    async def set_squelch(self, level: float) -> None:
        await self._client.set_squelch(level)

    async def start_recording(self) -> None:
        await self._client.start_recording()

    async def stop_recording(self) -> None:
        await self._client.stop_recording()

    async def close(self) -> None:
        await self._client.disconnect()
        logger.info("gqrx device %s closed", self.info.label)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_gqrx_device.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/engine/gqrx_device.py tests/test_gqrx_device.py
git commit -m "feat: add GqrxDevice adapter for gqrx rigctl interface"
```

---

### Task 3: DeviceManager — gqrx Discovery and Open

**Files:**
- Modify: `signaldeck/engine/device_manager.py`
- Modify: `tests/test_device_manager.py`

- [ ] **Step 1: Write tests for gqrx enumerate and open**

Add to `tests/test_device_manager.py`:

```python
@pytest.mark.asyncio
async def test_enumerate_detects_gqrx(tmp_path):
    """DeviceManager finds gqrx when it responds on the configured port."""
    import asyncio

    # Start a fake gqrx server that responds to "f"
    async def handle_client(reader, writer):
        data = await reader.readline()
        cmd = data.decode().strip()
        if cmd == "f":
            writer.write(b"162400000\n")
        else:
            writer.write(b"RPRT 1\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 17370)
    try:
        mgr = DeviceManager()
        devices = await mgr.enumerate_async(
            gqrx_auto_detect=True,
            gqrx_host="127.0.0.1",
            gqrx_port=17370,
            gqrx_instances=[],
        )
        gqrx_devs = [d for d in devices if d.driver == "gqrx"]
        assert len(gqrx_devs) == 1
        assert gqrx_devs[0].serial == "127.0.0.1:17370"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_enumerate_no_gqrx_when_unavailable():
    """DeviceManager skips gqrx gracefully when it's not running."""
    mgr = DeviceManager()
    devices = await mgr.enumerate_async(
        gqrx_auto_detect=True,
        gqrx_host="127.0.0.1",
        gqrx_port=19998,
        gqrx_instances=[],
    )
    gqrx_devs = [d for d in devices if d.driver == "gqrx"]
    assert len(gqrx_devs) == 0


@pytest.mark.asyncio
async def test_open_gqrx_device(tmp_path):
    """DeviceManager.open_gqrx returns a GqrxDevice."""
    import asyncio

    async def handle_client(reader, writer):
        while True:
            data = await reader.readline()
            if not data:
                break
            cmd = data.decode().strip()
            if cmd == "f":
                writer.write(b"162400000\n")
            elif cmd == "q":
                writer.close()
                break
            else:
                writer.write(b"RPRT 0\n")
            await writer.drain()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 17371)
    try:
        mgr = DeviceManager()
        device = await mgr.open_gqrx(host="127.0.0.1", port=17371)
        assert device.is_gqrx
        assert device.info.driver == "gqrx"
        await device.close()
    finally:
        server.close()
        await server.wait_closed()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_device_manager.py::test_enumerate_detects_gqrx -v`
Expected: FAIL — `DeviceManager has no attribute 'enumerate_async'`

- [ ] **Step 3: Add enumerate_async and open_gqrx to DeviceManager**

Add these methods to the `DeviceManager` class in `signaldeck/engine/device_manager.py`:

```python
    async def enumerate_async(
        self,
        gqrx_auto_detect: bool = True,
        gqrx_host: str = "localhost",
        gqrx_port: int = 7356,
        gqrx_instances: list[dict] | None = None,
    ) -> list[DeviceInfo]:
        """Discover SDR devices including gqrx instances."""
        devices = self.enumerate()  # existing SoapySDR discovery

        # Try auto-detecting gqrx on the default or configured host:port
        if gqrx_auto_detect:
            info = await self._probe_gqrx(gqrx_host, gqrx_port)
            if info:
                devices.append(info)

        # Check explicitly configured gqrx instances
        for inst in (gqrx_instances or []):
            host = inst.get("host", "localhost")
            port = inst.get("port", 7356)
            if host == gqrx_host and port == gqrx_port:
                continue  # already checked above
            info = await self._probe_gqrx(host, port)
            if info:
                devices.append(info)

        return devices

    async def _probe_gqrx(self, host: str, port: int) -> DeviceInfo | None:
        """Try connecting to a gqrx instance and return DeviceInfo if it responds."""
        import asyncio
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=1.0,
            )
            writer.write(b"f\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.readline(), timeout=1.0)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            # If we got a valid frequency back, gqrx is running
            int(resp.decode().strip())
            info = DeviceInfo(
                label=f"gqrx @ {host}:{port}",
                driver="gqrx",
                serial=f"{host}:{port}",
            )
            logger.info("Found gqrx at %s:%d", host, port)
            return info
        except Exception:
            return None

    async def open_gqrx(self, host: str = "localhost", port: int = 7356) -> "GqrxDevice":
        """Open a connection to a gqrx instance."""
        from signaldeck.engine.gqrx_client import GqrxClient
        from signaldeck.engine.gqrx_device import GqrxDevice

        client = GqrxClient(host=host, port=port)
        await client.connect()
        info = DeviceInfo(
            label=f"gqrx @ {host}:{port}",
            driver="gqrx",
            serial=f"{host}:{port}",
        )
        logger.info("Opened gqrx device at %s:%d", host, port)
        return GqrxDevice(client, info)
```

Also add this import at the top of the file (after existing imports):

```python
from __future__ import annotations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_device_manager.py -v`
Expected: all PASS (both old and new tests)

- [ ] **Step 5: Commit**

```bash
git add signaldeck/engine/device_manager.py tests/test_device_manager.py
git commit -m "feat: add gqrx auto-detection and connection to DeviceManager"
```

---

### Task 4: Scanner — Strength-Based Sweep and Bookmark Scan

**Files:**
- Modify: `signaldeck/engine/scanner.py`
- Create: `tests/test_scanner_gqrx.py`

- [ ] **Step 1: Write test for strength_sweep_once**

```python
# tests/test_scanner_gqrx.py
import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from signaldeck.engine.scanner import FrequencyScanner, ScanRange


def _make_mock_gqrx_device(strength_map: dict[float, float], default: float = -90.0):
    """Create a mock GqrxDevice that returns configured signal strengths.

    strength_map: {frequency_hz: strength_dbfs}
    """
    device = MagicMock()
    device.is_gqrx = True
    device.read_samples = MagicMock(return_value=None)
    device.set_sample_rate = MagicMock()
    device.start_stream = MagicMock()
    device.stop_stream = MagicMock()

    async def mock_tune(freq):
        device._current_freq = freq

    async def mock_strength():
        freq = getattr(device, "_current_freq", 0)
        # Find closest frequency in map
        if not strength_map:
            return default
        closest = min(strength_map.keys(), key=lambda f: abs(f - freq))
        if abs(closest - freq) < 100_000:  # within 100 kHz
            return strength_map[closest]
        return default

    device.tune = AsyncMock(side_effect=mock_tune)
    device.get_signal_strength = AsyncMock(side_effect=mock_strength)
    return device


@pytest.mark.asyncio
async def test_strength_sweep_detects_signals():
    """strength_sweep_once finds signals above threshold."""
    device = _make_mock_gqrx_device({
        100.0e6: -35.0,   # strong signal
        100.4e6: -45.0,   # medium signal
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,  # no delay in tests
    )
    signals = await scanner.strength_sweep_once()
    assert len(signals) == 2
    # Strongest first
    assert signals[0].peak_power > signals[1].peak_power


@pytest.mark.asyncio
async def test_strength_sweep_filters_weak_signals():
    """strength_sweep_once ignores signals below squelch."""
    device = _make_mock_gqrx_device({
        100.0e6: -85.0,  # barely above noise floor
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    signals = await scanner.strength_sweep_once()
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_strength_sweep_calls_fft_callback():
    """strength_sweep_once broadcasts power data to fft callback."""
    device = _make_mock_gqrx_device({100.0e6: -40.0})
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    callback_data = []

    async def on_fft(center_freq, sample_rate, power_db):
        callback_data.append((center_freq, power_db))

    await scanner.strength_sweep_once(fft_callback=on_fft)
    assert len(callback_data) > 0
    freq, power = callback_data[0]
    assert isinstance(power, np.ndarray)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner_gqrx.py -v`
Expected: FAIL — `FrequencyScanner has no attribute 'strength_sweep_once'`

- [ ] **Step 3: Implement strength_sweep_once**

Add to `FrequencyScanner` class in `signaldeck/engine/scanner.py`:

```python
    async def strength_sweep_once(self, fft_callback=None) -> list[DetectedSignal]:
        """Sweep by reading signal strength at each frequency (for gqrx backend).

        Instead of computing FFT from IQ samples, tunes to each frequency and
        reads a single signal strength value from the device.
        """
        all_signals: list[DetectedSignal] = []

        for scan_range in self._scan_ranges:
            freqs = scan_range.frequencies()
            strengths = np.full(len(freqs), -100.0)

            for i, freq in enumerate(freqs):
                await self._device.tune(freq)
                if self._dwell_time > 0:
                    await asyncio.sleep(self._dwell_time)
                strengths[i] = await self._device.get_signal_strength()

            # Broadcast the collected strengths as a power array for waterfall
            if fft_callback is not None:
                center = (scan_range.start_hz + scan_range.end_hz) / 2
                bandwidth = scan_range.end_hz - scan_range.start_hz
                await fft_callback(center, bandwidth, strengths)

            # Detect signals above noise floor + squelch offset
            noise_floor = float(np.median(strengths))
            threshold = noise_floor + self._squelch_offset

            for i, freq in enumerate(freqs):
                if strengths[i] > threshold:
                    all_signals.append(DetectedSignal(
                        frequency_hz=freq,
                        bandwidth_hz=scan_range.step_hz,
                        peak_power=float(strengths[i]),
                        avg_power=float(strengths[i]),
                        bin_start=i,
                        bin_end=i + 1,
                    ))

        all_signals.sort(key=lambda s: s.peak_power, reverse=True)
        return all_signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner_gqrx.py -v`
Expected: all PASS

- [ ] **Step 5: Write test for bookmark_scan_once**

Add to `tests/test_scanner_gqrx.py`:

```python
from signaldeck.storage.models import Bookmark
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_bookmark_scan_detects_active():
    """bookmark_scan_once detects active bookmarked frequencies."""
    device = _make_mock_gqrx_device({
        162.400e6: -30.0,  # active
        162.475e6: -85.0,  # inactive
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[],  # not used in bookmark mode
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    bookmarks = [
        Bookmark(frequency=162.400e6, label="NOAA Weather", modulation="FM",
                 decoder="weather", priority=5, camp_on_active=False),
        Bookmark(frequency=162.475e6, label="NOAA 2", modulation="FM",
                 decoder="weather", priority=3, camp_on_active=False),
    ]
    signals = await scanner.bookmark_scan_once(bookmarks)
    assert len(signals) == 1
    assert signals[0].frequency_hz == 162.400e6


@pytest.mark.asyncio
async def test_bookmark_scan_empty_bookmarks():
    """bookmark_scan_once returns empty list with no bookmarks."""
    device = _make_mock_gqrx_device({})
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    signals = await scanner.bookmark_scan_once([])
    assert signals == []
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner_gqrx.py::test_bookmark_scan_detects_active -v`
Expected: FAIL — `FrequencyScanner has no attribute 'bookmark_scan_once'`

- [ ] **Step 7: Implement bookmark_scan_once**

Add to `FrequencyScanner` class in `signaldeck/engine/scanner.py`:

```python
    async def bookmark_scan_once(self, bookmarks, fft_callback=None) -> list[DetectedSignal]:
        """Scan a list of bookmarked frequencies by reading signal strength.

        Args:
            bookmarks: List of Bookmark objects to scan.
            fft_callback: Optional async callback(center_freq, bandwidth, power_array).

        Returns:
            List of DetectedSignal for active bookmarks.
        """
        if not bookmarks:
            return []

        signals: list[DetectedSignal] = []
        freqs = np.array([b.frequency for b in bookmarks])
        strengths = np.full(len(bookmarks), -100.0)

        for i, bk in enumerate(bookmarks):
            await self._device.tune(bk.frequency)
            if self._dwell_time > 0:
                await asyncio.sleep(self._dwell_time)
            strengths[i] = await self._device.get_signal_strength()

        # Broadcast for waterfall
        if fft_callback is not None and len(bookmarks) > 0:
            center = (freqs.min() + freqs.max()) / 2
            bandwidth = freqs.max() - freqs.min() if len(freqs) > 1 else 1e6
            await fft_callback(center, bandwidth, strengths)

        # Detect active signals
        noise_floor = float(np.median(strengths))
        threshold = noise_floor + self._squelch_offset

        for i, bk in enumerate(bookmarks):
            if strengths[i] > threshold:
                signals.append(DetectedSignal(
                    frequency_hz=bk.frequency,
                    bandwidth_hz=0,  # unknown from strength reading
                    peak_power=float(strengths[i]),
                    avg_power=float(strengths[i]),
                    bin_start=i,
                    bin_end=i + 1,
                ))

        signals.sort(key=lambda s: s.peak_power, reverse=True)
        return signals
```

- [ ] **Step 8: Run all scanner gqrx tests**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner_gqrx.py -v`
Expected: all PASS

- [ ] **Step 9: Run existing scanner tests to verify no regressions**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add signaldeck/engine/scanner.py tests/test_scanner_gqrx.py
git commit -m "feat: add strength-based sweep and bookmark scanning for gqrx"
```

---

### Task 5: Config — gqrx Settings

**Files:**
- Modify: `config/default.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write test for gqrx config loading**

Add to `tests/test_config.py`:

```python
def test_default_config_has_gqrx_settings():
    """Default config includes gqrx auto-detect settings."""
    from signaldeck.config import load_config
    cfg = load_config(None)
    assert cfg["devices"]["gqrx_auto_detect"] is True
    assert cfg["devices"]["gqrx_instances"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_config.py::test_default_config_has_gqrx_settings -v`
Expected: FAIL — `KeyError: 'gqrx_auto_detect'`

- [ ] **Step 3: Add gqrx keys to default.yaml**

Edit `config/default.yaml`, updating the `devices:` section:

```yaml
devices:
  auto_discover: true
  gain: 40  # dB, overridden per device if needed
  gqrx_auto_detect: true   # try connecting to gqrx on localhost:7356
  gqrx_instances: []        # additional gqrx instances: [{host: "192.168.1.50", port: 7356}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source venv/bin/activate && python -m pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add config/default.yaml tests/test_config.py
git commit -m "feat: add gqrx auto-detect config keys"
```

---

### Task 6: Main Loop — gqrx Dispatch

**Files:**
- Modify: `signaldeck/main.py`

- [ ] **Step 1: Update imports and device discovery in _run()**

In `signaldeck/main.py`, after the existing device manager imports (around line 67-68), add:

```python
from signaldeck.engine.gqrx_device import GqrxDevice
```

Replace the device discovery block (lines ~91-107) with:

```python
        # Discover devices (SoapySDR + gqrx)
        mgr = DeviceManager()
        gqrx_cfg = cfg.get("devices", {})
        available = await mgr.enumerate_async(
            gqrx_auto_detect=gqrx_cfg.get("gqrx_auto_detect", True),
            gqrx_instances=gqrx_cfg.get("gqrx_instances", []),
        )
        sdr_devices = [d for d in available if d.driver not in ("audio",)]
        if not sdr_devices:
            logger.error("No SDR devices found. Connect a HackRF/RTL-SDR or start gqrx with remote control enabled.")
            if web_task:
                web_task.cancel()
            await db.close()
            return

        logger.info("Found %d device(s): %s", len(sdr_devices),
                     ", ".join(f"{d.label} ({d.driver})" for d in sdr_devices))

        # Prefer gqrx if available, otherwise use first SoapySDR device
        chosen = next((d for d in sdr_devices if d.driver == "gqrx"), sdr_devices[0])

        if chosen.driver == "gqrx":
            host, port_str = chosen.serial.split(":")
            device = await mgr.open_gqrx(host=host, port=int(port_str))
        else:
            device = mgr.open(driver=chosen.driver, serial=chosen.serial)
            device.set_gain(cfg["devices"]["gain"])

        is_gqrx = isinstance(device, GqrxDevice)
        if is_gqrx:
            logger.info("Using gqrx backend at %s", chosen.serial)
```

- [ ] **Step 2: Update the main scan loop**

Replace the main loop (the `while True:` block) with:

```python
        logger.info("Starting sweep across %d range(s)...", len(ranges))
        try:
            while True:
                if is_gqrx:
                    # gqrx mode: strength-based scanning, no audio streaming
                    # (gqrx handles audio output directly)
                    signals = await scanner.strength_sweep_once(fft_callback=on_fft)
                    if signals:
                        await on_signals(signals)
                else:
                    # SoapySDR mode: IQ-based scanning with optional audio
                    if audio_request_fn:
                        audio_req = audio_request_fn()
                        if audio_req.get("active") and audio_req.get("frequency_hz"):
                            logger.info("Audio streaming: tuning to %.3f MHz",
                                        audio_req["frequency_hz"] / 1e6)
                            await _stream_audio(device, audio_req["frequency_hz"],
                                                audio_stream_fn, audio_request_fn,
                                                sample_rate=2_000_000)
                            logger.info("Audio streaming ended, resuming scan")
                            continue

                    signals = await scanner.sweep_once(fft_callback=on_fft)
                    if signals:
                        await on_signals(signals)
        except KeyboardInterrupt:
            pass
```

- [ ] **Step 3: Update the cleanup block for async close**

In the `finally:` block, replace `device.close()` with:

```python
            if is_gqrx:
                await device.close()
            else:
                device.close()
```

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `source venv/bin/activate && python -m pytest tests/ -x -q -m "not hardware"`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/main.py
git commit -m "feat: integrate gqrx backend into main scan loop"
```

---

### Task 7: End-to-End Verification

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `source venv/bin/activate && python -m pytest tests/ -v -m "not hardware"`
Expected: all 214+ tests PASS (original tests plus new gqrx tests)

- [ ] **Step 2: Verify no import errors**

Run: `source venv/bin/activate && python -c "from signaldeck.engine.gqrx_client import GqrxClient; from signaldeck.engine.gqrx_device import GqrxDevice; print('OK')"`
Expected: prints `OK`

- [ ] **Step 3: Verify CLI still starts (will fail on no device, but shouldn't crash on import)**

Run: `source venv/bin/activate && python -m signaldeck.main --version`
Expected: prints version number

- [ ] **Step 4: Commit any final fixes if needed, then tag**

```bash
git log --oneline feature/gqrx-backend ^master
```

Verify the commit history looks clean.
