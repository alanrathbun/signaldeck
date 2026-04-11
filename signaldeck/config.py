import copy
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.yaml"
_USER_CONFIG_PATH = Path(__file__).parent.parent / "config" / "user_settings.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(config_path: str | None, load_user_settings: bool = True) -> dict:
    """Load configuration from default YAML, optionally merged with a custom file.

    Args:
        config_path: Path to custom YAML config, or None for defaults only.
        load_user_settings: Whether to auto-load user_settings.yaml. Set False in tests.

    Returns:
        Merged configuration dict.

    Raises:
        FileNotFoundError: If config_path is provided but does not exist.
    """
    with open(_DEFAULT_CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Auto-load persisted user settings if they exist
    if load_user_settings and _USER_CONFIG_PATH.exists():
        with open(_USER_CONFIG_PATH) as f:
            user = yaml.safe_load(f)
        if user:
            config = _deep_merge(config, user)

    # Explicit --config overrides everything
    if config_path is not None:
        custom_path = Path(config_path)
        if not custom_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(custom_path) as f:
            custom = yaml.safe_load(f)
        if custom:
            config = _deep_merge(config, custom)

    return config
