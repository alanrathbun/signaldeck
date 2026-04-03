import asyncio
from unittest.mock import MagicMock, AsyncMock

import numpy as np
import pytest

from signaldeck.engine.scanner import (
    FrequencyScanner,
    ScanRange,
    DetectedSignal,
    compute_power_spectrum,
    estimate_noise_floor,
)


def test_scan_range():
    """ScanRange calculates step frequencies."""
    sr = ScanRange(start_hz=88e6, end_hz=108e6, step_hz=200e3)
    freqs = sr.frequencies()
    assert freqs[0] == 88e6
    assert freqs[-1] <= 108e6
    assert all(freqs[i] < freqs[i + 1] for i in range(len(freqs) - 1))


def test_compute_power_spectrum():
    """compute_power_spectrum returns power in dB for each FFT bin."""
    n = 1024
    samples = np.zeros(n, dtype=np.complex64)
    samples += 0.001 * (np.random.randn(n) + 1j * np.random.randn(n))  # noise floor
    k = 100
    samples += np.exp(2j * np.pi * k * np.arange(n) / n).astype(np.complex64)  # tone

    power_db = compute_power_spectrum(samples, fft_size=n)
    assert len(power_db) == n
    peak_bin = np.argmax(power_db)
    # After fftshift, bin k maps to (k + n/2) % n
    expected_bin = (k + n // 2) % n
    assert abs(peak_bin - expected_bin) <= 1
    assert power_db[peak_bin] > np.median(power_db) + 20


def test_estimate_noise_floor():
    """estimate_noise_floor returns the median power level."""
    power_db = np.full(1024, -90.0)
    power_db[100] = -30.0
    power_db[200] = -40.0
    noise = estimate_noise_floor(power_db)
    assert abs(noise - (-90.0)) < 1.0


def test_detect_signals_above_threshold():
    """Scanner finds signals above squelch threshold."""
    power_db = np.full(1024, -90.0)
    power_db[100:105] = -40.0
    power_db[500:503] = -50.0

    noise_floor = estimate_noise_floor(power_db)
    squelch = noise_floor + 10

    from signaldeck.engine.scanner import find_signals_in_spectrum
    signals = find_signals_in_spectrum(
        power_db=power_db,
        center_freq_hz=100e6,
        sample_rate=2e6,
        squelch_db=squelch,
    )
    assert len(signals) == 2
    assert signals[0].peak_power > signals[1].peak_power


def test_scan_range_from_config():
    """ScanRange can be created from config dict."""
    cfg = {"start_mhz": 118, "end_mhz": 137, "label": "Airband"}
    sr = ScanRange.from_config(cfg)
    assert sr.start_hz == 118e6
    assert sr.end_hz == 137e6
    assert sr.label == "Airband"
