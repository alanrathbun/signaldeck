import pytest
from signaldeck.engine.classifier import SignalClassifier
from signaldeck.decoders.base import SignalInfo

def test_classify_broadcast_fm():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.modulation == "FM"
    assert result.protocol_hint == "broadcast_fm"

def test_classify_narrowband_fm():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=155e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.modulation == "FM"
    assert result.protocol_hint in ("analog_voice", "narrowband_fm")

def test_classify_adsb():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=1090e6, bandwidth_hz=1e6, peak_power=-40.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.protocol_hint == "adsb"

def test_classify_ism_433():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=433.92e6, bandwidth_hz=50e3, peak_power=-55.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.protocol_hint == "ism"

def test_classify_aviation_am():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=121.5e6, bandwidth_hz=8e3, peak_power=-45.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.modulation == "AM"
    assert result.protocol_hint == "aviation"

def test_classify_weather_radio():
    classifier = SignalClassifier()
    for freq in [162.400e6, 162.425e6, 162.450e6, 162.475e6, 162.500e6, 162.525e6, 162.550e6]:
        signal = SignalInfo(frequency_hz=freq, bandwidth_hz=12500.0, peak_power=-40.0, modulation="unknown")
        result = classifier.classify(signal)
        assert result.protocol_hint == "weather_radio", f"Failed for {freq/1e6} MHz"

def test_classify_noaa_apt():
    classifier = SignalClassifier()
    for freq in [137.1e6, 137.9125e6]:
        signal = SignalInfo(frequency_hz=freq, bandwidth_hz=40e3, peak_power=-60.0, modulation="unknown")
        result = classifier.classify(signal)
        assert result.protocol_hint == "noaa_apt", f"Failed for {freq/1e6} MHz"

def test_classify_unknown():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=300e6, bandwidth_hz=25e3, peak_power=-70.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.modulation in ("FM", "AM", "unknown")


def test_classify_marine_band():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=156.8e6, bandwidth_hz=12_500.0, peak_power=-45.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.protocol_hint == "marine"
    assert result.modulation == "FM"


def test_classify_key_fob_band():
    classifier = SignalClassifier()
    signal = SignalInfo(frequency_hz=433.92e6, bandwidth_hz=20_000.0, peak_power=-55.0, modulation="unknown")
    result = classifier.classify(signal)
    assert result.protocol_hint == "ism"
    assert result.modulation in ("OOK", "unknown")
