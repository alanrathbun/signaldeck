"""Integration tests requiring a connected SDR device.

Run with: pytest tests/test_integration.py -v -m hardware
Skip with: pytest tests/ -v -m "not hardware"
"""
import asyncio

import numpy as np
import pytest

from signaldeck.engine.device_manager import DeviceManager
from signaldeck.engine.scanner import (
    FrequencyScanner,
    ScanRange,
    compute_power_spectrum,
    estimate_noise_floor,
)
from signaldeck.engine.audio_pipeline import fm_demodulate


def _hackrf_available() -> bool:
    try:
        mgr = DeviceManager()
        return len(mgr.enumerate()) > 0
    except Exception:
        return False


hardware = pytest.mark.skipif(
    not _hackrf_available(),
    reason="No SDR hardware connected",
)


@hardware
@pytest.mark.hardware
def test_device_enumerate_finds_hackrf():
    """Real HackRF is discovered."""
    mgr = DeviceManager()
    devices = mgr.enumerate()
    assert len(devices) >= 1
    drivers = [d.driver for d in devices]
    assert "hackrf" in drivers


@hardware
@pytest.mark.hardware
def test_read_samples_from_hackrf():
    """Can read IQ samples from HackRF."""
    mgr = DeviceManager()
    device = mgr.open(driver="hackrf")
    device.set_sample_rate(2_000_000)
    device.set_gain(40)
    device.tune(100_000_000)  # 100 MHz FM broadcast
    device.start_stream()

    samples = device.read_samples(1024)
    device.stop_stream()
    device.close()

    assert samples is not None
    assert len(samples) == 1024
    assert samples.dtype == np.complex64


@hardware
@pytest.mark.hardware
def test_power_spectrum_from_real_samples():
    """Power spectrum from real IQ data has reasonable values."""
    mgr = DeviceManager()
    device = mgr.open(driver="hackrf")
    device.set_sample_rate(2_000_000)
    device.set_gain(40)
    device.tune(100_000_000)
    device.start_stream()

    samples = device.read_samples(1024)
    device.stop_stream()
    device.close()

    power_db = compute_power_spectrum(samples, fft_size=1024)
    noise_floor = estimate_noise_floor(power_db)

    # Noise floor should be somewhere reasonable (not 0, not -inf)
    assert -120 < noise_floor < 0
    assert len(power_db) == 1024


@hardware
@pytest.mark.hardware
def test_sweep_broadcast_fm():
    """Sweep the FM broadcast band and find at least one station."""
    mgr = DeviceManager()
    device = mgr.open(driver="hackrf")
    device.set_gain(40)

    fm_range = ScanRange(start_hz=88e6, end_hz=108e6, step_hz=200e3, label="FM Broadcast")
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[fm_range],
        fft_size=1024,
        squelch_offset_db=10,
        sample_rate=2_000_000,
        dwell_time_s=0.05,
    )

    signals = asyncio.run(scanner.sweep_once())
    device.close()

    # There should be at least one FM station in any populated area
    assert len(signals) > 0
    # All should be in or near the FM band (allowing for FFT bin spread at edges)
    for s in signals:
        assert 87e6 <= s.frequency_hz <= 109e6
