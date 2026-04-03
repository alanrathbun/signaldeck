"""ADS-B decoder wrapping dump1090-mutability with SBS-format message parsing."""

import logging
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

# ADS-B is broadcast on 1090 MHz
ADSB_FREQUENCY_HZ = 1_090_000_000
ADSB_FREQUENCY_TOLERANCE_HZ = 500_000


def _safe_int(value: str) -> int | None:
    """Parse an integer from a string, returning None on failure."""
    try:
        stripped = value.strip()
        if not stripped:
            return None
        return int(stripped)
    except (ValueError, AttributeError):
        return None


def _safe_float(value: str) -> float | None:
    """Parse a float from a string, returning None on failure."""
    try:
        stripped = value.strip()
        if not stripped:
            return None
        return float(stripped)
    except (ValueError, AttributeError):
        return None


def parse_sbs_message(line: str) -> dict | None:
    """Parse a single SBS (BaseStation) format message line.

    SBS messages are comma-separated with at least 22 fields and begin with "MSG".
    Returns a dict of extracted fields, or None if the line is invalid.

    Field indices (0-based):
        0  - message_type ("MSG")
        1  - transmission_type (1=ID, 3=airborne position, 4=airborne velocity, etc.)
        4  - hex_ident (ICAO 24-bit address as hex string)
        10 - callsign (msg_type 1)
        11 - altitude in feet (msg_type 3)
        12 - ground_speed in knots (msg_type 4)
        13 - track in degrees (msg_type 4)
        14 - latitude (msg_type 3)
        15 - longitude (msg_type 3)
        16 - vertical_rate in ft/min (msg_type 4)
    """
    if not line or not line.strip():
        return None

    fields = line.strip().split(",")

    # SBS messages need at least 11 fields to reach the callsign (field[10]).
    # Fully-populated messages have 22 fields, but some implementations omit
    # trailing empty fields for certain transmission types.
    if len(fields) < 11:
        return None

    if fields[0] != "MSG":
        return None

    msg_type_raw = _safe_int(fields[1])
    if msg_type_raw is None:
        return None

    hex_ident = fields[4].strip()
    result: dict = {
        "msg_type": msg_type_raw,
        "hex_ident": hex_ident,
    }

    if msg_type_raw == 1:
        # Identification message: callsign
        callsign = fields[10].strip()
        if callsign:
            result["callsign"] = callsign

    elif msg_type_raw == 3:
        # Airborne position: altitude, latitude, longitude
        altitude = _safe_int(fields[11]) if len(fields) > 11 else None
        latitude = _safe_float(fields[14]) if len(fields) > 14 else None
        longitude = _safe_float(fields[15]) if len(fields) > 15 else None
        if altitude is not None:
            result["altitude"] = altitude
        if latitude is not None:
            result["latitude"] = latitude
        if longitude is not None:
            result["longitude"] = longitude

    elif msg_type_raw == 4:
        # Airborne velocity: ground_speed, track, vertical_rate
        ground_speed = _safe_int(fields[12]) if len(fields) > 12 else None
        track = _safe_int(fields[13]) if len(fields) > 13 else None
        vertical_rate = _safe_int(fields[16]) if len(fields) > 16 else None
        if ground_speed is not None:
            result["ground_speed"] = ground_speed
        if track is not None:
            result["track"] = track
        if vertical_rate is not None:
            result["vertical_rate"] = vertical_rate

    return result


class AdsbDecoder(DecoderPlugin):
    """ADS-B decoder that wraps dump1090-mutability for continuous aircraft monitoring.

    ADS-B (Automatic Dependent Surveillance-Broadcast) is transmitted at 1090 MHz
    and carries aircraft identification, position, altitude, and velocity data.
    dump1090 captures and decodes Mode S / ADS-B frames from an RTL-SDR and outputs
    them in SBS (BaseStation) format over a TCP connection.
    """

    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()
        # In-memory store of currently visible aircraft keyed by hex_ident
        self._aircraft: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "adsb"

    @property
    def protocols(self) -> list[str]:
        return ["adsb", "mode_s"]

    @property
    def input_type(self) -> str:
        return "iq"

    def tool_available(self) -> bool:
        """Return True if dump1090-mutability (or dump1090-fa) is on PATH."""
        return (
            shutil.which("dump1090-mutability") is not None
            or shutil.which("dump1090") is not None
            or shutil.which("dump1090-fa") is not None
        )

    def can_decode(self, signal: SignalInfo) -> float:
        """Return a confidence score for whether this decoder can handle the signal.

        Returns:
            0.95 if the protocol_hint is "adsb"
            0.9  if the frequency is within ±500 kHz of 1090 MHz
            0.0  otherwise
        """
        if signal.protocol_hint == "adsb":
            return 0.95
        if abs(signal.frequency_hz - ADSB_FREQUENCY_HZ) <= ADSB_FREQUENCY_TOLERANCE_HZ:
            return 0.9
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        """Stub: ADS-B requires continuous monitoring via start_monitoring()."""
        logger.info(
            "AdsbDecoder.decode() called; ADS-B requires continuous monitoring. "
            "Use start_monitoring() instead."
        )
        # ADS-B is a continuous broadcast protocol; a single-shot decode is not
        # meaningful. Yield nothing and advise callers to use start_monitoring().
        return
        yield  # make this a generator

    def start_monitoring(self, on_result: Callable[[dict], None]) -> None:
        """Launch dump1090 and call on_result for each decoded SBS message.

        This method is non-blocking; it registers the callback and starts the
        background process via the supervisor. The supervisor will restart dump1090
        if it exits unexpectedly.

        Args:
            on_result: Callable that receives a parsed SBS message dict for each
                       decoded ADS-B frame.
        """
        if not self.tool_available():
            logger.error("dump1090 is not installed; cannot start ADS-B monitoring")
            return

        tool = (
            shutil.which("dump1090-mutability")
            or shutil.which("dump1090")
            or shutil.which("dump1090-fa")
        )

        config = ProcessConfig(
            command=[tool, "--net", "--quiet"],
            name="dump1090",
        )

        def _on_line(line: str) -> None:
            parsed = parse_sbs_message(line)
            if parsed is None:
                return
            hex_ident = parsed.get("hex_ident")
            if hex_ident:
                # Merge new data into accumulated aircraft state
                if hex_ident not in self._aircraft:
                    self._aircraft[hex_ident] = {}
                self._aircraft[hex_ident].update(parsed)
                self._aircraft[hex_ident]["last_seen"] = datetime.now(timezone.utc).isoformat()
            on_result(parsed)

        import asyncio

        loop = asyncio.get_event_loop()
        loop.create_task(
            self._supervisor.run_once(config, on_output=_on_line, timeout=None)
        )

    def get_aircraft(self) -> dict[str, dict]:
        """Return the current in-memory state of all tracked aircraft.

        Returns:
            Dict mapping hex_ident -> merged state dict accumulated from all
            received SBS message types for that aircraft.
        """
        return dict(self._aircraft)

    async def stop(self) -> None:
        """Stop dump1090 and clear tracked aircraft state."""
        await self._supervisor.stop_all()
        self._aircraft.clear()
