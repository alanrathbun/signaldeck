from datetime import datetime, timezone
import pytest
from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.registry import DecoderRegistry

class MockDecoder(DecoderPlugin):
    @property
    def name(self) -> str: return "mock"
    @property
    def protocols(self) -> list[str]: return ["mock_proto"]
    @property
    def input_type(self) -> str: return "audio"
    def can_decode(self, signal: SignalInfo) -> float:
        if 88e6 <= signal.frequency_hz <= 108e6: return 0.9
        return 0.0
    async def decode(self, signal, data_source):
        yield DecoderResult(timestamp=datetime.now(timezone.utc), frequency=signal.frequency_hz,
                           protocol="mock_proto", result_type="data", content={"test": True})

class AnotherMockDecoder(DecoderPlugin):
    @property
    def name(self) -> str: return "another"
    @property
    def protocols(self) -> list[str]: return ["another_proto"]
    @property
    def input_type(self) -> str: return "iq"
    def can_decode(self, signal: SignalInfo) -> float:
        if 88e6 <= signal.frequency_hz <= 108e6: return 0.5
        return 0.0
    async def decode(self, signal, data_source):
        yield DecoderResult(timestamp=datetime.now(timezone.utc), frequency=signal.frequency_hz,
                           protocol="another_proto", result_type="data", content={})

def test_register_and_list_decoders():
    registry = DecoderRegistry()
    registry.register(MockDecoder())
    registry.register(AnotherMockDecoder())
    assert len(registry.list_decoders()) == 2
    names = [d.name for d in registry.list_decoders()]
    assert "mock" in names and "another" in names

def test_find_decoders_for_signal():
    registry = DecoderRegistry()
    registry.register(MockDecoder())
    registry.register(AnotherMockDecoder())
    signal = SignalInfo(frequency_hz=100e6, bandwidth_hz=200e3, peak_power=-40.0, modulation="FM")
    matches = registry.find_decoders(signal)
    assert len(matches) == 2
    assert matches[0][0].name == "mock" and matches[0][1] == 0.9
    assert matches[1][0].name == "another" and matches[1][1] == 0.5

def test_find_decoders_no_match():
    registry = DecoderRegistry()
    registry.register(MockDecoder())
    signal = SignalInfo(frequency_hz=400e6, bandwidth_hz=12500.0, peak_power=-60.0, modulation="FM")
    assert len(registry.find_decoders(signal)) == 0

def test_get_decoder_by_name():
    registry = DecoderRegistry()
    decoder = MockDecoder()
    registry.register(decoder)
    assert registry.get("mock") is decoder
    assert registry.get("nonexistent") is None
