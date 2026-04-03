from datetime import datetime, timezone

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo


def test_decoder_result_creation():
    result = DecoderResult(
        timestamp=datetime.now(timezone.utc),
        frequency=162_400_000.0,
        protocol="fm",
        result_type="voice",
        content={"description": "NOAA Weather Radio"},
        audio_path="/tmp/test.wav",
        metadata={"strength": -45.0, "duration": 5.0},
    )
    assert result.protocol == "fm"
    assert result.result_type == "voice"
    assert result.audio_path == "/tmp/test.wav"


def test_decoder_result_without_audio():
    result = DecoderResult(
        timestamp=datetime.now(timezone.utc),
        frequency=433_920_000.0,
        protocol="rtl433",
        result_type="data",
        content={"model": "Acurite-Tower", "temperature_C": 22.5},
    )
    assert result.audio_path is None
    assert result.metadata == {}


def test_signal_info_creation():
    info = SignalInfo(
        frequency_hz=162_400_000.0,
        bandwidth_hz=12500.0,
        peak_power=-45.0,
        modulation="FM",
    )
    assert info.frequency_hz == 162_400_000.0
    assert info.modulation == "FM"


def test_decoder_plugin_is_abstract():
    try:
        DecoderPlugin()
        assert False, "Should have raised TypeError"
    except TypeError:
        pass
