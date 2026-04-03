"""Tests for GqrxClient — rigctl TCP protocol client."""
import asyncio

import pytest

from signaldeck.engine.gqrx_client import GqrxClient, GqrxConnectionError

# ---------------------------------------------------------------------------
# Mock gqrx server helpers
# ---------------------------------------------------------------------------

RESPONSES = {
    b"f\n": b"162400000\n",
    b"F 162400000\n": b"RPRT 0\n",
    b"l STRENGTH\n": b"-42.5\n",
    b"M FM 0\n": b"RPRT 0\n",
    b"L SQL -40.0\n": b"RPRT 0\n",
    b"l SQL\n": b"-40.0\n",
    b"U RECORD 1\n": b"RPRT 0\n",
    b"U RECORD 0\n": b"RPRT 0\n",
    b"q\n": b"RPRT 0\n",
}


async def _run_mock_server(port: int, handler) -> asyncio.AbstractServer:
    """Start a mock TCP server on the given port."""
    server = await asyncio.start_server(handler, "127.0.0.1", port)
    return server


def _simple_handler(responses: dict):
    """Return a connection handler that responds from the given dict."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                response = responses.get(line, b"RPRT -1\n")
                writer.write(response)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    return handler


def _mode_handler():
    """Connection handler that handles the two-line 'm' response specially."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if line == b"m\n":
                    writer.write(b"FM\n12500\n")
                else:
                    response = RESPONSES.get(line, b"RPRT -1\n")
                    writer.write(response)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_and_get_frequency():
    """Connect to mock server, get frequency, verify value, disconnect."""
    port = 17356
    server = await _run_mock_server(port, _simple_handler(RESPONSES))
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        assert client.is_connected
        freq = await client.get_frequency()
        assert freq == 162400000
        await client.disconnect()
        assert not client.is_connected


@pytest.mark.asyncio
async def test_set_frequency():
    """set_frequency sends 'F <hz>' and succeeds on 'RPRT 0'."""
    port = 17357
    server = await _run_mock_server(port, _simple_handler(RESPONSES))
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        # Should not raise
        await client.set_frequency(162400000)
        await client.disconnect()


@pytest.mark.asyncio
async def test_get_signal_strength():
    """get_signal_strength returns a float parsed from 'l STRENGTH' response."""
    port = 17358
    server = await _run_mock_server(port, _simple_handler(RESPONSES))
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        strength = await client.get_signal_strength()
        assert strength == pytest.approx(-42.5)
        await client.disconnect()


@pytest.mark.asyncio
async def test_set_and_get_mode():
    """set_mode succeeds and get_mode returns (mode_str, passband_int)."""
    port = 17359
    server = await _run_mock_server(port, _mode_handler())
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        await client.set_mode("FM")
        mode, passband = await client.get_mode()
        assert mode == "FM"
        assert passband == 12500
        await client.disconnect()


@pytest.mark.asyncio
async def test_squelch():
    """set_squelch and get_squelch work correctly."""
    port = 17360
    server = await _run_mock_server(port, _simple_handler(RESPONSES))
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        await client.set_squelch(-40.0)
        level = await client.get_squelch()
        assert level == pytest.approx(-40.0)
        await client.disconnect()


@pytest.mark.asyncio
async def test_recording():
    """start_recording and stop_recording complete without errors."""
    port = 17361
    server = await _run_mock_server(port, _simple_handler(RESPONSES))
    async with server:
        client = GqrxClient(host="127.0.0.1", port=port, timeout=2.0)
        await client.connect()
        await client.start_recording()
        await client.stop_recording()
        await client.disconnect()


@pytest.mark.asyncio
async def test_connection_error():
    """Connecting to a non-existent port raises GqrxConnectionError."""
    client = GqrxClient(host="127.0.0.1", port=19999, timeout=1.0)
    with pytest.raises(GqrxConnectionError):
        await client.connect()


@pytest.mark.asyncio
async def test_command_when_disconnected():
    """Calling get_frequency without connecting raises GqrxConnectionError."""
    client = GqrxClient(host="127.0.0.1", port=17356, timeout=1.0)
    with pytest.raises(GqrxConnectionError):
        await client.get_frequency()
