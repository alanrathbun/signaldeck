import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)

# The 7 NOAA Weather Radio frequencies in MHz
WEATHER_FREQS = [
    162.400e6,
    162.425e6,
    162.450e6,
    162.475e6,
    162.500e6,
    162.525e6,
    162.550e6,
]

# SAME (Specific Area Message Encoding) event codes
SAME_EVENTS: dict[str, str] = {
    # Warnings
    "TOR": "Tornado Warning",
    "SVR": "Severe Thunderstorm Warning",
    "FFW": "Flash Flood Warning",
    "FLW": "Flood Warning",
    "HUW": "Hurricane Warning",
    "TSW": "Tsunami Warning",
    "WSW": "Winter Storm Warning",
    "BZW": "Blizzard Warning",
    "EWW": "Extreme Wind Warning",
    "FRW": "Fire Warning",
    "HMW": "Hazardous Materials Warning",
    "NUW": "Nuclear Power Plant Warning",
    "RHW": "Radiological Hazard Warning",
    "VOW": "Volcano Warning",
    "SMW": "Special Marine Warning",
    "MWS": "Marine Weather Statement",
    "LAW": "Landslide Warning",
    "LEW": "Law Enforcement Warning",
    "CEM": "Civil Emergency Message",
    # Watches
    "TOA": "Tornado Watch",
    "SVA": "Severe Thunderstorm Watch",
    "FFA": "Flash Flood Watch",
    "FLA": "Flood Watch",
    "HUA": "Hurricane Watch",
    "TSA": "Tsunami Watch",
    "WSA": "Winter Storm Watch",
    # Advisories and Statements
    "FFS": "Flash Flood Statement",
    "FLS": "Flood Statement",
    "HLS": "Hurricane Statement",
    "SSA": "Storm Surge Watch",
    "SSW": "Storm Surge Warning",
    "SQW": "Snow Squall Warning",
    "DUW": "Dust Storm Warning",
    "FGW": "Dense Fog Advisory",
    "HWW": "High Wind Warning",
    "WIW": "Winter Weather Advisory",
    # Special / National
    "EAN": "Emergency Action Notification",
    "EAT": "Emergency Action Termination",
    "NIC": "National Information Center",
    "NPT": "National Periodic Test",
    "RWT": "Required Weekly Test",
    "RMT": "Required Monthly Test",
    "ADR": "Administrative Message",
    "AVW": "Avalanche Warning",
    "AVA": "Avalanche Watch",
    "CAE": "Child Abduction Emergency",
    "CDW": "Civil Danger Warning",
    "DMO": "Practice/Demo Warning",
    "EVI": "Evacuation Immediate",
    "SPW": "Shelter in Place Warning",
    "TOE": "911 Telephone Outage Emergency",
}

# Regex for SAME header: ZCZC-ORG-EEE-PSSCCC[-PSSCCC...]+TTTT-JJJHHMM-LLLLLLLL/NNN-
_SAME_PATTERN = re.compile(
    r"ZCZC-(\w{3})-(\w{3})-([\d-]+)\+(\d{4})-(\d{7})-(.+)-$"
)


def parse_same_header(header: str) -> dict | None:
    """Parse a NOAA SAME (Specific Area Message Encoding) header string.

    Returns a dict with keys: originator, event, locations, duration_minutes,
    datetime_code, station. Returns None if the header is invalid.
    """
    if not header or not header.startswith("ZCZC"):
        return None

    match = _SAME_PATTERN.match(header)
    if not match:
        return None

    originator, event, locations_raw, duration_hhmm, datetime_code, station = match.groups()

    # Split the dash-separated FIPS location codes
    locations = [loc for loc in locations_raw.split("-") if loc]

    # Parse duration: HHMM → total minutes
    try:
        hours = int(duration_hhmm[:2])
        minutes = int(duration_hhmm[2:])
        duration_minutes = hours * 60 + minutes
    except (ValueError, IndexError):
        return None

    return {
        "originator": originator,
        "event": event,
        "locations": locations,
        "duration_minutes": duration_minutes,
        "datetime_code": datetime_code,
        "station": station,
        "event_description": SAME_EVENTS.get(event, "Unknown Event"),
    }


class WeatherRadioDecoder(DecoderPlugin):
    """Decoder for NOAA Weather Radio (NWR) with SAME alert parsing."""

    def __init__(self, recording_dir: str = "data/recordings") -> None:
        self._recording_dir = recording_dir

    @property
    def name(self) -> str:
        return "weather_radio"

    @property
    def protocols(self) -> list[str]:
        return ["weather_radio"]

    @property
    def input_type(self) -> str:
        return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        if signal.protocol_hint == "weather_radio":
            return 0.95
        # Check if frequency is within ±5 kHz of any NOAA weather frequency
        for freq in WEATHER_FREQS:
            if abs(signal.frequency_hz - freq) <= 5000:
                return 0.9
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        from signaldeck.engine.audio_pipeline import fm_demodulate, AudioRecorder

        recorder = AudioRecorder(output_dir=self._recording_dir, sample_rate=48000)
        label = f"{signal.frequency_hz / 1e6:.3f}MHz_weather"
        audio_path = recorder.start(label)
        total_samples = 0

        async for iq_chunk in data_source:
            audio = fm_demodulate(iq_chunk, sample_rate=signal.sample_rate, audio_rate=48000)
            recorder.write(audio)
            total_samples += len(audio)

        recorder.stop()
        duration = total_samples / 48000.0

        yield DecoderResult(
            timestamp=datetime.now(timezone.utc),
            frequency=signal.frequency_hz,
            protocol="weather_radio",
            result_type="voice",
            content={
                "modulation": "FM",
                "duration_s": round(duration, 2),
                "sample_count": total_samples,
                "frequency_mhz": round(signal.frequency_hz / 1e6, 3),
            },
            audio_path=audio_path,
            metadata={
                "strength": signal.peak_power,
                "bandwidth_hz": signal.bandwidth_hz,
            },
        )
