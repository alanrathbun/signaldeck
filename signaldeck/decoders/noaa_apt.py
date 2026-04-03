import logging
import shutil
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import AsyncIterator

import numpy as np

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessConfig, ProcessSupervisor

logger = logging.getLogger(__name__)

# NOAA APT satellite frequencies and metadata
NOAA_SATELLITES = [
    {
        "name": "NOAA-15",
        "freq_hz": 137.62e6,
        "status": "decommissioned_2025",
    },
    {
        "name": "NOAA-18",
        "freq_hz": 137.9125e6,
        "status": "decommissioned_2025",
    },
    {
        "name": "NOAA-19",
        "freq_hz": 137.1e6,
        "status": "decommissioned_2025",
    },
]

# Frequency match tolerance in Hz
_FREQ_TOLERANCE_HZ = 25_000


def tool_available() -> bool:
    """Return True if the aptdec command-line tool is installed."""
    return shutil.which("aptdec") is not None


class NoaaAptDecoder(DecoderPlugin):
    """Decoder for NOAA APT (Automatic Picture Transmission) satellite imagery.

    Receives IQ data, FM-demodulates it, resamples to 11025 Hz (the standard
    APT audio sample rate), saves a WAV file, then optionally invokes aptdec
    to produce a PNG image.
    """

    _APT_AUDIO_RATE = 11025  # Hz – standard rate expected by aptdec

    def __init__(self, image_dir: str = "data/images") -> None:
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
        return ["noaa_apt"]

    @property
    def input_type(self) -> str:
        return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        if signal.protocol_hint == "noaa_apt":
            return 0.95
        for sat in NOAA_SATELLITES:
            if abs(signal.frequency_hz - sat["freq_hz"]) <= _FREQ_TOLERANCE_HZ:
                return 0.85
        return 0.0

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        from signaldeck.engine.audio_pipeline import fm_demodulate, save_audio_wav
        from scipy.signal import resample_poly

        # Collect all IQ chunks
        chunks = []
        async for iq_chunk in data_source:
            chunks.append(iq_chunk)

        if chunks:
            iq_data = np.concatenate(chunks)
        else:
            iq_data = np.zeros(0, dtype=np.complex64)

        # FM demodulate to intermediate audio at sample_rate
        sample_rate = signal.sample_rate
        if len(iq_data) > 1:
            audio = fm_demodulate(iq_data, sample_rate=sample_rate, audio_rate=sample_rate)
        else:
            audio = np.zeros(0, dtype=np.float32)

        # Resample to APT standard rate (11025 Hz)
        if len(audio) > 0 and sample_rate != self._APT_AUDIO_RATE:
            from_int = int(sample_rate)
            to_int = self._APT_AUDIO_RATE
            divisor = gcd(from_int, to_int)
            up = to_int // divisor
            down = from_int // divisor
            audio = resample_poly(audio, up, down).astype(np.float32)

        # Build WAV file path
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        freq_label = f"{signal.frequency_hz / 1e6:.4f}MHz"
        wav_path = str(self._image_dir / f"{timestamp}_{freq_label}.wav")

        if len(audio) > 0:
            save_audio_wav(audio, wav_path, sample_rate=self._APT_AUDIO_RATE)
        else:
            # Still create an empty-ish WAV so aptdec has something to open
            save_audio_wav(np.zeros(self._APT_AUDIO_RATE, dtype=np.float32), wav_path,
                           sample_rate=self._APT_AUDIO_RATE)

        # Determine which satellite this is (for metadata)
        satellite_name = self._identify_satellite(signal.frequency_hz)

        # Try to run aptdec
        if tool_available():
            png_path = wav_path.replace(".wav", ".png")
            config = ProcessConfig(
                command=["aptdec", wav_path, "-o", png_path],
                name=f"aptdec_{timestamp}",
            )
            lines: list[str] = []

            async def collect(line: str) -> None:
                lines.append(line)

            return_code = await self._supervisor.run_once(config, collect, timeout=60.0)
            image_exists = Path(png_path).exists()

            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=signal.frequency_hz,
                protocol="noaa_apt",
                result_type="image",
                content={
                    "image_path": png_path if image_exists else None,
                    "wav_path": wav_path,
                    "satellite": satellite_name,
                    "aptdec_output": lines,
                    "aptdec_return_code": return_code,
                    "status": "ok" if image_exists else "aptdec_failed",
                },
                metadata={
                    "strength": signal.peak_power,
                    "bandwidth_hz": signal.bandwidth_hz,
                    "audio_samples": len(audio),
                    "audio_rate_hz": self._APT_AUDIO_RATE,
                },
            )
        else:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=signal.frequency_hz,
                protocol="noaa_apt",
                result_type="image",
                content={
                    "image_path": None,
                    "wav_path": wav_path,
                    "satellite": satellite_name,
                    "status": "aptdec_not_installed",
                },
                metadata={
                    "strength": signal.peak_power,
                    "bandwidth_hz": signal.bandwidth_hz,
                    "audio_samples": len(audio),
                    "audio_rate_hz": self._APT_AUDIO_RATE,
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _identify_satellite(self, frequency_hz: float) -> str | None:
        for sat in NOAA_SATELLITES:
            if abs(frequency_hz - sat["freq_hz"]) <= _FREQ_TOLERANCE_HZ:
                return sat["name"]
        return None
