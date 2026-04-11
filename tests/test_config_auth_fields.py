"""Verifies the new auth.* config fields load with sensible defaults."""
from signaldeck.config import load_config


def test_default_config_has_lan_allowlist():
    cfg = load_config(None, load_user_settings=False)
    allowlist = cfg.get("auth", {}).get("lan_allowlist")
    assert isinstance(allowlist, list)
    assert "127.0.0.0/8" in allowlist
    assert "100.64.0.0/10" in allowlist  # Tailscale CGNAT
    assert "192.168.0.0/16" in allowlist


def test_default_config_has_trust_x_forwarded_for_false():
    cfg = load_config(None, load_user_settings=False)
    assert cfg.get("auth", {}).get("trust_x_forwarded_for") is False


def test_default_config_has_remember_token_days_null():
    cfg = load_config(None, load_user_settings=False)
    assert cfg.get("auth", {}).get("remember_token_days") is None
