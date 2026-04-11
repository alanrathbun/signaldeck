"""Tests for the fldigi WEFAX decoder (Tier 1.2)."""
from unittest.mock import patch, MagicMock

import pytest

from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.fldigi_wefax import (
    FldigiWefaxDecoder,
    HF_WEFAX_FREQUENCIES_HZ,
    _frequency_in_wefax_band,
    tool_available,
)


def test_fldigi_wefax_properties():
    decoder = FldigiWefaxDecoder()
    assert decoder.name == "fldigi_wefax"
    assert "wefax" in decoder.protocols
    assert decoder.input_type == "audio"


def test_hf_wefax_frequency_list_covers_known_stations():
    # NMF Boston 4235 kHz, NMG New Orleans 8503.9 kHz, KVM70 Hawaii 16135 kHz
    assert 4235_000 in HF_WEFAX_FREQUENCIES_HZ
    assert 8503_900 in HF_WEFAX_FREQUENCIES_HZ
    assert 16135_000 in HF_WEFAX_FREQUENCIES_HZ


@pytest.mark.parametrize(
    "freq_hz,expected",
    [
        (4235_000, True),     # exact
        (4234_500, True),     # within 2 kHz
        (4237_000, True),     # within 2 kHz
        (4240_000, False),    # 5 kHz off — outside tolerance
        (100_300_000, False), # FM broadcast — not WEFAX
        (137_100_000, False), # NOAA APT — not HF WEFAX
    ],
)
def test_frequency_in_wefax_band(freq_hz, expected):
    assert _frequency_in_wefax_band(freq_hz) is expected


def test_can_decode_zero_when_fldigi_missing():
    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=False):
        decoder = FldigiWefaxDecoder()
        signal = SignalInfo(
            frequency_hz=4235_000,
            bandwidth_hz=3000,
            peak_power=-70.0,
            modulation="USB",
            protocol_hint="wefax",
        )
        assert decoder.can_decode(signal) == 0.0


def test_can_decode_high_when_fldigi_present_and_freq_matches():
    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=True):
        decoder = FldigiWefaxDecoder()
        signal = SignalInfo(
            frequency_hz=4235_000,
            bandwidth_hz=3000,
            peak_power=-70.0,
            modulation="USB",
            protocol_hint="wefax",
        )
        assert decoder.can_decode(signal) >= 0.80


def test_can_decode_zero_for_non_wefax_frequency():
    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=True):
        decoder = FldigiWefaxDecoder()
        signal = SignalInfo(
            frequency_hz=100_300_000,  # FM broadcast
            bandwidth_hz=200_000,
            peak_power=-40.0,
            modulation="FM",
        )
        assert decoder.can_decode(signal) == 0.0


async def test_decode_skips_when_fldigi_not_installed(tmp_path):
    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=False):
        decoder = FldigiWefaxDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=4235_000,
            bandwidth_hz=3000,
            peak_power=-70.0,
            modulation="USB",
        )
        results = await decoder.decode_to_list(signal, None)
        assert results == []


async def test_decode_skips_when_fldigi_xmlrpc_unreachable(tmp_path):
    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=True), \
         patch(
             "signaldeck.decoders.fldigi_wefax._fldigi_xmlrpc_reachable",
             return_value=False,
         ):
        decoder = FldigiWefaxDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=4235_000,
            bandwidth_hz=3000,
            peak_power=-70.0,
            modulation="USB",
        )
        results = await decoder.decode_to_list(signal, None)
        assert results == []


async def test_decode_yields_status_result_when_fldigi_reachable(tmp_path):
    """When fldigi is reachable, decoder yields a status DecoderResult
    indicating WEFAX mode was set but audio routing is still manual."""
    mock_proxy = MagicMock()
    mock_proxy.modem.set_by_name = MagicMock(return_value=None)

    with patch("signaldeck.decoders.fldigi_wefax.tool_available", return_value=True), \
         patch(
             "signaldeck.decoders.fldigi_wefax._fldigi_xmlrpc_reachable",
             return_value=True,
         ), \
         patch(
             "signaldeck.decoders.fldigi_wefax.ServerProxy",
             return_value=mock_proxy,
         ):
        decoder = FldigiWefaxDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=4235_000,
            bandwidth_hz=3000,
            peak_power=-70.0,
            modulation="USB",
        )
        results = await decoder.decode_to_list(signal, None)

    assert len(results) == 1
    assert results[0].protocol == "wefax"
    assert results[0].result_type == "status"
    assert results[0].content["setup_required"] is True
    mock_proxy.modem.set_by_name.assert_called_once_with("WEFAX-IOC576")


def test_tool_available_returns_bool():
    assert isinstance(tool_available(), bool)
