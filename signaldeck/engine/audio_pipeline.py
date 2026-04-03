import logging
import wave
from datetime import datetime, timezone
from math import gcd
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.signal import resample_poly

logger = logging.getLogger(__name__)


def fm_demodulate(
    iq_samples: NDArray[np.complex64],
    sample_rate: float,
    audio_rate: float = 48000,
) -> NDArray[np.float32]:
    product = iq_samples[1:] * np.conj(iq_samples[:-1])
    phase_diff = np.angle(product)
    audio = (phase_diff / np.pi).astype(np.float32)

    if sample_rate != audio_rate:
        audio = _resample(audio, sample_rate, audio_rate)

    return audio


def am_demodulate(
    iq_samples: NDArray[np.complex64],
    sample_rate: float,
    audio_rate: float = 48000,
) -> NDArray[np.float32]:
    envelope = np.abs(iq_samples).astype(np.float32)
    envelope -= np.mean(envelope)
    peak = np.max(np.abs(envelope))
    if peak > 0:
        envelope /= peak

    if sample_rate != audio_rate:
        envelope = _resample(envelope, sample_rate, audio_rate)

    return envelope


def _resample(audio: NDArray[np.float32], from_rate: float, to_rate: float) -> NDArray[np.float32]:
    from_int = int(from_rate)
    to_int = int(to_rate)
    divisor = gcd(from_int, to_int)
    up = to_int // divisor
    down = from_int // divisor
    return resample_poly(audio, up, down).astype(np.float32)


def save_audio_wav(
    audio: NDArray[np.float32],
    file_path: str,
    sample_rate: int = 48000,
) -> None:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)

    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())

    logger.debug("Saved %d samples to %s", len(audio), file_path)


class AudioRecorder:
    def __init__(self, output_dir: str, sample_rate: int = 48000) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._sample_rate = sample_rate
        self._wf: wave.Wave_write | None = None
        self._path: str | None = None

    def start(self, label: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{label}.wav"
        self._path = str(self._output_dir / filename)
        self._wf = wave.open(self._path, "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(self._sample_rate)
        logger.debug("Recording started: %s", self._path)
        return self._path

    def write(self, audio: NDArray[np.float32]) -> None:
        if self._wf is None:
            return
        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = (clipped * 32767).astype(np.int16)
        self._wf.writeframes(pcm16.tobytes())

    def stop(self) -> str | None:
        if self._wf is not None:
            self._wf.close()
            self._wf = None
            logger.debug("Recording stopped: %s", self._path)
        return self._path
