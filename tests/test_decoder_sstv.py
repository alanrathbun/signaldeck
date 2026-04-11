"""Tests for the SSTV decoder (Tier 2.1)."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.sstv import (
    SstvDecoder,
    SSTV_FREQUENCIES_HZ,
    _sstv_mode_for_frequency,
    library_available,
)


def test_sstv_decoder_properties():
    decoder = SstvDecoder()
    assert decoder.name == "sstv"
    assert "sstv" in decoder.protocols
    assert decoder.input_type == "audio"


def test_sstv_frequency_list_covers_key_bands():
    freqs = {hz for hz, _ in SSTV_FREQUENCIES_HZ}
    # 20m HF + 2m FM calling + ISS downlink must all be present
    assert 14_230_000 in freqs
    assert 145_500_000 in freqs
    assert 145_800_000 in freqs


@pytest.mark.parametrize(
    "freq_hz,expected_hit",
    [
        (14_230_000, True),    # 20m exact
        (14_231_000, True),    # 20m within HF tolerance
        (14_235_000, False),   # 5 kHz off — outside HF tolerance (3 kHz)
        (145_500_000, True),   # 2m calling exact
        (145_504_000, True),   # within VHF tolerance (5 kHz)
        (145_510_000, False),  # 10 kHz off — outside VHF tolerance
        (145_800_000, True),   # ISS
        (100_300_000, False),  # FM broadcast — not SSTV
    ],
)
def test_frequency_matching_with_tolerance(freq_hz, expected_hit):
    hit, _ = _sstv_mode_for_frequency(freq_hz)
    assert hit is expected_hit


def test_library_available_returns_bool():
    assert isinstance(library_available(), bool)


def test_can_decode_zero_when_library_missing():
    with patch("signaldeck.decoders.sstv.library_available", return_value=False):
        decoder = SstvDecoder()
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="sstv",
        )
        assert decoder.can_decode(signal) == 0.0


def test_can_decode_high_when_library_present_and_freq_matches():
    with patch("signaldeck.decoders.sstv.library_available", return_value=True):
        decoder = SstvDecoder()
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="sstv",
        )
        # With explicit sstv hint, confidence is 0.90
        assert decoder.can_decode(signal) == 0.90


def test_can_decode_moderate_when_no_hint():
    with patch("signaldeck.decoders.sstv.library_available", return_value=True):
        decoder = SstvDecoder()
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
        )
        # No hint — lower confidence because voice also uses these freqs
        assert 0.5 < decoder.can_decode(signal) < 0.9


def test_can_decode_zero_for_non_sstv_frequency():
    with patch("signaldeck.decoders.sstv.library_available", return_value=True):
        decoder = SstvDecoder()
        signal = SignalInfo(
            frequency_hz=100_300_000,  # FM broadcast
            bandwidth_hz=200_000,
            peak_power=-40.0,
            modulation="FM",
        )
        assert decoder.can_decode(signal) == 0.0


async def test_decode_skips_when_library_not_installed(tmp_path):
    with patch("signaldeck.decoders.sstv.library_available", return_value=False):
        decoder = SstvDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
        )
        audio = np.zeros(48000, dtype=np.float32)
        results = await decoder.decode_to_list(signal, audio)
        assert results == []


async def test_decode_skips_when_audio_too_short(tmp_path):
    with patch("signaldeck.decoders.sstv.library_available", return_value=True):
        decoder = SstvDecoder(image_dir=str(tmp_path))
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
        )
        # Less than 1 second of audio
        audio = np.zeros(10_000, dtype=np.float32)
        results = await decoder.decode_to_list(signal, audio)
        assert results == []


async def test_decode_yields_image_result_when_library_succeeds(tmp_path):
    """With the library mocked to return a fake PIL image, decode()
    yields one image DecoderResult with an image_path on disk."""
    from PIL import Image
    fake_image = Image.new("RGB", (320, 256), color=(200, 100, 50))

    decoder = SstvDecoder(image_dir=str(tmp_path))

    with patch("signaldeck.decoders.sstv.library_available", return_value=True), \
         patch.object(decoder, "_decode_wav", return_value=fake_image):
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
            protocol_hint="sstv",
        )
        audio = np.zeros(48000 * 5, dtype=np.float32)  # 5 seconds
        results = await decoder.decode_to_list(signal, audio)

    assert len(results) == 1
    assert results[0].protocol == "sstv"
    assert results[0].result_type == "image"
    assert results[0].content["width"] == 320
    assert results[0].content["height"] == 256
    assert results[0].content["image_path"].endswith(".png")
    # The file must actually exist on disk after decode
    from pathlib import Path as _P
    assert _P(results[0].content["image_path"]).is_file()


async def test_decode_yields_nothing_when_library_cannot_find_vis_header(tmp_path):
    """The colaclanth/sstv library raises when no VIS header is present.
    Treat that as 'no image in this chunk' not an error."""
    decoder = SstvDecoder(image_dir=str(tmp_path))

    with patch("signaldeck.decoders.sstv.library_available", return_value=True), \
         patch.object(
             decoder, "_decode_wav", side_effect=ValueError("No VIS header found")
         ):
        signal = SignalInfo(
            frequency_hz=145_500_000,
            bandwidth_hz=12500,
            peak_power=-60.0,
            modulation="FM",
        )
        audio = np.zeros(48000 * 5, dtype=np.float32)
        results = await decoder.decode_to_list(signal, audio)

    assert results == []
