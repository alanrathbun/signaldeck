import shutil, pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.p25 import P25Decoder, parse_op25_stderr_line

def test_p25_decoder_properties():
    decoder = P25Decoder()
    assert decoder.name == "p25"
    assert "p25" in decoder.protocols
    assert decoder.input_type == "iq"

def test_can_decode_p25_hint():
    decoder = P25Decoder()
    signal = SignalInfo(frequency_hz=851e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="p25")
    assert decoder.can_decode(signal) > 0.8

def test_can_decode_narrowband_uhf():
    decoder = P25Decoder()
    signal = SignalInfo(frequency_hz=851e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="narrowband_fm")
    assert decoder.can_decode(signal) > 0.2

def test_cannot_decode_broadcast():
    decoder = P25Decoder()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) == 0.0

def test_parse_talkgroup_line():
    result = parse_op25_stderr_line("tgid=12345 freq=851012500")
    assert result is not None and result["talkgroup"] == "12345" and result["frequency"] == "851012500"

def test_parse_nac_line():
    result = parse_op25_stderr_line("NAC 0x293 WACN 0xBEE00 SYSID 0x123 RFID 0x01 STID 0x01")
    assert result is not None and result["type"] == "system_info" and result["nac"] == "0x293"

def test_parse_voice_grant():
    result = parse_op25_stderr_line("voice grant  tgid 12345  freq 851.0125")
    assert result is not None and result["type"] == "voice_grant"

def test_parse_irrelevant():
    assert parse_op25_stderr_line("") is None
    assert parse_op25_stderr_line("random text") is None
