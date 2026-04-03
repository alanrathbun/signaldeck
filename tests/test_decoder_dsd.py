import shutil, pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.dsd import DsdDecoder, parse_dsd_stderr_line

def test_dsd_decoder_properties():
    decoder = DsdDecoder()
    assert decoder.name == "dsd"
    assert "dmr" in decoder.protocols and "dstar" in decoder.protocols and "nxdn" in decoder.protocols
    assert decoder.input_type == "audio"

def test_can_decode_dmr_hint():
    decoder = DsdDecoder()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="dmr")
    assert decoder.can_decode(signal) > 0.8

def test_can_decode_narrowband_digital():
    decoder = DsdDecoder()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="narrowband_fm")
    assert decoder.can_decode(signal) > 0.2

def test_cannot_decode_wideband():
    decoder = DsdDecoder()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) == 0.0

def test_parse_dmr_sync_line():
    result = parse_dsd_stderr_line("Sync: +DMR [slot1] slot2 | Color Code=01 | CSBK")
    assert result is not None and result["protocol"] == "dmr" and result["color_code"] == "01"

def test_parse_dmr_talkgroup_line():
    result = parse_dsd_stderr_line(" Talkgroup Voice Channel Grant (TV_GRANT)")
    assert result is not None and result["type"] == "grant"

def test_parse_dmr_target_source_line():
    result = parse_dsd_stderr_line(" LPCN: 0075; TS: 2; Target: 16518173 - Source: 16533625")
    assert result is not None and result["target"] == "16518173" and result["source"] == "16533625"

def test_parse_dstar_header():
    result = parse_dsd_stderr_line("D-STAR Header: MY=W3ADO    YOUR=CQCQCQ  RPT1=W3ADO B RPT2=W3ADO G")
    assert result is not None and result["protocol"] == "dstar" and result["my_callsign"] == "W3ADO"

def test_parse_nxdn_line():
    result = parse_dsd_stderr_line("NXDN48: RAN=01 CC=001 TG=12345")
    assert result is not None and result["protocol"] == "nxdn"

def test_parse_irrelevant_line():
    assert parse_dsd_stderr_line("") is None
    assert parse_dsd_stderr_line("some random output") is None
