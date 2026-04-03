import asyncio
from datetime import datetime, timezone
import numpy as np
import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.fm_am import FmAmDecoder

@pytest.fixture
def decoder():
    return FmAmDecoder(recording_dir="/tmp/signaldeck_test")

def test_fm_am_decoder_properties(decoder):
    assert decoder.name == "fm_am"
    assert "fm" in decoder.protocols
    assert "am" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_wideband_fm(decoder):
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) > 0.5

def test_can_decode_narrowband_fm(decoder):
    signal = SignalInfo(frequency_hz=155e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="narrowband_fm")
    assert decoder.can_decode(signal) > 0.5

def test_can_decode_am(decoder):
    signal = SignalInfo(frequency_hz=121.5e6, bandwidth_hz=8e3, peak_power=-45.0,
                        modulation="AM", protocol_hint="aviation")
    assert decoder.can_decode(signal) > 0.5

def test_cannot_decode_adsb(decoder):
    signal = SignalInfo(frequency_hz=1090e6, bandwidth_hz=1e6, peak_power=-40.0,
                        modulation="PULSE", protocol_hint="adsb")
    assert decoder.can_decode(signal) == 0.0

async def test_decode_fm_signal(decoder, tmp_path):
    decoder = FmAmDecoder(recording_dir=str(tmp_path))
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    n = 48000
    t = np.arange(n) / 2e6
    mod_freq = 1000
    deviation = 75000
    phase = np.cumsum(2 * np.pi * deviation * np.sin(2 * np.pi * mod_freq * t) / 2e6)
    iq_data = np.exp(1j * phase).astype(np.complex64)

    async def iq_source():
        yield iq_data

    results = []
    async for result in decoder.decode(signal, iq_source()):
        results.append(result)
    assert len(results) >= 1
    assert results[0].protocol == "fm"
    assert results[0].result_type == "voice"
    assert results[0].audio_path is not None
