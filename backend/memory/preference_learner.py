"""
Preference learner — detects user corrections in chat and updates config instantly.
e.g. "don't use Edge, use Chrome" → sets browser preference to chrome
"""
import logging
import re

from config.manager import update_config

logger = logging.getLogger(__name__)

CORRECTION_PATTERNS = [
    # "don't use X, use Y" / "stop using X" / "switch to Y"
    (r"don[''t]*\s+use\s+(\w+)", r"use\s+(\w+)", "negative_positive"),
    (r"stop\s+using\s+(\w+)", r"", "negative"),
    (r"switch\s+to\s+(\w+)", r"", "switch_to"),
    (r"(?:open|use)\s+(\w+)\s+instead", r"", "instead"),
    (r"always\s+(?:use|open)\s+(\w+)", r"", "always"),
]

APP_CATEGORY_MAP = {
    "chrome": "browser", "chromium": "browser", "firefox": "browser",
    "edge": "browser", "msedge": "browser", "brave": "browser", "opera": "browser",
    "notepad": "editor", "vscode": "editor", "code": "editor",
    "vim": "editor", "sublime": "editor", "atom": "editor",
    "cmd": "terminal", "powershell": "terminal", "wt": "terminal",
    "terminal": "terminal",
}


def learn_from_message(user_message: str) -> list[dict]:
    """
    Scan a user message for preference corrections.
    Returns list of applied changes.
    """
    msg = user_message.lower()
    changes = []

    # Detect "don't use X, use Y" pattern
    dont_match = re.search(r"don[''t]*\s+use\s+(\w+)", msg)
    use_match = re.search(r"\buse\s+(\w+)(?:\s+instead)?", msg)

    if dont_match and use_match:
        bad_app = dont_match.group(1)
        good_app = use_match.group(1)
        if good_app != bad_app:
            category = APP_CATEGORY_MAP.get(good_app)
            if category:
                update_config({"user_preferences": {category: good_app}})
                logger.info(f"Preference learned: {category} = {good_app} (was {bad_app})")
                changes.append({"category": category, "value": good_app, "reason": f"Replaced '{bad_app}'"})
        return changes

    # Detect "switch to X" / "always use X" / "use X instead"
    for pattern, _, ptype in CORRECTION_PATTERNS[2:]:
        m = re.search(pattern, msg)
        if m:
            app = m.group(1)
            category = APP_CATEGORY_MAP.get(app)
            if category:
                update_config({"user_preferences": {category: app}})
                logger.info(f"Preference learned: {category} = {app}")
                changes.append({"category": category, "value": app})
                break

    return changes
