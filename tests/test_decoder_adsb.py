import json
import shutil
import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.adsb import AdsbDecoder, parse_sbs_message

def test_adsb_decoder_properties():
    decoder = AdsbDecoder()
    assert decoder.name == "adsb"
    assert "adsb" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_1090mhz():
    decoder = AdsbDecoder()
    signal = SignalInfo(frequency_hz=1090e6, bandwidth_hz=1e6, peak_power=-40.0,
                        modulation="PULSE", protocol_hint="adsb")
    assert decoder.can_decode(signal) > 0.8

def test_cannot_decode_non_adsb():
    decoder = AdsbDecoder()
    signal = SignalInfo(frequency_hz=433e6, bandwidth_hz=50e3, peak_power=-55.0,
                        modulation="unknown", protocol_hint="ism")
    assert decoder.can_decode(signal) == 0.0

def test_parse_sbs_message_position():
    line = "MSG,3,1,1,A12345,1,2026/04/02,15:30:00.000,2026/04/02,15:30:00.000,,35000,,,40.7128,-74.0060,,,0,,0,0"
    result = parse_sbs_message(line)
    assert result is not None
    assert result["hex_ident"] == "A12345"
    assert result["altitude"] == 35000
    assert result["latitude"] == 40.7128
    assert result["longitude"] == -74.0060

def test_parse_sbs_message_identification():
    line = "MSG,1,1,1,A12345,1,2026/04/02,15:30:00.000,2026/04/02,15:30:00.000,UAL447,,,,,,,,,,"
    result = parse_sbs_message(line)
    assert result is not None
    assert result["callsign"] == "UAL447"

def test_parse_sbs_message_velocity():
    line = "MSG,4,1,1,A12345,1,2026/04/02,15:30:00.000,2026/04/02,15:30:00.000,,,450,180,,,1024,,,,,0"
    result = parse_sbs_message(line)
    assert result is not None
    assert result["ground_speed"] == 450
    assert result["track"] == 180

def test_parse_sbs_invalid():
    assert parse_sbs_message("") is None
    assert parse_sbs_message("not,enough,fields") is None
