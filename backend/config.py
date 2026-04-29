"""Configuration — reads from ~/.config/dianoia/config.toml with env var fallbacks."""
import os
import tomllib
from pathlib import Path

_config_path = Path.home() / ".config" / "dianoia" / "config.toml"
_toml: dict = {}
if _config_path.exists():
    with open(_config_path, "rb") as _f:
        _toml = tomllib.load(_f)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or _toml.get("anthropic_api_key")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or _toml.get("model", "claude-sonnet-4-6")
