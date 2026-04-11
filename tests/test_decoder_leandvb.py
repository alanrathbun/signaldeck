"""Tests for the leandvb DATV decoder (Tier 2.2)."""
from unittest.mock import patch

import numpy as np
import pytest

from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.leandvb import (
    LeandvbDecoder,
    DATV_FREQUENCY_RANGES_HZ,
    _is_datv_frequency,
    tool_available,
)


def test_leandvb_decoder_properties():
    decoder = LeandvbDecoder()
    assert decoder.name == "leandvb_datv"
    assert "dvb_s" in decoder.protocols
    assert "dvb_s2" in decoder.protocols
    assert "datv" in decoder.protocols
    assert decoder.input_type == "iq"


def test_datv_frequency_ranges_cover_qo100_and_amateur_bands():
    # QO-100 WB center ~10.490 GHz
    qo100 = [(lo, hi, d) for lo, hi, d in DATV_FREQUENCY_RANGES_HZ if "QO-100" in d]
    assert qo100, "QO-100 range missing"
    # 23cm DATV around 1255 MHz
    assert any(
        lo <= 1_255_000_000 <= hi for lo, hi, _ in DATV_FREQUENCY_RANGES_HZ
    )


@pytest.mark.parametrize(
    "freq_hz,expected_hit",
    [
        (10_490_000_000, True),    # QO-100 center
        (10_489_500_000, True),    # inside QO-100 range
        (10_495_000_000, False),   # above QO-100 range
        (1_260_000_000, True),     # 23cm mid-band
        (2_420_000_000, True),     # 13cm
        (2_402_000_000, True),     # ISS S-band
        (100_300_000, False),      # FM broadcast
        (146_520_000, False),      # 2m voice
    ],
)
def test_is_datv_frequency(freq_hz, expected_hit):
    hit, _ = _is_datv_frequency(freq_hz)
    assert hit is expected_hit


def test_can_decode_zero_when_tools_missing():
    with patch("signaldeck.decoders.leandvb.tool_available", return_value=False):
        decoder = LeandvbDecoder()
        signal = SignalInfo(
            frequency_hz=10_490_000_000,
            bandwidth_hz=2_000_000,
            peak_power=-70.0,
            modulation="QPSK",
            protocol_hint="datv",
        )
        assert decoder.can_decode(signal) == 0.0


def test_can_decode_high_with_hint():
    with patch("signaldeck.decoders.leandvb.tool_available", return_value=True):
        decoder = LeandvbDecoder()
        signal = SignalInfo(
            frequency_hz=10_490_000_000,
            bandwidth_hz=2_000_000,
            peak_power=-70.0,
            modulation="QPSK",
            protocol_hint="datv",
        )
        assert decoder.can_decode(signal) >= 0.80


def test_can_decode_moderate_without_hint():
    with patch("signaldeck.decoders.leandvb.tool_available", return_value=True):
        decoder = LeandvbDecoder()
        signal = SignalInfo(
            frequency_hz=10_490_000_000,
            bandwidth_hz=2_000_000,
            peak_power=-70.0,
            modulation="QPSK",
        )
        # No hint — moderate confidence because DATV shares spectrum
        conf = decoder.can_decode(signal)
        assert 0.2 < conf < 0.8


def test_can_decode_zero_for_non_datv_frequency():
    with patch("signaldeck.decoders.leandvb.tool_available", return_value=True):
        decoder = LeandvbDecoder()
        signal = SignalInfo(
            frequency_hz=100_300_000,  # FM broadcast
            bandwidth_hz=200_000,
            peak_power=-40.0,
            modulation="FM",
        )
        assert decoder.can_decode(signal) == 0.0


async def test_decode_skips_when_tools_not_installed(tmp_path):
    with patch("signaldeck.decoders.leandvb.tool_available", return_value=False):
        decoder = LeandvbDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=10_490_000_000,
            bandwidth_hz=2_000_000,
            peak_power=-70.0,
            modulation="QPSK",
        )
        iq = np.zeros(1024, dtype=np.complex64)
        results = await decoder.decode_to_list(signal, iq)
        assert results == []


def test_tool_available_returns_bool():
    assert isinstance(tool_available(), bool)
