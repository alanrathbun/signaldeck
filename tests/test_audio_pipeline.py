import wave
from pathlib import Path

import numpy as np
import pytest

from signaldeck.engine.audio_pipeline import (
    fm_demodulate,
    am_demodulate,
    save_audio_wav,
    AudioRecorder,
)


def test_fm_demodulate_produces_audio():
    """FM demodulation of a modulated signal produces non-zero audio."""
    n = 48000
    t = np.arange(n) / 2e6
    mod_freq = 1000
    deviation = 75000
    phase = 2 * np.pi * (0 * t + deviation * np.sin(2 * np.pi * mod_freq * t) / mod_freq)
    iq = np.exp(1j * np.cumsum(2 * np.pi * 0 * np.ones(n) / 2e6 + np.diff(phase, prepend=0))).astype(np.complex64)

    audio = fm_demodulate(iq, sample_rate=2e6, audio_rate=48000)
    assert len(audio) > 0
    assert np.max(np.abs(audio)) > 0.01


def test_am_demodulate_produces_audio():
    """AM demodulation extracts envelope."""
    n = 48000
    t = np.arange(n) / 2e6
    mod_freq = 1000
    carrier = np.exp(2j * np.pi * 100e3 * t)
    envelope = 1.0 + 0.5 * np.sin(2 * np.pi * mod_freq * t)
    iq = (carrier * envelope).astype(np.complex64)

    audio = am_demodulate(iq, sample_rate=2e6, audio_rate=48000)
    assert len(audio) > 0
    assert np.max(np.abs(audio)) > 0.01


def test_save_audio_wav(tmp_path: Path):
    """save_audio_wav writes a valid WAV file."""
    audio = np.sin(2 * np.pi * 440 * np.arange(48000) / 48000).astype(np.float32)
    path = str(tmp_path / "test.wav")
    save_audio_wav(audio, path, sample_rate=48000)

    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 48000
        assert wf.getnframes() == 48000


def test_audio_recorder_creates_file(tmp_path: Path):
    """AudioRecorder writes audio chunks to a WAV file."""
    recorder = AudioRecorder(output_dir=str(tmp_path), sample_rate=48000)
    recording_path = recorder.start("test_signal")

    chunk = np.sin(2 * np.pi * 440 * np.arange(4800) / 48000).astype(np.float32)
    recorder.write(chunk)
    recorder.write(chunk)
    recorder.stop()

    assert Path(recording_path).exists()
    with wave.open(recording_path, "rb") as wf:
        assert wf.getnframes() == 9600
