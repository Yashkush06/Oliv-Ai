"""
Preference resolver: translates user preferences into concrete app names
and action permissions based on the current approval_mode.
"""
import logging
from typing import Optional

from .manager import load_config

logger = logging.getLogger(__name__)

# Approval mode: which risk levels require confirmation
APPROVAL_RULES = {
    "safe": {"safe", "moderate", "dangerous"},        # confirm everything
    "smart": {"moderate", "dangerous"},                # confirm risky + dangerous
    "autonomous": set(),                               # confirm nothing
}

# Fallback app defaults when user has no preference set
APP_DEFAULTS = {
    "browser": "msedge",
    "editor": "notepad",
    "terminal": "cmd",
}


def resolve_app(category: str) -> str:
    """
    Return the preferred app for a category (browser, editor, terminal).
    Falls back to system defaults if not set.
    """
    config = load_config()
    prefs = config.get("user_preferences", {})
    app = prefs.get(category)
    if app:
        return app
    default = APP_DEFAULTS.get(category, category)
    logger.info(f"No preference for '{category}', using default: {default}")
    return default


def resolve_permission(tool_name: str, risk_level: str) -> str:
    """
    Determine whether to auto-execute or ask the user for confirmation.
    Returns: "auto" | "confirm"
    """
    config = load_config()
    prefs = config.get("user_preferences", {})
    mode = prefs.get("approval_mode", "smart")

    needs_confirm = risk_level in APPROVAL_RULES.get(mode, set())
    result = "confirm" if needs_confirm else "auto"
    logger.debug(f"Permission for {tool_name} (risk={risk_level}, mode={mode}): {result}")
    return result
