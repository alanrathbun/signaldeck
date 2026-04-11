"""Tests for is_lan_client — IP classification for the LAN auth bypass."""
import pytest

from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client


@pytest.mark.parametrize("ip", [
    "127.0.0.1",
    "127.1.2.3",
    "127.255.255.255",
    "::1",
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.1.100",
    "192.168.255.255",
    "100.64.0.0",       # Tailscale CGNAT lower bound
    "100.94.221.106",   # Operator's actual NucBox Tailscale IP
    "100.127.255.255",  # Tailscale CGNAT upper bound
    "fd00::1",          # IPv6 ULA
    "fdff:ffff:ffff::1",
])
def test_is_lan_client_accepts_local_ranges(ip):
    assert is_lan_client(ip, DEFAULT_LAN_ALLOWLIST) is True


@pytest.mark.parametrize("ip", [
    "8.8.8.8",
    "1.1.1.1",
    "100.63.255.255",    # Just below Tailscale CGNAT
    "100.128.0.0",       # Just above Tailscale CGNAT
    "2001:4860:4860::8888",
    "2606:4700:4700::1111",
])
def test_is_lan_client_rejects_public(ip):
    assert is_lan_client(ip, DEFAULT_LAN_ALLOWLIST) is False


@pytest.mark.parametrize("bad", ["", "not-an-ip", "999.999.999.999", "::gg::"])
def test_is_lan_client_rejects_malformed(bad):
    assert is_lan_client(bad, DEFAULT_LAN_ALLOWLIST) is False


def test_is_lan_client_rejects_none():
    assert is_lan_client(None, DEFAULT_LAN_ALLOWLIST) is False


def test_is_lan_client_custom_allowlist_accepts_only_listed_range():
    allowlist = ["10.5.0.0/16"]
    assert is_lan_client("10.5.0.1", allowlist) is True
    assert is_lan_client("10.5.255.254", allowlist) is True
    assert is_lan_client("10.6.0.0", allowlist) is False
    assert is_lan_client("192.168.1.1", allowlist) is False


def test_is_lan_client_empty_allowlist_rejects_everything():
    assert is_lan_client("127.0.0.1", []) is False
    assert is_lan_client("192.168.1.1", []) is False


def test_default_allowlist_contents():
    """Guard against accidental deletion of critical ranges."""
    assert "127.0.0.0/8" in DEFAULT_LAN_ALLOWLIST
    assert "::1/128" in DEFAULT_LAN_ALLOWLIST
    assert "10.0.0.0/8" in DEFAULT_LAN_ALLOWLIST
    assert "172.16.0.0/12" in DEFAULT_LAN_ALLOWLIST
    assert "192.168.0.0/16" in DEFAULT_LAN_ALLOWLIST
    assert "fc00::/7" in DEFAULT_LAN_ALLOWLIST
    assert "100.64.0.0/10" in DEFAULT_LAN_ALLOWLIST  # Tailscale


def test_is_lan_client_skips_malformed_allowlist_entries():
    """A bad CIDR entry must not prevent matching on valid entries that follow."""
    allowlist = ["not-a-cidr", "10.0.0.0/8"]
    assert is_lan_client("10.1.2.3", allowlist) is True

    allowlist_all_bad = ["not-a-cidr", "also-bad", "9999::/200"]
    assert is_lan_client("10.1.2.3", allowlist_all_bad) is False
