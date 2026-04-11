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
    find_signals_in_spectrum,
)
from signaldeck.engine.scan_presets import resolve_sweep_ranges


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

    signals = find_signals_in_spectrum(
        power_db=power_db,
        center_freq_hz=100e6,
        sample_rate=2e6,
        squelch_db=squelch,
    )
    assert len(signals) == 2
    assert signals[0].peak_power > signals[1].peak_power
    assert "prominence_db" in (signals[0].features or {})


def test_detect_broadcast_fm_wideband_signal():
    power_db = np.full(2048, -90.0)
    power_db[930:1090] = -80.0
    power_db[980:1040] = -62.0
    power_db[1008:1016] = -48.0

    noise_floor = estimate_noise_floor(power_db)
    squelch = noise_floor + 10
    signals = find_signals_in_spectrum(
        power_db=power_db,
        center_freq_hz=99.5e6,
        sample_rate=2e6,
        squelch_db=squelch,
    )

    fm_like = [s for s in signals if s.bandwidth_hz >= 100_000]
    assert fm_like, "expected a wideband FM-like detection"
    assert 88e6 <= fm_like[0].frequency_hz <= 108e6


def test_scan_range_from_config():
    """ScanRange can be created from config dict."""
    cfg = {"start_mhz": 118, "end_mhz": 137, "label": "Airband", "step_khz": 25, "priority": 19}
    sr = ScanRange.from_config(cfg)
    assert sr.start_hz == 118e6
    assert sr.end_hz == 137e6
    assert sr.step_hz == 25e3
    assert sr.label == "Airband"
    assert sr.priority == 19


def test_resolve_sweep_ranges_scan_ranges_are_authoritative():
    """When the user has explicit sweep_ranges, profiles must be ignored.

    Previously profiles silently contributed additional ranges alongside
    the user's list, which meant unchecking every range except Broadcast FM
    still swept dozens of other bands via the enabled profiles.
    """
    scanner_cfg = {
        "scan_profiles": ["marine_weather", "digital_signal_hunting"],
        "sweep_ranges": [{"label": "Custom", "start_mhz": 50, "end_mhz": 51, "priority": 30}],
    }
    ranges = resolve_sweep_ranges(scanner_cfg)
    labels = [rng["label"] for rng in ranges]
    assert labels == ["Custom"]
    assert "Marine VHF" not in labels
    assert "433 MHz ISM" not in labels


def test_resolve_sweep_ranges_falls_back_to_profiles_when_empty():
    """When the user has no explicit sweep_ranges, enabled profiles still
    supply the sweep plan — this keeps the first-run workflow working."""
    scanner_cfg = {
        "scan_profiles": ["marine_weather"],
        "sweep_ranges": [],
    }
    ranges = resolve_sweep_ranges(scanner_cfg)
    labels = [rng["label"] for rng in ranges]
    assert "Marine VHF" in labels
    assert "NOAA Weather" in labels


def test_resolve_sweep_ranges_single_broadcast_fm_matches_user_report():
    """The exact user-reported scenario: one Broadcast FM range plus every
    stock profile checked on. Only Broadcast FM should be swept."""
    scanner_cfg = {
        "scan_profiles": [
            "rtl_priority_search",
            "civil_aircraft",
            "likely_local_voice",
            "marine_weather",
            "digital_signal_hunting",
            "tv_and_wideband",
        ],
        "sweep_ranges": [
            {"label": "Broadcast FM", "start_mhz": 88.0, "end_mhz": 108.0, "step_khz": 200, "priority": 18},
        ],
    }
    ranges = resolve_sweep_ranges(scanner_cfg)
    assert len(ranges) == 1
    assert ranges[0]["label"] == "Broadcast FM"


def test_resolve_sweep_ranges_dedupes_same_range_with_different_labels():
    scanner_cfg = {
        "scan_profiles": ["custom_only"],
        "sweep_ranges": [
            {"label": "Range A", "start_mhz": 88.0, "end_mhz": 108.0, "step_khz": 200, "priority": 18},
            {"label": "Range B", "start_mhz": 88.0, "end_mhz": 108.0, "step_khz": 200, "priority": 22},
        ],
    }
    ranges = resolve_sweep_ranges(scanner_cfg)
    assert len(ranges) == 1
    assert ranges[0]["priority"] == 22


@pytest.mark.asyncio
async def test_sweep_once_emits_incremental_signal_callback():
    device = MagicMock()
    device.read_samples.return_value = np.ones(1024, dtype=np.complex64)
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=100e6, end_hz=100.2e6, step_hz=200e3)],
        fft_size=1024,
        squelch_offset_db=10,
        dwell_time_s=0,
    )

    fake_detected = [
        DetectedSignal(
            frequency_hz=100.1e6,
            bandwidth_hz=12_500,
            peak_power=-30.0,
            avg_power=-35.0,
            bin_start=10,
            bin_end=20,
            features={"prominence_db": 15.0},
        )
    ]
    callback = AsyncMock()

    from signaldeck.engine import scanner as scanner_module

    original = scanner_module.find_signals_in_spectrum
    scanner_module.find_signals_in_spectrum = MagicMock(return_value=fake_detected)
    try:
        signals = await scanner.sweep_once(signal_callback=callback)
    finally:
        scanner_module.find_signals_in_spectrum = original

    assert signals == fake_detected
    callback.assert_awaited_once_with(fake_detected)
