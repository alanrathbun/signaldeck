"""RDS (Radio Data System) decoder for FM broadcast stations.

Parses RDS group data to extract Programme Service (PS) name,
Radio Text (RT), Programme Type (PTY), and PI code from
broadcast FM signals in the 87.5–108 MHz band.
"""

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)

# RDS Programme Type codes (RBDS/RDS standard, 32 entries, index 0-31)
RDS_PTY_CODES: list[str] = [
    "No programme type",   # 0
    "News",                # 1
    "Current Affairs",     # 2
    "Information",         # 3
    "Sport",               # 4
    "Rock",                # 5 (RBDS: Rock Music)
    "Easy Listening",      # 6
    "Light Classical",     # 7
    "Serious Classical",   # 8
    "Other Music",         # 9
    "Pop Music",           # 10
    "Rock Music",          # 11
    "Easy Listening Music",# 12
    "Light Jazz",          # 13
    "Country Music",       # 14
    "National Music",      # 15
    "Oldies Music",        # 16
    "Folk Music",          # 17
    "Documentary",         # 18
    "Alarm Test",          # 19 (RBDS: Talk)
    "Alarm",               # 20 (RBDS: Classical)
    "Travel",              # 21
    "Leisure",             # 22
    "Jazz Music",          # 23
    "Country",             # 24
    "National Music",      # 25
    "Oldies Music",        # 26
    "Folk Music",          # 27
    "Documentary",         # 28
    "Weather",             # 29
    "Emergency Test",      # 30
    "Emergency",           # 31
]


def decode_rds_group(
    block_a: int,
    block_b: int,
    block_c: int,
    block_d: int,
) -> dict | None:
    """Decode a single RDS group from four 16-bit blocks.

    Block layout per the RDS standard (IEC 62106):
      block_a — Programme Identification (PI) code
      block_b — bits 15-12: group type code (0-15)
                bit  11:    version (0=A, 1=B)
                bits 10:    traffic programme flag
                bits 9-5:   PTY code
                bits 4-0:   group-type-specific

    Returns a dict with decoded fields, or None if the group type
    is not supported by this implementation.
    """
    pi_code = block_a & 0xFFFF

    group_type_code = (block_b >> 12) & 0x0F
    version_bit = (block_b >> 11) & 0x01
    version = "A" if version_bit == 0 else "B"
    pty = (block_b >> 5) & 0x1F
    pty_name = RDS_PTY_CODES[pty] if 0 <= pty < len(RDS_PTY_CODES) else "Unknown"

    group_type = f"{group_type_code}{version}"

    base = {
        "pi_code": pi_code,
        "group_type": group_type,
        "pty": pty,
        "pty_name": pty_name,
    }

    if group_type_code == 0:
        # Group 0: Programme Service (PS) name
        # bits 1-0 of block_b = PS segment address (0-3), each carries 2 chars
        ps_segment = block_b & 0x03
        ps_char_hi = chr((block_d >> 8) & 0xFF)
        ps_char_lo = chr(block_d & 0xFF)
        return {
            **base,
            "ps_segment": ps_segment,
            "ps_chars": ps_char_hi + ps_char_lo,
        }

    if group_type_code == 2 and version == "A":
        # Group 2A: Radio Text (RT)
        # bits 3-0 of block_b = RT segment address (0-15), each carries 4 chars
        rt_segment = block_b & 0x0F
        rt_chars = (
            chr((block_c >> 8) & 0xFF)
            + chr(block_c & 0xFF)
            + chr((block_d >> 8) & 0xFF)
            + chr(block_d & 0xFF)
        )
        return {
            **base,
            "rt_segment": rt_segment,
            "rt_chars": rt_chars,
        }

    # Unsupported / unimplemented group — return base info only
    return {**base}


class RdsDecoder(DecoderPlugin):
    """Decoder that extracts RDS metadata from FM broadcast IQ samples."""

    def __init__(self) -> None:
        self._station_data: dict[float, dict] = {}
        self._pipelines: dict[float, "RdsPipeline"] = {}

    # ------------------------------------------------------------------
    # DecoderPlugin interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "rds"

    @property
    def protocols(self) -> list[str]:
        return ["rds", "broadcast_fm"]

    @property
    def input_type(self) -> str:
        return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        hint = signal.protocol_hint
        if hint == "rds":
            return 0.95
        if hint == "broadcast_fm":
            return 0.60
        is_fm = signal.modulation.upper() == "FM"
        in_broadcast_band = 87.5e6 <= signal.frequency_hz <= 108e6
        is_wideband = signal.bandwidth_hz >= 100_000
        if is_fm and in_broadcast_band and is_wideband:
            return 0.50
        return 0.0

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        """Decode RDS from IQ samples (numpy complex64 array)."""
        import numpy as np
        from signaldeck.engine.rds_pipeline import RdsPipeline

        freq = signal.frequency_hz

        if freq not in self._pipelines:
            self._pipelines[freq] = RdsPipeline(
                input_sample_rate=signal.sample_rate
            )

        pipeline = self._pipelines[freq]

        if not isinstance(data_source, np.ndarray) or len(data_source) < 1000:
            return

        groups = pipeline.process(data_source)

        for block_a, block_b, block_c, block_d in groups:
            group = self.process_group(freq, block_a, block_b, block_c, block_d)
            if group is None:
                continue

            station = self._station_data.get(freq, {})
            ps_name = "".join(station.get("ps_name", [])).strip()
            radio_text = "".join(station.get("radio_text", [])).strip()

            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=freq,
                protocol="rds",
                result_type="rds_group",
                content={
                    **group,
                    "ps_name": ps_name,
                    "radio_text": radio_text,
                },
                metadata={
                    "strength": signal.peak_power,
                    "bandwidth_hz": signal.bandwidth_hz,
                },
            )

    def reset_frequency(self, freq_hz: float) -> None:
        """Reset RDS pipeline state for a frequency."""
        if freq_hz in self._pipelines:
            self._pipelines[freq_hz].reset()
        if freq_hz in self._station_data:
            del self._station_data[freq_hz]

    def get_station_data(self, freq_hz: float) -> dict | None:
        """Return accumulated station metadata for a frequency."""
        station = self._station_data.get(freq_hz)
        if station is None:
            return None
        return {
            "pi_code": station.get("pi_code"),
            "ps_name": "".join(station.get("ps_name", [])).strip(),
            "radio_text": "".join(station.get("radio_text", [])).strip(),
        }

    # ------------------------------------------------------------------
    # Stateful group accumulation (unchanged from original)
    # ------------------------------------------------------------------

    def process_group(
        self,
        frequency_hz: float,
        block_a: int,
        block_b: int,
        block_c: int,
        block_d: int,
    ) -> dict | None:
        group = decode_rds_group(block_a, block_b, block_c, block_d)
        if group is None:
            return None

        station = self._station_data.setdefault(frequency_hz, {
            "pi_code": group["pi_code"],
            "ps_name": [" "] * 8,
            "radio_text": [" "] * 64,
        })

        if group["group_type"] == "0A" or group["group_type"] == "0B":
            seg = group.get("ps_segment", 0)
            chars = group.get("ps_chars", "  ")
            if len(chars) == 2:
                station["ps_name"][seg * 2] = chars[0]
                station["ps_name"][seg * 2 + 1] = chars[1]

        if group["group_type"] == "2A":
            seg = group.get("rt_segment", 0)
            chars = group.get("rt_chars", "    ")
            if len(chars) == 4:
                for i, ch in enumerate(chars):
                    station["radio_text"][seg * 4 + i] = ch

        return group
