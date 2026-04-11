from pathlib import Path

from signaldeck.config import load_config
from signaldeck.engine.scan_presets import resolve_sweep_ranges


def test_load_default_config():
    """Loading with no path returns defaults."""
    cfg = load_config(None, load_user_settings=False)
    assert cfg["scanner"]["fft_size"] == 1024
    assert cfg["scanner"]["squelch_offset"] == 20
    assert isinstance(cfg["scanner"]["sweep_ranges"], list)
    assert len(resolve_sweep_ranges(cfg["scanner"])) > 0


def test_load_custom_config(tmp_path: Path):
    """Custom YAML merges over defaults."""
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "scanner:\n"
        "  squelch_offset: 25\n"
        "  fft_size: 2048\n"
    )
    cfg = load_config(str(custom), load_user_settings=False)
    assert cfg["scanner"]["squelch_offset"] == 25
    assert cfg["scanner"]["fft_size"] == 2048
    # defaults still present for keys not overridden
    assert cfg["scanner"]["dwell_time_ms"] == 50


def test_load_config_resolves_paths(tmp_path: Path):
    """Relative paths in config are resolved to absolute."""
    cfg = load_config(None)
    db_path = cfg["storage"]["database_path"]
    assert isinstance(db_path, str)
    assert len(db_path) > 0


def test_load_config_missing_file_raises():
    """Non-existent custom config path raises FileNotFoundError."""
    try:
        load_config("/nonexistent/path.yaml")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


def test_default_config_has_gqrx_settings():
    """Default config includes gqrx auto-detect settings."""
    from signaldeck.config import load_config
    cfg = load_config(None, load_user_settings=False)
    assert cfg["devices"]["gqrx_auto_detect"] is True
    assert cfg["devices"]["gqrx_auto_start"] is True
    assert cfg["devices"]["gqrx_instances"] == []


def test_default_config_has_scan_profiles():
    """Default config enables curated scan profiles."""
    cfg = load_config(None, load_user_settings=False)
    assert isinstance(cfg["scanner"]["scan_profiles"], list)
    assert "rtl_priority_search" in cfg["scanner"]["scan_profiles"]
