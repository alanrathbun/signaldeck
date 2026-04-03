import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.aprs import AprsDecoder, parse_aprs_packet

def test_aprs_decoder_properties():
    decoder = AprsDecoder()
    assert decoder.name == "aprs"
    assert "aprs" in decoder.protocols
    assert decoder.input_type == "audio"

def test_can_decode_144_39():
    decoder = AprsDecoder()
    signal = SignalInfo(frequency_hz=144.39e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) > 0.8

def test_can_decode_vhf_narrowband():
    decoder = AprsDecoder()
    signal = SignalInfo(frequency_hz=144.8e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) > 0.2

def test_cannot_decode_uhf():
    decoder = AprsDecoder()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) == 0.0

def test_parse_position_packet():
    raw = "W3ADO-1>APRS,RELAY:=4903.50N/07201.75W-PHG2360/RELAY"
    result = parse_aprs_packet(raw)
    assert result is not None
    assert result["source"] == "W3ADO-1"
    assert result["destination"] == "APRS"
    assert result["type"] == "position"
    assert "latitude" in result and "longitude" in result

def test_parse_weather_packet():
    raw = "DW1234>APRS:@092345z4903.50N/07201.75W_090/000g005t077r000p000P000h50b10243"
    result = parse_aprs_packet(raw)
    assert result is not None
    assert result["type"] == "weather"

def test_parse_message_packet():
    raw = "W3ADO>APRS::BLN1     :Test bulletin"
    result = parse_aprs_packet(raw)
    assert result is not None
    assert result["type"] == "message"

def test_parse_invalid_packet():
    assert parse_aprs_packet("") is None
    assert parse_aprs_packet("just random text") is None
