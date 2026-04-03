import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.weather_radio import WeatherRadioDecoder, parse_same_header, SAME_EVENTS

def test_weather_decoder_properties():
    decoder = WeatherRadioDecoder()
    assert decoder.name == "weather_radio"
    assert "weather_radio" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_noaa_freq():
    decoder = WeatherRadioDecoder()
    signal = SignalInfo(frequency_hz=162.4e6, bandwidth_hz=12500.0, peak_power=-40.0,
                        modulation="FM", protocol_hint="weather_radio")
    assert decoder.can_decode(signal) > 0.8

def test_cannot_decode_non_weather():
    decoder = WeatherRadioDecoder()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) == 0.0

def test_parse_same_header_tornado_warning():
    header = "ZCZC-WXR-TOR-029510-029090-029150+0030-0920815-KLWX/NWS-"
    result = parse_same_header(header)
    assert result is not None
    assert result["originator"] == "WXR"
    assert result["event"] == "TOR"
    assert "029510" in result["locations"]
    assert result["duration_minutes"] == 30
    assert result["station"] == "KLWX/NWS"

def test_parse_same_header_severe_thunderstorm():
    header = "ZCZC-WXR-SVR-020103+0045-0911510-KBMX/NWS-"
    result = parse_same_header(header)
    assert result is not None
    assert result["event"] == "SVR"
    assert result["duration_minutes"] == 45

def test_parse_same_header_winter_storm():
    header = "ZCZC-WXR-WSW-020009-020015-020117+0600-1011200-KBMX/NWS-"
    result = parse_same_header(header)
    assert result is not None
    assert result["event"] == "WSW"
    assert len(result["locations"]) == 3
    assert result["duration_minutes"] == 360

def test_parse_same_invalid():
    assert parse_same_header("") is None
    assert parse_same_header("random text") is None
    assert parse_same_header("ZCZC") is None

def test_same_event_description():
    assert SAME_EVENTS["TOR"] == "Tornado Warning"
    assert SAME_EVENTS["SVR"] == "Severe Thunderstorm Warning"
    assert "EAN" in SAME_EVENTS
