"""Tests for resolve_effective_audio_mode — the audio-mode decision rule."""
import pytest

from signaldeck.api.websocket import audio_stream


@pytest.fixture(autouse=True)
def clear_clients():
    """Reset the module-level subscriber dict between tests."""
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


def _client(freq, is_lan, addr="1.1.1.1"):
    """Build a fake subscriber entry."""
    return {"freq": freq, "is_lan": is_lan, "remote_addr": addr}


def test_manual_gqrx_always_wins_regardless_of_subscribers():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("gqrx") == "gqrx"


def test_manual_pcm_stream_always_wins():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="127.0.0.1")
    assert audio_stream.resolve_effective_audio_mode("pcm_stream") == "pcm_stream"


def test_auto_no_subscribers_picks_gqrx():
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_lan_only_subscriber_picks_gqrx():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="192.168.1.5")
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_remote_subscriber_picks_pcm_stream():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"


def test_auto_mixed_lan_and_remote_picks_pcm_stream():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="192.168.1.5")
    audio_stream._audio_clients["ws2"] = _client(100e6, is_lan=False, addr="203.0.113.9")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"


def test_auto_subscriber_with_freq_none_is_ignored():
    """A client that has connected to /ws/audio but hasn't subscribed to a
    frequency yet (freq=None) should not count as 'listening.'"""
    audio_stream._audio_clients["ws1"] = _client(None, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_subscriber_disconnect_returns_to_gqrx():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"
    # Simulate disconnect
    del audio_stream._audio_clients["ws1"]
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_returns_valid_literal_only():
    """Result must always be one of the three valid literal strings."""
    for clients in [{}, {"x": _client(100e6, True)}, {"x": _client(100e6, False)}]:
        audio_stream._audio_clients.clear()
        audio_stream._audio_clients.update(clients)
        result = audio_stream.resolve_effective_audio_mode("auto")
        assert result in ("gqrx", "pcm_stream")
