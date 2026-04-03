import pytest
from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.rds import RdsDecoder, decode_rds_group, RDS_PTY_CODES


def test_rds_decoder_properties():
    decoder = RdsDecoder()
    assert decoder.name == "rds"
    assert "rds" in decoder.protocols
    assert decoder.input_type == "audio"


def test_can_decode_broadcast_fm():
    decoder = RdsDecoder()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    assert decoder.can_decode(signal) > 0.5


def test_cannot_decode_narrowband():
    decoder = RdsDecoder()
    signal = SignalInfo(frequency_hz=155e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    assert decoder.can_decode(signal) == 0.0


def test_rds_pty_codes_populated():
    assert len(RDS_PTY_CODES) == 32
    assert RDS_PTY_CODES[0] == "No programme type"
    assert RDS_PTY_CODES[1] == "News"
    assert RDS_PTY_CODES[3] == "Information"


def test_decode_rds_group_0a():
    block_a = 0x1234
    block_b = 0x0020  # group 0A, PTY=1 (News), segment=0
    block_c = 0x0000
    block_d = (ord('W') << 8) | ord('X')
    result = decode_rds_group(block_a, block_b, block_c, block_d)
    assert result is not None
    assert result["pi_code"] == 0x1234
    assert result["group_type"] == "0A"
    assert result["pty"] == 1
    assert result["pty_name"] == "News"
    assert result["ps_segment"] == 0
    assert result["ps_chars"] == "WX"


def test_decode_rds_group_2a():
    block_a = 0x1234
    block_b = 0x20A1  # group 2A, PTY=5 (Rock), segment=1
    block_c = (ord('e') << 8) | ord('s')
    block_d = (ord('t') << 8) | ord('!')
    result = decode_rds_group(block_a, block_b, block_c, block_d)
    assert result is not None
    assert result["group_type"] == "2A"
    assert result["pty_name"] == "Rock"
    assert "rt_chars" in result
