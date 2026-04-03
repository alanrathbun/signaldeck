import shutil
from pathlib import Path
import numpy as np
import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.noaa_apt import NoaaAptDecoder, NOAA_SATELLITES

def test_noaa_apt_decoder_properties():
    decoder = NoaaAptDecoder()
    assert decoder.name == "noaa_apt"
    assert "noaa_apt" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_noaa_15():
    decoder = NoaaAptDecoder()
    signal = SignalInfo(frequency_hz=137.62e6, bandwidth_hz=40e3, peak_power=-60.0,
                        modulation="FM", protocol_hint="noaa_apt")
    assert decoder.can_decode(signal) > 0.8

def test_can_decode_noaa_18():
    decoder = NoaaAptDecoder()
    signal = SignalInfo(frequency_hz=137.9125e6, bandwidth_hz=40e3, peak_power=-60.0,
                        modulation="FM", protocol_hint="noaa_apt")
    assert decoder.can_decode(signal) > 0.8

def test_can_decode_noaa_19():
    decoder = NoaaAptDecoder()
    signal = SignalInfo(frequency_hz=137.1e6, bandwidth_hz=40e3, peak_power=-60.0,
                        modulation="FM", protocol_hint="noaa_apt")
    assert decoder.can_decode(signal) > 0.8

def test_cannot_decode_non_noaa():
    decoder = NoaaAptDecoder()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) == 0.0

def test_noaa_satellite_frequencies():
    assert len(NOAA_SATELLITES) >= 3
    names = [s["name"] for s in NOAA_SATELLITES]
    assert "NOAA-15" in names and "NOAA-18" in names and "NOAA-19" in names

async def test_decode_produces_image_result(tmp_path):
    decoder = NoaaAptDecoder(image_dir=str(tmp_path))
    signal = SignalInfo(frequency_hz=137.1e6, bandwidth_hz=40e3, peak_power=-60.0,
                        modulation="FM", protocol_hint="noaa_apt")
    iq_data = np.zeros(48000, dtype=np.complex64)
    async def iq_source():
        yield iq_data
    results = []
    async for result in decoder.decode(signal, iq_source()):
        results.append(result)
    assert len(results) >= 1
    assert results[0].protocol == "noaa_apt"
    assert results[0].result_type == "image"
