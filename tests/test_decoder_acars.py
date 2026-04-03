import json
import shutil

import pytest

from signaldeck.decoders.base import SignalInfo
from signaldeck.decoders.acars import AcarsDecoder, parse_acars_json


def test_acars_decoder_properties():
    decoder = AcarsDecoder()
    assert decoder.name == "acars"
    assert "acars" in decoder.protocols
    assert decoder.input_type == "iq"


def test_can_decode_acars_freq():
    decoder = AcarsDecoder()
    signal = SignalInfo(frequency_hz=131.55e6, bandwidth_hz=12500.0, peak_power=-45.0,
                        modulation="AM", protocol_hint="acars")
    assert decoder.can_decode(signal) > 0.8


def test_can_decode_other_acars_freqs():
    decoder = AcarsDecoder()
    for freq_mhz in [131.525, 131.550, 131.725, 131.825, 130.025, 136.900]:
        signal = SignalInfo(frequency_hz=freq_mhz * 1e6, bandwidth_hz=12500.0,
                            peak_power=-45.0, modulation="AM")
        assert decoder.can_decode(signal) > 0.3, f"Failed for {freq_mhz} MHz"


def test_cannot_decode_non_acars():
    decoder = AcarsDecoder()
    signal = SignalInfo(frequency_hz=433e6, bandwidth_hz=50e3, peak_power=-55.0,
                        modulation="unknown", protocol_hint="ism")
    assert decoder.can_decode(signal) == 0.0


def test_parse_acars_json_valid():
    data = {"timestamp": 1752154097.84, "freq": 131.825, "tail": "N827NW",
            "flight": "NW0183", "text": "POSITION REPORT", "label": "H1"}
    result = parse_acars_json(json.dumps(data))
    assert result is not None and result["tail"] == "N827NW"


def test_parse_acars_json_invalid():
    assert parse_acars_json("not json") is None
    assert parse_acars_json("") is None


@pytest.mark.skipif(not shutil.which("acarsdec"), reason="acarsdec not installed")
def test_acars_tool_available():
    assert AcarsDecoder().tool_available()
