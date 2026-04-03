import pytest
from signaldeck.decoders.all import create_default_registry
from signaldeck.decoders.base import SignalInfo

def test_default_registry_has_all_decoders():
    registry = create_default_registry()
    names = [d.name for d in registry.list_decoders()]
    assert "fm_am" in names
    assert "rds" in names
    assert "weather_radio" in names
    assert "ism" in names
    assert "pocsag" in names
    assert "aprs" in names
    assert "adsb" in names

def test_broadcast_fm_routes_to_fm_and_rds():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=98.5e6, bandwidth_hz=200e3, peak_power=-30.0,
                        modulation="FM", protocol_hint="broadcast_fm")
    matches = registry.find_decoders(signal)
    names = [m[0].name for m in matches]
    assert "fm_am" in names and "rds" in names

def test_weather_radio_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=162.4e6, bandwidth_hz=12500.0, peak_power=-40.0,
                        modulation="FM", protocol_hint="weather_radio")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "weather_radio"

def test_ism_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=433.92e6, bandwidth_hz=50e3, peak_power=-55.0,
                        modulation="unknown", protocol_hint="ism")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "ism"

def test_adsb_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=1090e6, bandwidth_hz=1e6, peak_power=-40.0,
                        modulation="PULSE", protocol_hint="adsb")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "adsb"

def test_aprs_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=144.39e6, bandwidth_hz=12500.0, peak_power=-50.0, modulation="FM")
    names = [m[0].name for m in registry.find_decoders(signal)]
    assert "aprs" in names

def test_pager_routes_to_pocsag():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=152.48e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="narrowband_fm")
    names = [m[0].name for m in registry.find_decoders(signal)]
    assert "pocsag" in names

def test_default_registry_has_new_decoders():
    registry = create_default_registry()
    names = [d.name for d in registry.list_decoders()]
    assert "acars" in names
    assert "dsd" in names
    assert "p25" in names
    assert "noaa_apt" in names

def test_acars_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=131.55e6, bandwidth_hz=12500.0, peak_power=-45.0,
                        modulation="AM", protocol_hint="acars")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "acars"

def test_p25_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=851e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="p25")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "p25"

def test_dmr_routes_to_dsd():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=460e6, bandwidth_hz=12500.0, peak_power=-50.0,
                        modulation="FM", protocol_hint="dmr")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "dsd"

def test_noaa_apt_routes_correctly():
    registry = create_default_registry()
    signal = SignalInfo(frequency_hz=137.1e6, bandwidth_hz=40e3, peak_power=-60.0,
                        modulation="FM", protocol_hint="noaa_apt")
    matches = registry.find_decoders(signal)
    assert matches[0][0].name == "noaa_apt"

def test_total_decoder_count():
    registry = create_default_registry()
    assert len(registry.list_decoders()) == 11
