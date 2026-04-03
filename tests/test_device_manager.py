from unittest.mock import MagicMock, patch

import pytest

from signaldeck.engine.device_manager import DeviceManager, SDRDevice, DeviceInfo


def _make_mock_soapy_device():
    """Create a mock SoapySDR device."""
    dev = MagicMock()
    dev.getHardwareKey.return_value = "HackRF"
    dev.getHardwareInfo.return_value = {"serial": "abc123"}
    dev.getSampleRateRange.return_value = [MagicMock(minimum=lambda: 1e6, maximum=lambda: 20e6)]
    dev.getFrequencyRange.return_value = [MagicMock(minimum=lambda: 1e6, maximum=lambda: 6e9)]
    dev.listGains.return_value = ["LNA", "VGA"]
    dev.setSampleRate = MagicMock()
    dev.setFrequency = MagicMock()
    dev.setGain = MagicMock()
    dev.setupStream = MagicMock(return_value="stream_handle")
    dev.activateStream = MagicMock()
    dev.deactivateStream = MagicMock()
    dev.closeStream = MagicMock()
    dev.readStream = MagicMock(return_value=(0, None))
    return dev


def test_device_info():
    """DeviceInfo stores device metadata."""
    info = DeviceInfo(
        label="HackRF One",
        driver="hackrf",
        serial="abc123",
        hardware_key="HackRF",
    )
    assert info.label == "HackRF One"
    assert info.driver == "hackrf"


@patch("signaldeck.engine.device_manager.SoapySDR")
def test_enumerate_devices(mock_soapy):
    """DeviceManager discovers connected SDR devices."""
    mock_soapy.Device.enumerate.return_value = [
        {"driver": "hackrf", "label": "HackRF One", "serial": "abc123"},
    ]
    mgr = DeviceManager()
    devices = mgr.enumerate()
    assert len(devices) == 1
    assert devices[0].driver == "hackrf"


@patch("signaldeck.engine.device_manager.SoapySDR")
def test_open_and_close_device(mock_soapy):
    """Can open a device and close it."""
    mock_soapy.Device.enumerate.return_value = [
        {"driver": "hackrf", "serial": "abc123"},
    ]
    mock_dev = _make_mock_soapy_device()
    mock_soapy.Device.return_value = mock_dev

    mgr = DeviceManager()
    sdr = mgr.open(driver="hackrf")
    assert sdr is not None
    assert sdr.info.driver == "hackrf"

    sdr.close()
    sdr2 = mgr.open(driver="hackrf")
    assert sdr2 is not None
    sdr2.close()


@patch("signaldeck.engine.device_manager.SoapySDR")
def test_tune_device(mock_soapy):
    """Can tune an opened device to a frequency."""
    mock_soapy.Device.enumerate.return_value = [
        {"driver": "hackrf", "serial": "abc123"},
    ]
    mock_dev = _make_mock_soapy_device()
    mock_soapy.Device.return_value = mock_dev
    mock_soapy.SOAPY_SDR_RX = 0

    mgr = DeviceManager()
    sdr = mgr.open(driver="hackrf")
    sdr.tune(162_400_000)
    mock_dev.setFrequency.assert_called_with(0, 0, 162_400_000)
    sdr.close()


@patch("signaldeck.engine.device_manager.SoapySDR")
def test_set_sample_rate(mock_soapy):
    """Can set sample rate on an opened device."""
    mock_soapy.Device.enumerate.return_value = [
        {"driver": "hackrf", "serial": "abc123"},
    ]
    mock_dev = _make_mock_soapy_device()
    mock_soapy.Device.return_value = mock_dev
    mock_soapy.SOAPY_SDR_RX = 0

    mgr = DeviceManager()
    sdr = mgr.open(driver="hackrf")
    sdr.set_sample_rate(2_000_000)
    mock_dev.setSampleRate.assert_called_with(0, 0, 2_000_000)
    sdr.close()
