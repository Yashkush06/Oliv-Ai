"""
Shared agent constants — single source of truth for skip-sets and limits.

Import from here instead of defining these inline in loop.py / reflector.py
so the two sets never drift apart.
"""

# Tools whose effects are either invisible to a vision LLM or are verified
# at the code level (e.g. pyautogui confirms the click landed). The Critic
# and the Reflector both skip visual verification for these tools.
#
# NOTE: click_text is intentionally NOT in this set — the smarter vision
# prompts can now reliably confirm whether a button/element responded to a
# click (e.g. a dialog opened, tab changed). click() and double_click() remain
# skipped because their effect is often a cursor flash too subtle for vision.
SKIP_VISUAL_VERIFICATION_TOOLS: frozenset[str] = frozenset({
    # Screen-read only — nothing changes
    "read_screen",
    "list_running_apps",
    "is_app_running",
    # App launch: effect is asynchronous; window opens seconds later.
    # The Critic would time-out on a blank desktop. Let wait_for_text handle it.
    "open_app",
    # Low-level click/tap: pyautogui confirms the click landed but the resulting
    # cursor flash or focus ring is too subtle for vision LLM to reliably spot.
    # click_text is NOT skipped — its outcomes (dialogs, new pages) are visible.
    "click",
    "double_click",
    "move_mouse",
    # Keyboard: typing / key combos don't change window chrome.
    "press_key",
    "hotkey",
    # Text input: the text may appear but timing varies; Critic can be flaky.
    "type_text",
})

# How many times the loop may trigger a full re-plan for the ENTIRE task run.
MAX_TASK_REPLANS: int = 3

# How many automatic fix-attempts the fixer may make per failed step.
MAX_FIX_ATTEMPTS: int = 2

# Seconds the executor is allowed before a hard timeout (also in executor.py).
EXECUTOR_TIMEOUT_SECONDS: int = 30

# Seconds to wait for visual confirmation after each step.
CRITIC_TIMEOUT_SECONDS: int = 8

# Vision verification confidence thresholds.
# Scores come from VisionClient.assess_with_confidence().
#   >= PASS  → confirmed success
#   >= UNCERTAIN but < PASS → log warning, treat as pass (don't block task)
#   < UNCERTAIN → vision says no
VISION_CONFIDENCE_PASS: float = 0.70
VISION_CONFIDENCE_UNCERTAIN: float = 0.40

# Max width (pixels) screenshots are resized to before sending to vision APIs.
# Stays high enough for UI element legibility but cuts token cost by ~75%.
VISION_SCREENSHOT_MAX_WIDTH: int = 1280
