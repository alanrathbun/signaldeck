import logging
import re
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

# APRS North-American primary frequency
_APRS_FREQ_NA = 144.39e6
# APRS European primary frequency
_APRS_FREQ_EU = 144.80e6

# Matches SOURCE>DEST,PATH:payload or SOURCE>DEST:payload
_HEADER_RE = re.compile(r"^([A-Z0-9\-]+)>([A-Z0-9\-]+)((?:,[^:]+)*):(.*)", re.DOTALL)

# Position pattern: !=/@ followed by DDMM.MMN/DDDMM.MMW
_POSITION_RE = re.compile(r"[!=/@](\d{4}\.\d{2})([NS])[/\\](\d{5}\.\d{2})([EW])")

# multimon-ng AFSK1200 output line
_AFSK_LINE_RE = re.compile(r"AFSK1200:\s*(.*)")


def _parse_lat_lon(lat_str: str, lat_dir: str, lon_str: str, lon_dir: str) -> tuple[float, float]:
    """Convert DDMM.MM / DDDMM.MM format to decimal degrees."""
    lat_deg = float(lat_str[:2])
    lat_min = float(lat_str[2:])
    latitude = lat_deg + lat_min / 60.0
    if lat_dir == "S":
        latitude = -latitude

    lon_deg = float(lon_str[:3])
    lon_min = float(lon_str[3:])
    longitude = lon_deg + lon_min / 60.0
    if lon_dir == "W":
        longitude = -longitude

    return latitude, longitude


def parse_aprs_packet(raw: str) -> dict | None:
    """Parse a raw APRS packet string.

    Returns a dict with at minimum: source, destination, path, type.
    Position packets also include latitude and longitude.
    Returns None if the packet cannot be parsed.
    """
    if not raw or not raw.strip():
        return None

    match = _HEADER_RE.match(raw.strip())
    if not match:
        return None

    source, destination, path_raw, payload = match.groups()
    # path_raw starts with a comma or is empty
    path = path_raw.lstrip(",") if path_raw else ""

    result: dict = {
        "source": source,
        "destination": destination,
        "path": path,
        "raw": raw,
    }

    if not payload:
        result["type"] = "unknown"
        return result

    first_char = payload[0]

    # Weather: @ or * with underscore symbol somewhere in payload
    if first_char in ("@", "*") and "_" in payload:
        result["type"] = "weather"
        # Attempt position extraction from weather packet
        pos_match = _POSITION_RE.search(payload)
        if pos_match:
            lat, lon = _parse_lat_lon(*pos_match.groups())
            result["latitude"] = lat
            result["longitude"] = lon
        return result

    # Position: !, =, /, @
    if first_char in ("!", "=", "/", "@"):
        result["type"] = "position"
        pos_match = _POSITION_RE.search(payload)
        if pos_match:
            lat, lon = _parse_lat_lon(*pos_match.groups())
            result["latitude"] = lat
            result["longitude"] = lon
        return result

    # Message / bulletin: starts with :
    if first_char == ":":
        result["type"] = "message"
        # payload format:  :ADDRESSEE :message text
        msg_match = re.match(r":(.{9}):(.+)", payload)
        if msg_match:
            result["addressee"] = msg_match.group(1).strip()
            result["message"] = msg_match.group(2)
        return result

    # Status: starts with >
    if first_char == ">":
        result["type"] = "status"
        result["status"] = payload[1:]
        return result

    result["type"] = "unknown"
    result["payload"] = payload
    return result


class AprsDecoder(DecoderPlugin):
    """APRS decoder using multimon-ng AFSK1200."""

    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()

    @property
    def name(self) -> str:
        return "aprs"

    @property
    def protocols(self) -> list[str]:
        return ["aprs"]

    @property
    def input_type(self) -> str:
        return "audio"

    def tool_available(self) -> bool:
        return shutil.which("multimon-ng") is not None

    def can_decode(self, signal: SignalInfo) -> float:
        """Return confidence that this decoder can handle the signal.

        - 0.9 for the North American APRS primary frequency (144.39 MHz)
        - 0.3 for any narrowband FM in the 144–148 MHz VHF amateur band
        - 0.0 otherwise
        """
        freq = signal.frequency_hz
        if signal.modulation.upper() != "FM":
            return 0.0

        # Exact match for 144.39 MHz (within ±5 kHz)
        if abs(freq - _APRS_FREQ_NA) <= 5000:
            return 0.9

        # General VHF amateur band 144–148 MHz with narrowband FM
        if 144e6 <= freq <= 148e6 and signal.bandwidth_hz <= 25000:
            return 0.3

        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        """Pipe audio data to multimon-ng and yield parsed APRS packets."""
        if not self.tool_available():
            logger.error("multimon-ng not installed; cannot decode APRS")
            return

        import numpy as np
        from scipy.signal import resample_poly
        from math import gcd

        config = ProcessConfig(
            command=["multimon-ng", "-t", "raw", "-a", "AFSK1200", "-"],
            name="multimon_aprs",
            stdin_pipe=True,
        )

        results: list[dict] = []

        async def on_line(line: str) -> None:
            line_match = _AFSK_LINE_RE.match(line)
            if line_match:
                packet_str = line_match.group(1).strip()
                parsed = parse_aprs_packet(packet_str)
                if parsed:
                    results.append(parsed)

        managed = await self._supervisor.start_process(config, on_output=on_line)

        async for audio_chunk in data_source:
            divisor = gcd(48000, 22050)
            up = 22050 // divisor
            down = 48000 // divisor
            resampled = resample_poly(audio_chunk, up, down).astype(np.float32)
            pcm16 = (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16)
            await self._supervisor.write_stdin("multimon_aprs", pcm16.tobytes())

        await self._supervisor.stop_process("multimon_aprs")

        for parsed in results:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=signal.frequency_hz,
                protocol="aprs",
                result_type="packet",
                content=parsed,
                metadata={
                    "source": parsed.get("source", ""),
                    "packet_type": parsed.get("type", "unknown"),
                    "strength": signal.peak_power,
                },
            )

    async def stop(self) -> None:
        await self._supervisor.stop_all()
