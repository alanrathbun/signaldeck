import pytest
from unittest.mock import AsyncMock, MagicMock
from signaldeck.engine.gqrx_device import GqrxDevice
from signaldeck.engine.device_manager import DeviceInfo


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.is_connected = True
    return client


@pytest.fixture
def device(mock_client):
    info = DeviceInfo(label="gqrx @ localhost:7356", driver="gqrx", serial="localhost:7356")
    return GqrxDevice(mock_client, info)


def test_is_gqrx(device):
    assert device.is_gqrx is True


def test_tune_calls_set_frequency(device, mock_client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(device.tune(162_400_000))
    mock_client.set_frequency.assert_called_once_with(162400000)


def test_noop_methods_do_not_raise(device):
    device.set_gain(40)
    device.set_sample_rate(2_000_000)
    device.start_stream()
    device.stop_stream()


def test_read_samples_returns_none(device):
    assert device.read_samples(1024) is None


def test_get_signal_strength(device, mock_client):
    import asyncio
    mock_client.get_signal_strength.return_value = -42.5
    strength = asyncio.get_event_loop().run_until_complete(device.get_signal_strength())
    assert strength == -42.5


def test_close_disconnects(device, mock_client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(device.close())
    mock_client.disconnect.assert_called_once()
