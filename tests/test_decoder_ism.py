import json
import shutil
import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.ism import IsmDecoder, parse_rtl433_json, summarize_rtl433_json

def test_ism_decoder_properties():
    decoder = IsmDecoder()
    assert decoder.name == "ism"
    assert "rtl433" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_433mhz():
    decoder = IsmDecoder()
    signal = SignalInfo(frequency_hz=433.92e6, bandwidth_hz=50e3, peak_power=-55.0,
                        modulation="unknown", protocol_hint="ism")
    assert decoder.can_decode(signal) > 0.5

def test_can_decode_915mhz():
    decoder = IsmDecoder()
    signal = SignalInfo(frequency_hz=915e6, bandwidth_hz=100e3, peak_power=-55.0,
                        modulation="unknown", protocol_hint="ism")
    assert decoder.can_decode(signal) > 0.5

def test_cannot_decode_non_ism():
    decoder = IsmDecoder()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) == 0.0

def test_parse_rtl433_json_valid():
    line = json.dumps({"time": "2026-04-02 15:30:00", "model": "Acurite-Tower",
                       "id": 12345, "temperature_C": 22.5, "humidity": 45})
    result = parse_rtl433_json(line)
    assert result is not None
    assert result["model"] == "Acurite-Tower"
    assert result["temperature_C"] == 22.5

def test_parse_rtl433_json_invalid():
    assert parse_rtl433_json("not json") is None
    assert parse_rtl433_json("") is None


def test_summarize_rtl433_json():
    summary = summarize_rtl433_json({
        "model": "Acurite-Tower",
        "id": 12345,
        "temperature_C": 22.5,
        "humidity": 45,
    })
    assert "Acurite-Tower" in summary
    assert "id=12345" in summary
    assert "temperature_C=22.5" in summary

@pytest.mark.skipif(not shutil.which("rtl_433"), reason="rtl_433 not installed")
def test_ism_decoder_tool_available():
    decoder = IsmDecoder()
    assert decoder.tool_available()
