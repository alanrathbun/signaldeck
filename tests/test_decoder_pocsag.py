import shutil
import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.pocsag import PocsagDecoder, parse_multimon_pocsag

def test_pocsag_decoder_properties():
    decoder = PocsagDecoder()
    assert decoder.name == "pocsag"
    assert "pocsag" in decoder.protocols
    assert "flex" in decoder.protocols
    assert decoder.input_type == "audio"

def test_can_decode_pager_frequency():
    decoder = PocsagDecoder()
    signal = SignalInfo(frequency_hz=152.48e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="narrowband_fm")
    assert decoder.can_decode(signal) > 0.3

def test_can_decode_with_hint():
    decoder = PocsagDecoder()
    signal = SignalInfo(frequency_hz=152.48e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="pocsag")
    assert decoder.can_decode(signal) > 0.7

def test_cannot_decode_broadcast_fm():
    decoder = PocsagDecoder()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) == 0.0

def test_parse_multimon_pocsag_numeric():
    line = "POCSAG512: Address: 1234567  Function: 0  Numeric:    1234"
    result = parse_multimon_pocsag(line)
    assert result is not None
    assert result["address"] == "1234567"
    assert result["type"] == "numeric"
    assert result["message"] == "1234"

def test_parse_multimon_pocsag_alpha():
    line = "POCSAG1200: Address:  123456  Function: 2  Alpha:   Test message here"
    result = parse_multimon_pocsag(line)
    assert result is not None
    assert result["address"] == "123456"
    assert result["type"] == "alpha"
    assert result["message"] == "Test message here"

def test_parse_multimon_flex():
    line = "FLEX: 1600/4/A 01.234 [1234567] ALN   Test FLEX message"
    result = parse_multimon_pocsag(line)
    assert result is not None
    assert result["protocol"] == "flex"

def test_parse_multimon_non_pocsag():
    assert parse_multimon_pocsag("some random text") is None
    assert parse_multimon_pocsag("") is None
