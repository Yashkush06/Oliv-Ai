import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "model_config": {
        "provider": "ollama",
        "model": "llama3",
        "base_url": "http://localhost:11434",
        "gemini_api_key": None,
        "gemini_model": "gemini-2.0-flash",
        "fallback_model": None,
        "timeout_seconds": 60,
        "max_retries": 3,
        "vision_model": None,  # e.g. "ollama:llava" or "api:gpt-4o"
    },
    "user_preferences": {
        "browser": None,
        "editor": None,
        "terminal": None,
        "approval_mode": "smart",  # "safe" | "smart" | "autonomous"
    },
    "behavior": {
        "reuse_browser_tabs": None,
        "confirm_before_open": None,
    },
    "asked_flags": {},
    "setup_complete": False,
}


def _get_config_dir() -> Path:
    override = os.environ.get("OLIV_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".oliv-ai"


def _get_config_path() -> Path:
    return _get_config_dir() / "config.json"


def load_config() -> dict:
    """Load config from disk. Returns defaults if file doesn't exist."""
    path = _get_config_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults to fill in any new keys
        merged = _deep_merge(DEFAULT_CONFIG, data)
        # Sanitize: if provider is ollama but base_url is a cloud/Gemini URL, reset it
        mc = merged.get("model_config", {})
        if mc.get("provider") == "ollama":
            url = mc.get("base_url") or ""
            if url and "localhost" not in url and "127.0.0.1" not in url and "ollama" not in url:
                logger.warning(f"Config has provider=ollama but non-Ollama base_url={url!r} — resetting to localhost.")
                mc["base_url"] = "http://localhost:11434"
        return merged
    except Exception as e:
        logger.warning(f"Failed to load config, using defaults: {e}")
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: dict) -> None:
    """Save config to disk."""
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config saved to {path}")


def update_config(updates: dict) -> dict:
    """Deep-merge updates into the current config and save."""
    current = load_config()
    merged = _deep_merge(current, updates)
    save_config(merged)
    return merged


def get_value(key_path: str, default: Any = None) -> Any:
    """Get a nested config value using dot notation. e.g. 'model_config.provider'"""
    config = load_config()
    keys = key_path.split(".")
    val = config
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


def set_value(key_path: str, value: Any) -> dict:
    """Set a nested config value using dot notation and save."""
    config = load_config()
    keys = key_path.split(".")
    obj = config
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value
    save_config(config)
    return config


def mark_asked(flag: str) -> None:
    """Mark a contextual preference question as already asked."""
    set_value(f"asked_flags.{flag}", True)


def was_asked(flag: str) -> bool:
    """Check whether a contextual preference was already asked."""
    return bool(get_value(f"asked_flags.{flag}", False))


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
