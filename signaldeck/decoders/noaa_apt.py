"""NOAA APT and Meteor-M LRPT weather satellite decoder via SatDump.

SatDump (https://github.com/SatDump/SatDump) is a mature, actively maintained
C++ satellite decoder that handles NOAA 15/18/19 APT, Meteor-M LRPT, GOES,
and dozens of other satellites. This module wraps SatDump as a subprocess
and surfaces the resulting images as DecoderResults.

SatDump is NOT in the standard Debian/Ubuntu repositories. To install:

    # Ubuntu/Debian — fetch the latest .deb from GitHub releases
    wget https://github.com/SatDump/SatDump/releases/latest/download/satdump_ubuntu_latest_amd64.deb
    sudo apt install ./satdump_ubuntu_latest_amd64.deb

    # Or build from source (see https://docs.satdump.org/building.html)

Once `satdump` is on PATH, SignalDeck picks it up automatically — no code
changes needed. The decoder degrades to "tool not installed" mode if
satdump is absent, and logs a warning rather than raising.

Supported pipelines (from docs.satdump.org/pipelines.html):
    - noaa_apt_demod      NOAA 15/18/19 APT (137 MHz)
    - meteor_m2-x_lrpt    Meteor-M N2/N2-2/N2-3/N2-4 LRPT (137 MHz)
    - meteor_m-hrpt       Meteor-M HRPT (1.7 GHz)
    - goes_hrit           GOES HRIT (1.7 GHz)

This module exposes the first two pipelines (APT + LRPT) because they're
the ones an operator with an RTL-SDR and a V-dipole can actually receive.
HRPT and HRIT require dish antennas.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import numpy as np

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessConfig, ProcessSupervisor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SatelliteInfo:
    name: str
    freq_hz: float
    pipeline: str
    status: str  # "active" | "decommissioned" | "unknown"


# Weather satellites we can decode with an RTL-SDR. Metadata used for
# frequency matching in can_decode(). Pipeline strings match SatDump's
# CLI pipeline IDs.
WEATHER_SATELLITES: list[SatelliteInfo] = [
    # NOAA APT — all three are technically decommissioned as of 2025,
    # but the signals still transmit intermittently and old recordings
    # are a common test case.
    SatelliteInfo("NOAA-15", 137.620e6, "noaa_apt_demod", "decommissioned_2025"),
    SatelliteInfo("NOAA-18", 137.9125e6, "noaa_apt_demod", "decommissioned_2025"),
    SatelliteInfo("NOAA-19", 137.100e6, "noaa_apt_demod", "decommissioned_2025"),
    # Meteor-M LRPT — Russian polar weather satellites, active replacements
    # for the NOAA APT series. LRPT is QPSK'd, SatDump handles it.
    SatelliteInfo("Meteor-M N2-3", 137.900e6, "meteor_m2-x_lrpt", "active"),
    SatelliteInfo("Meteor-M N2-4", 137.900e6, "meteor_m2-x_lrpt", "active"),
]

# Frequency match tolerance in Hz — wide because Doppler shift during a
# pass can push the effective frequency by ±3 kHz.
_FREQ_TOLERANCE_HZ = 25_000


def tool_available() -> bool:
    """Return True if the satdump binary is on PATH."""
    return shutil.which("satdump") is not None


def _satellite_for_frequency(freq_hz: float) -> SatelliteInfo | None:
    """Return the satellite whose nominal frequency is closest to freq_hz,
    or None if nothing matches within _FREQ_TOLERANCE_HZ."""
    best: tuple[float, SatelliteInfo] | None = None
    for sat in WEATHER_SATELLITES:
        delta = abs(sat.freq_hz - freq_hz)
        if delta <= _FREQ_TOLERANCE_HZ:
            if best is None or delta < best[0]:
                best = (delta, sat)
    return best[1] if best else None


class NoaaAptDecoder(DecoderPlugin):
    """Weather-satellite decoder wrapping SatDump.

    Decodes NOAA APT and Meteor-M LRPT live from I/Q samples. Writes
    SatDump's PNG outputs into `image_dir` and yields one DecoderResult
    per output image.

    The live-decode mode isn't used — SatDump's `live` command wants to
    own the SDR device, which conflicts with SignalDeck's scanner loop.
    Instead we collect I/Q into a temp file and run SatDump's
    baseband-processing mode on that file after the pass ends.
    """

    # SatDump's baseband input format — "f32" is raw interleaved complex
    # float32 at native sample rate, which matches what we already have
    # in-memory as numpy complex64.
    _INPUT_LEVEL = "baseband"

    def __init__(self, image_dir: str = "data/images/satellite") -> None:
        self._image_dir = Path(image_dir)
        self._image_dir.mkdir(parents=True, exist_ok=True)
        self._supervisor = ProcessSupervisor()

    # ------------------------------------------------------------------
    # DecoderPlugin interface
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return "noaa_apt"

    @property
    def protocols(self) -> list[str]:
        return ["noaa_apt", "meteor_m_lrpt"]

    @property
    def input_type(self) -> str:
        return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        if not tool_available():
            return 0.0
        sat = _satellite_for_frequency(signal.frequency_hz)
        if sat is None:
            return 0.0
        # High confidence on a known APT/LRPT frequency within tolerance.
        return 0.85

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        if not tool_available():
            logger.warning(
                "satdump not installed — skipping NOAA APT/LRPT decode. "
                "Install from https://github.com/SatDump/SatDump/releases"
            )
            return

        sat = _satellite_for_frequency(signal.frequency_hz)
        if sat is None:
            logger.debug(
                "No known satellite within %d Hz of %.3f MHz",
                _FREQ_TOLERANCE_HZ,
                signal.frequency_hz / 1e6,
            )
            return

        iq = await self._collect_iq(data_source)
        if iq is None or len(iq) == 0:
            logger.warning("No I/Q samples collected for %s", sat.name)
            return

        # Write the I/Q buffer to a temp baseband file that SatDump
        # can read. SatDump expects interleaved float32 (not complex64).
        iq_f32 = iq.astype(np.complex64, copy=False)
        interleaved = np.empty(len(iq_f32) * 2, dtype=np.float32)
        interleaved[0::2] = iq_f32.real
        interleaved[1::2] = iq_f32.imag

        with tempfile.NamedTemporaryFile(
            suffix=".f32", delete=False, dir=str(self._image_dir)
        ) as tmp:
            tmp.write(interleaved.tobytes())
            tmp_path = tmp.name

        # Per-pass output subdirectory keeps SatDump's multiple output
        # files grouped so we can scan the directory afterward.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = self._image_dir / f"{sat.name.replace(' ', '_')}_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        config = ProcessConfig(
            command=[
                "satdump",
                sat.pipeline,
                self._INPUT_LEVEL,
                tmp_path,
                str(out_dir),
                "--samplerate", str(int(signal.sample_rate)),
                "--baseband_format", "f32",
            ],
            name=f"satdump-{sat.pipeline}",
        )

        logger.info(
            "Running SatDump %s pipeline on %.3f MHz capture (%d samples)",
            sat.pipeline,
            signal.frequency_hz / 1e6,
            len(iq),
        )

        try:
            await self._supervisor.run_once(config, timeout=600.0)
        except Exception as e:
            logger.warning("SatDump invocation failed: %s", e)
            return
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        # Scan the output directory for PNG/JPG images SatDump produced.
        images = sorted(out_dir.glob("*.png")) + sorted(out_dir.glob("*.jpg"))
        if not images:
            logger.warning(
                "SatDump produced no images in %s — pass may have been too "
                "weak, frequency off, or pipeline mismatched",
                out_dir,
            )
            return

        for img_path in images:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=signal.frequency_hz,
                protocol=sat.pipeline,
                result_type="image",
                content={
                    "satellite": sat.name,
                    "image_path": str(img_path),
                    "channel": img_path.stem,
                },
                metadata={
                    "satellite": sat.name,
                    "pipeline": sat.pipeline,
                    "status": sat.status,
                    "output_dir": str(out_dir),
                },
            )

    async def decode_to_list(self, signal: SignalInfo, data_source) -> list[DecoderResult]:
        return [result async for result in self.decode(signal, data_source)]

    async def stop(self) -> None:
        await self._supervisor.stop_all()

    async def _collect_iq(self, data_source) -> np.ndarray | None:
        if isinstance(data_source, np.ndarray):
            return data_source.astype(np.complex64, copy=False)
        chunks = []
        async for chunk in data_source:
            chunks.append(chunk)
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.complex64, copy=False)
