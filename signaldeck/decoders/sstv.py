"""SSTV (Slow-Scan Television) decoder — pure Python, no external binary.

SSTV is an amateur radio mode that sends still images over voice channels
as sequences of audio tones (typically 1100-2300 Hz FSK). Popular modes
include Martin M1/M2, Scottie S1/S2, Robot 36, and PD120/PD180. The
ISS downlinks occasional SSTV images on 145.800 MHz FM as part of ARISS
educational events.

This decoder wraps the colaclanth/sstv library (installed from the
project's GitHub, `pip install git+https://github.com/colaclanth/sstv.git`),
which auto-detects the SSTV mode from the VIS header and produces a
PIL image. The library reads audio from a WAV file — so this decoder
accepts either a PCM audio numpy array (which it writes to a temp WAV
file) or a pre-existing file path.

### Installation

The colaclanth/sstv library is included as a venv-local dependency
installed via pip from its GitHub repo. It pulls in:
    - PySoundFile (for reading WAV)
    - Pillow (for PIL image output)
    - numpy (already a core dependency)

To install (already done in this session's venv):

    .venv/bin/pip install git+https://github.com/colaclanth/sstv.git

### SSTV frequencies

| Band  | Frequency      | Mode | Notes                           |
|-------|----------------|------|---------------------------------|
| 20m   | 14.230 MHz USB | HF   | Most common HF SSTV freq        |
| 15m   | 21.340 MHz USB | HF   |                                 |
| 10m   | 28.680 MHz USB | HF   |                                 |
| 2m    | 144.500 MHz FM | VHF  | East-coast US simplex SSTV      |
| 2m    | 145.500 MHz FM | VHF  | Default 2m SSTV calling         |
| 2m    | 145.800 MHz FM | VHF  | ISS downlink (ARISS events)     |
| 70cm  | 434.000 MHz FM | UHF  | Occasional activity             |
"""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import numpy as np

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)


# Common SSTV operating frequencies with nominal tolerance.
SSTV_FREQUENCIES_HZ: list[tuple[float, str]] = [
    (14_230_000, "20m HF SSB"),
    (21_340_000, "15m HF SSB"),
    (28_680_000, "10m HF SSB"),
    (144_500_000, "2m simplex"),
    (145_500_000, "2m calling"),
    (145_800_000, "ISS downlink"),
    (434_000_000, "70cm"),
]

# Frequency match tolerance — narrower on VHF/UHF (tight frequency
# discipline), wider on HF (drift over a long path).
_HF_TOLERANCE_HZ = 3_000    # HF — SSB passband is ~2.4 kHz
_VHF_TOLERANCE_HZ = 5_000   # VHF/UHF — NBFM channel


def _sstv_mode_for_frequency(freq_hz: float) -> tuple[bool, str]:
    """Return (is_sstv_frequency, band_description) for a given freq."""
    for nominal, band in SSTV_FREQUENCIES_HZ:
        is_hf = nominal < 30_000_000
        tolerance = _HF_TOLERANCE_HZ if is_hf else _VHF_TOLERANCE_HZ
        if abs(freq_hz - nominal) <= tolerance:
            return True, band
    return False, ""


def library_available() -> bool:
    """Return True if the colaclanth/sstv library is importable."""
    try:
        import sstv.decode  # noqa: F401
        return True
    except ImportError:
        return False


class SstvDecoder(DecoderPlugin):
    """SSTV image decoder using the colaclanth/sstv pure-Python library.

    Accepts audio samples (not IQ) and produces a PNG image when the
    library successfully recognizes an SSTV VIS header and decodes a
    full frame. Short or incomplete audio buffers are expected to
    produce no output — that's normal operation, not a failure.
    """

    _AUDIO_RATE = 48_000  # Hz — colaclanth/sstv handles any rate but 48k is the SignalDeck default

    def __init__(self, image_dir: str = "data/images/sstv") -> None:
        self._image_dir = Path(image_dir)
        self._image_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "sstv"

    @property
    def protocols(self) -> list[str]:
        return ["sstv"]

    @property
    def input_type(self) -> str:
        return "audio"

    def can_decode(self, signal: SignalInfo) -> float:
        if not library_available():
            return 0.0
        is_sstv_freq, _ = _sstv_mode_for_frequency(signal.frequency_hz)
        if not is_sstv_freq:
            return 0.0
        # Moderate confidence — SSTV shares these frequencies with voice,
        # so being on the right freq doesn't guarantee the signal is SSTV.
        # Higher if the caller explicitly tagged it.
        if signal.protocol_hint == "sstv":
            return 0.90
        return 0.55

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        if not library_available():
            logger.warning(
                "sstv library not installed — install with "
                "`pip install git+https://github.com/colaclanth/sstv.git`"
            )
            return

        audio = await self._collect_audio(data_source)
        if audio is None or len(audio) < self._AUDIO_RATE:
            logger.debug(
                "SSTV: insufficient audio (%s samples) — need >=1 second",
                0 if audio is None else len(audio),
            )
            return

        # Write audio to a temp WAV file for the sstv library.
        wav_path = self._write_temp_wav(audio)

        try:
            image = self._decode_wav(wav_path)
        except Exception as e:
            # Most common failure: no VIS header found in the audio,
            # which the library reports via exception. Treat as "no
            # SSTV image in this chunk" rather than an error.
            logger.debug("SSTV decode returned no image: %s", e)
            image = None
        finally:
            try:
                Path(wav_path).unlink()
            except OSError:
                pass

        if image is None:
            return

        # Persist the image to image_dir and yield a result.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        band = _sstv_mode_for_frequency(signal.frequency_hz)[1] or "unknown_band"
        out_path = (
            self._image_dir
            / f"sstv_{band.replace(' ', '_')}_{timestamp}.png"
        )
        try:
            image.save(out_path, "PNG")
        except Exception as e:
            logger.warning("Failed to save SSTV image to %s: %s", out_path, e)
            return

        logger.info(
            "SSTV image decoded: %s (%dx%d) from %.3f MHz",
            out_path.name,
            image.width,
            image.height,
            signal.frequency_hz / 1e6,
        )

        yield DecoderResult(
            timestamp=datetime.now(timezone.utc),
            frequency=signal.frequency_hz,
            protocol="sstv",
            result_type="image",
            content={
                "image_path": str(out_path),
                "width": image.width,
                "height": image.height,
                "band": band,
            },
            metadata={
                "decoder": "sstv",
                "library": "colaclanth/sstv",
            },
        )

    async def decode_to_list(self, signal: SignalInfo, data_source) -> list[DecoderResult]:
        return [result async for result in self.decode(signal, data_source)]

    async def _collect_audio(self, data_source) -> np.ndarray | None:
        """Accept either a numpy array or an async iterator of chunks.

        Returns a 1-D float32 array of audio samples, or None if no data.
        """
        if isinstance(data_source, np.ndarray):
            return data_source.astype(np.float32, copy=False)
        chunks = []
        async for chunk in data_source:
            chunks.append(np.asarray(chunk, dtype=np.float32))
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def _write_temp_wav(self, audio: np.ndarray) -> str:
        """Write audio to a temp WAV file and return its path."""
        import soundfile as sf

        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, dir=str(self._image_dir)
        ) as tmp:
            tmp_path = tmp.name
        # Clip to [-1, 1] and save as PCM16.
        clipped = np.clip(audio, -1.0, 1.0)
        sf.write(tmp_path, clipped, self._AUDIO_RATE, subtype="PCM_16")
        return tmp_path

    def _decode_wav(self, wav_path: str):
        """Invoke the colaclanth/sstv decoder on a WAV file.

        Returns a PIL Image on success, raises on failure.
        """
        from sstv.decode import SSTVDecoder

        decoder = SSTVDecoder(wav_path)
        try:
            return decoder.decode()
        finally:
            decoder.close()
