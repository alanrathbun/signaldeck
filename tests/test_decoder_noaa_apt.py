"""Tests for the SatDump-backed NOAA APT / Meteor-M LRPT decoder.

Since SatDump is a heavy external C++ binary that probably isn't installed
in most test environments, most tests mock `tool_available()` and/or
`ProcessSupervisor.run_once` rather than actually running the binary.
"""
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.noaa_apt import (
    NoaaAptDecoder,
    WEATHER_SATELLITES,
    SatelliteInfo,
    _satellite_for_frequency,
    tool_available,
)


def test_noaa_apt_decoder_properties():
    decoder = NoaaAptDecoder()
    assert decoder.name == "noaa_apt"
    assert "noaa_apt" in decoder.protocols
    assert "meteor_m_lrpt" in decoder.protocols
    assert decoder.input_type == "iq"


def test_weather_satellites_cover_nominal_frequencies():
    """The constant list must include all three NOAA APT birds and at
    least one Meteor-M LRPT entry. This is a guard against accidental
    deletion during future refactors."""
    assert len(WEATHER_SATELLITES) >= 4
    names = {s.name for s in WEATHER_SATELLITES}
    assert "NOAA-15" in names
    assert "NOAA-18" in names
    assert "NOAA-19" in names
    assert any("Meteor" in n for n in names)


@pytest.mark.parametrize(
    "freq_hz,expected_name",
    [
        (137.620e6, "NOAA-15"),
        (137.9125e6, "NOAA-18"),
        (137.100e6, "NOAA-19"),
        # Within tolerance window
        (137.618e6, "NOAA-15"),
        (137.622e6, "NOAA-15"),
    ],
)
def test_satellite_for_frequency_matches_within_tolerance(freq_hz, expected_name):
    sat = _satellite_for_frequency(freq_hz)
    assert sat is not None
    assert sat.name == expected_name


@pytest.mark.parametrize(
    "freq_hz",
    [
        100.3e6,   # FM broadcast
        162.4e6,   # NOAA weather radio
        460.0e6,   # GMRS
        433.92e6,  # ISM
    ],
)
def test_satellite_for_frequency_rejects_non_satellite(freq_hz):
    assert _satellite_for_frequency(freq_hz) is None


def test_can_decode_zero_when_satdump_missing():
    """Without satdump on PATH, can_decode must return 0 so the registry
    doesn't try to dispatch work that'll fail."""
    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=False):
        decoder = NoaaAptDecoder()
        signal = SignalInfo(
            frequency_hz=137.100e6,
            bandwidth_hz=40e3,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="noaa_apt",
        )
        assert decoder.can_decode(signal) == 0.0


def test_can_decode_high_when_satdump_present_and_freq_matches():
    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=True):
        decoder = NoaaAptDecoder()
        signal = SignalInfo(
            frequency_hz=137.100e6,
            bandwidth_hz=40e3,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="noaa_apt",
        )
        assert decoder.can_decode(signal) >= 0.8


def test_can_decode_zero_for_off_frequency_even_when_satdump_present():
    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=True):
        decoder = NoaaAptDecoder()
        signal = SignalInfo(
            frequency_hz=460.0e6,  # GMRS, definitely not a weather sat
            bandwidth_hz=12500.0,
            peak_power=-50.0,
            modulation="FM",
        )
        assert decoder.can_decode(signal) == 0.0


async def test_decode_skips_when_satdump_not_installed(tmp_path):
    """With satdump absent, decode() yields nothing and logs a warning
    (rather than raising)."""
    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=False):
        decoder = NoaaAptDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=137.100e6,
            bandwidth_hz=40e3,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="noaa_apt",
        )
        iq = np.zeros(1024, dtype=np.complex64)
        results = await decoder.decode_to_list(signal, iq)
        assert results == []


async def test_decode_skips_when_frequency_outside_satellite_window(tmp_path):
    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=True):
        decoder = NoaaAptDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=100.3e6,  # FM broadcast
            bandwidth_hz=200e3,
            peak_power=-40.0,
            modulation="FM",
        )
        iq = np.zeros(1024, dtype=np.complex64)
        results = await decoder.decode_to_list(signal, iq)
        assert results == []


async def test_decode_yields_image_results_when_satdump_produces_pngs(tmp_path):
    """With satdump mocked and a fake PNG dropped into the output dir,
    decode() yields one DecoderResult per image."""
    decoder = NoaaAptDecoder(image_dir=str(tmp_path))

    # Mock supervisor.run_once to succeed without actually running satdump
    async def fake_run_once(config, on_output=None, timeout=None):
        # Simulate SatDump dropping a PNG into the output directory.
        # The output dir is the 5th positional arg to satdump after
        # [pipeline_id, input_level, input_file, output_dir].
        out_dir_arg = config.command[4]
        from pathlib import Path as _Path
        out = _Path(out_dir_arg)
        out.mkdir(parents=True, exist_ok=True)
        (out / "MSU-MR_ch1.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        return 0

    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=True), \
         patch.object(
             decoder._supervisor, "run_once", new=AsyncMock(side_effect=fake_run_once)
         ):
        signal = SignalInfo(
            frequency_hz=137.100e6,
            bandwidth_hz=40e3,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="noaa_apt",
            sample_rate=2_000_000,
        )
        iq = np.zeros(48000, dtype=np.complex64)
        results = await decoder.decode_to_list(signal, iq)

    assert len(results) == 1
    assert results[0].result_type == "image"
    assert results[0].protocol == "noaa_apt_demod"
    assert results[0].content["satellite"] == "NOAA-19"
    assert results[0].content["image_path"].endswith(".png")


async def test_decode_yields_nothing_when_satdump_produces_no_images(tmp_path):
    decoder = NoaaAptDecoder(image_dir=str(tmp_path))

    async def fake_run_once_empty(config, on_output=None, timeout=None):
        # Create the out dir but drop no images (a weak-signal pass)
        out_dir_arg = config.command[4]
        from pathlib import Path as _Path
        _Path(out_dir_arg).mkdir(parents=True, exist_ok=True)
        return 0

    with patch("signaldeck.decoders.noaa_apt.tool_available", return_value=True), \
         patch.object(
             decoder._supervisor, "run_once", new=AsyncMock(side_effect=fake_run_once_empty)
         ):
        signal = SignalInfo(
            frequency_hz=137.100e6,
            bandwidth_hz=40e3,
            peak_power=-60.0,
            modulation="FM",
            sample_rate=2_000_000,
        )
        iq = np.zeros(48000, dtype=np.complex64)
        results = await decoder.decode_to_list(signal, iq)

    assert results == []


def test_tool_available_returns_bool():
    # Not asserting True/False because it depends on the host. Just that
    # the return type is bool — guards against the function ever raising.
    assert isinstance(tool_available(), bool)
