"""P25 decoder wrapping OP25 (rx.py) with stderr event parsing."""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

# OP25 apps directory
_OP25_APPS_DIR = Path("~/signaldeck-tools/src/op25/op25/gr-op25_repeater/apps/").expanduser()
_RX_PY = _OP25_APPS_DIR / "rx.py"

# P25 frequency bands (MHz)
# 700 MHz band: 764-776 MHz (uplink) / 794-806 MHz (downlink)
_BAND_700_RANGES = [(764e6, 776e6), (794e6, 806e6)]
# 800 MHz band: 806-869 MHz
_BAND_800_RANGE = (806e6, 869e6)

# --- Regex patterns for OP25 stderr output ---

# tgid=12345 freq=851012500
_TGID_FREQ_RE = re.compile(r"tgid=(\d+)\s+freq=(\d+)")

# NAC 0x293 WACN 0xBEE00 SYSID 0x123 RFID 0x01 STID 0x01
_NAC_RE = re.compile(
    r"NAC\s+(0x[0-9A-Fa-f]+)\s+WACN\s+(0x[0-9A-Fa-f]+)\s+SYSID\s+(0x[0-9A-Fa-f]+)"
)

# voice grant  tgid 12345  freq 851.0125
_VOICE_GRANT_RE = re.compile(r"voice\s+grant", re.IGNORECASE)


def parse_op25_stderr_line(line: str) -> dict | None:
    """Parse a single line from OP25 rx.py stderr output.

    Recognises three event types:
    - tgid/freq assignments: returns dict with talkgroup and frequency keys
    - NAC/WACN/SYSID system info: returns dict with type="system_info" and nac/wacn/sysid keys
    - Voice grant lines: returns dict with type="voice_grant"

    Returns None for empty or unrecognised lines.
    """
    if not line or not line.strip():
        return None

    # tgid=... freq=... assignment
    m = _TGID_FREQ_RE.search(line)
    if m:
        return {
            "type": "tgid_freq",
            "talkgroup": m.group(1),
            "frequency": m.group(2),
        }

    # NAC system info
    m = _NAC_RE.search(line)
    if m:
        return {
            "type": "system_info",
            "nac": m.group(1),
            "wacn": m.group(2),
            "sysid": m.group(3),
        }

    # Voice grant
    if _VOICE_GRANT_RE.search(line):
        # Extract optional tgid and freq from the voice grant line
        result: dict = {"type": "voice_grant"}
        tgid_m = re.search(r"tgid\s+(\d+)", line, re.IGNORECASE)
        freq_m = re.search(r"freq\s+([\d.]+)", line, re.IGNORECASE)
        if tgid_m:
            result["talkgroup"] = tgid_m.group(1)
        if freq_m:
            result["frequency"] = freq_m.group(1)
        return result

    return None


class P25Decoder(DecoderPlugin):
    """P25 (Project 25) digital voice decoder wrapping OP25 rx.py.

    OP25 is a GNU Radio-based P25 decoder. This class manages the rx.py
    subprocess and parses relevant events from its stderr output.
    """

    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()

    @property
    def name(self) -> str:
        return "p25"

    @property
    def protocols(self) -> list[str]:
        return ["p25"]

    @property
    def input_type(self) -> str:
        return "iq"

    def tool_available(self) -> bool:
        """Return True if the OP25 rx.py script exists at the expected path."""
        return _RX_PY.exists()

    def can_decode(self, signal: SignalInfo) -> float:
        """Return confidence score for decoding this signal with P25/OP25.

        Scoring:
        - 0.95  protocol_hint is "p25"
        - 0.5   frequency falls in the 700 MHz P25 band (764-776 or 794-806 MHz)
        - 0.4   frequency falls in the 800 MHz P25 band (806-869 MHz)
        - 0.25  narrowband FM hint in VHF/UHF (non-broadcast) range
        - 0.0   otherwise (e.g. broadcast FM at 88-108 MHz)
        """
        freq = signal.frequency_hz

        # Explicit protocol hint
        if signal.protocol_hint == "p25":
            return 0.95

        # 700 MHz P25 band
        for low, high in _BAND_700_RANGES:
            if low <= freq <= high:
                return 0.5

        # 800 MHz P25 band
        if _BAND_800_RANGE[0] <= freq <= _BAND_800_RANGE[1]:
            return 0.4

        # Narrowband FM hint in VHF/UHF (exclude broadcast FM 88-108 MHz)
        if (
            signal.protocol_hint == "narrowband_fm"
            and signal.bandwidth_hz <= 25000
            and not (88e6 <= freq <= 108e6)
        ):
            return 0.25

        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        """Stub: OP25 requires a live SDR connection, not one-shot IQ data.

        Callers should use start_monitoring() instead for continuous P25 monitoring.
        """
        logger.info(
            "P25Decoder.decode() called; OP25 requires a live SDR connection. "
            "Use start_monitoring() instead."
        )
        return
        yield  # make this an async generator

    def start_monitoring(
        self,
        frequency_hz: float,
        gain: float,
        sample_rate: float,
        on_result: Callable[[dict], None],
    ) -> None:
        """Launch OP25 rx.py and call on_result for each decoded P25 event.

        This is a non-blocking call; rx.py is launched as a background subprocess
        managed by ProcessSupervisor. Stderr lines are parsed for P25 events.

        Args:
            frequency_hz:  Centre frequency in Hz.
            gain:          SDR gain in dB.
            sample_rate:   SDR sample rate in samples/second.
            on_result:     Callback receiving a parsed event dict for each P25 event.
        """
        if not self.tool_available():
            logger.error("OP25 rx.py not found at %s; cannot start P25 monitoring", _RX_PY)
            return

        freq_mhz = frequency_hz / 1e6

        config = ProcessConfig(
            command=[
                "python3",
                str(_RX_PY),
                "--args", "rtl",
                "--gains", f"lna:{gain}",
                "--frequency", str(int(frequency_hz)),
                "--sample-rate", str(int(sample_rate)),
                "-q",
            ],
            name="op25_rx",
        )

        async def _on_line(line: str) -> None:
            parsed = parse_op25_stderr_line(line)
            if parsed is not None:
                on_result(parsed)

        import asyncio

        loop = asyncio.get_event_loop()
        loop.create_task(
            self._supervisor.start_process(config, on_output=_on_line)
        )

    async def stop(self) -> None:
        """Stop the OP25 subprocess."""
        await self._supervisor.stop_all()
