import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from signaldeck.engine.scanner import FrequencyScanner, ScanRange


def _make_mock_gqrx_device(strength_map: dict[float, float], default: float = -90.0):
    """Create a mock GqrxDevice that returns configured signal strengths.

    strength_map: {frequency_hz: strength_dbfs}
    """
    device = MagicMock()
    device.is_gqrx = True
    device.read_samples = MagicMock(return_value=None)
    device.set_sample_rate = MagicMock()
    device.start_stream = MagicMock()
    device.stop_stream = MagicMock()

    async def mock_tune(freq):
        device._current_freq = freq

    async def mock_strength():
        freq = getattr(device, "_current_freq", 0)
        if not strength_map:
            return default
        closest = min(strength_map.keys(), key=lambda f: abs(f - freq))
        if abs(closest - freq) < 100_000:  # within 100 kHz
            return strength_map[closest]
        return default

    device.tune = AsyncMock(side_effect=mock_tune)
    device.get_signal_strength = AsyncMock(side_effect=mock_strength)
    return device


@pytest.mark.asyncio
async def test_strength_sweep_detects_signals():
    """strength_sweep_once finds signals above threshold."""
    device = _make_mock_gqrx_device({
        100.0e6: -35.0,
        100.4e6: -45.0,
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    signals = await scanner.strength_sweep_once()
    assert len(signals) == 2
    assert signals[0].peak_power > signals[1].peak_power


@pytest.mark.asyncio
async def test_strength_sweep_filters_weak_signals():
    """strength_sweep_once ignores signals below squelch."""
    device = _make_mock_gqrx_device({
        100.0e6: -85.0,
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    signals = await scanner.strength_sweep_once()
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_strength_sweep_calls_fft_callback():
    """strength_sweep_once broadcasts power data to fft callback."""
    device = _make_mock_gqrx_device({100.0e6: -40.0})
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[ScanRange(start_hz=99.8e6, end_hz=100.8e6, step_hz=200_000)],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    callback_data = []

    async def on_fft(center_freq, sample_rate, power_db):
        callback_data.append((center_freq, power_db))

    await scanner.strength_sweep_once(fft_callback=on_fft)
    assert len(callback_data) > 0
    freq, power = callback_data[0]
    assert isinstance(power, np.ndarray)


from signaldeck.storage.models import Bookmark
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_bookmark_scan_detects_active():
    """bookmark_scan_once detects active bookmarked frequencies."""
    device = _make_mock_gqrx_device({
        162.400e6: -30.0,
        162.475e6: -85.0,
    })
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    bookmarks = [
        Bookmark(frequency=162.400e6, label="NOAA Weather", modulation="FM",
                 decoder="weather", priority=5, camp_on_active=False),
        Bookmark(frequency=162.475e6, label="NOAA 2", modulation="FM",
                 decoder="weather", priority=3, camp_on_active=False),
    ]
    signals = await scanner.bookmark_scan_once(bookmarks)
    assert len(signals) == 1
    assert signals[0].frequency_hz == 162.400e6


@pytest.mark.asyncio
async def test_bookmark_scan_empty_bookmarks():
    """bookmark_scan_once returns empty list with no bookmarks."""
    device = _make_mock_gqrx_device({})
    scanner = FrequencyScanner(
        device=device,
        scan_ranges=[],
        squelch_offset_db=10.0,
        dwell_time_s=0.0,
    )
    signals = await scanner.bookmark_scan_once([])
    assert signals == []
