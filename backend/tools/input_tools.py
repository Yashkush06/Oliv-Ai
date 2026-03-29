"""Input tools — mouse and keyboard control via PyAutoGUI."""
import logging
import time
from typing import List

import pyautogui

from tools.registry import tool
from tools.screen_tools import find_on_screen

logger = logging.getLogger(__name__)

# Safety: fail-safe corner (move mouse to top-left to abort)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1


@tool(
    name="click",
    description="Click at a specific (x, y) screen coordinate.",
    parameters={
        "x": {"type": "integer", "description": "X coordinate"},
        "y": {"type": "integer", "description": "Y coordinate"},
        "button": {"type": "string", "description": "'left', 'right', or 'middle' (default: left)"},
    },
    risk_level="safe",
)
def click(x: int, y: int, button: str = "left") -> dict:
    logger.info(f"Click at ({x}, {y}) button={button}")
    pyautogui.click(x=x, y=y, button=button)
    return {"success": True, "x": x, "y": y, "button": button, "action_coords": [x, y]}


@tool(
    name="click_text",
    description="Find specific text on the screen and click it. Best for buttons and search bars.",
    parameters={"text": {"type": "string", "description": "Text to find and click"}},
    risk_level="moderate",
)
def click_text(text: str) -> dict:
    try:
        result = find_on_screen(text)
        if result.get("found"):
            x, y = result["x"], result["y"]
            pyautogui.click(x=x, y=y)
            return {"success": True, "message": f"Clicked text '{text}' at ({x}, {y})", "action_coords": [x, y]}
        return {"success": False, "error": result.get("message", f"Could not find text '{text}' on screen")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="double_click",
    description="Double-click at a specific (x, y) screen coordinate.",
    parameters={
        "x": {"type": "integer", "description": "X coordinate"},
        "y": {"type": "integer", "description": "Y coordinate"},
    },
    risk_level="safe",
)
def double_click(x: int, y: int) -> dict:
    logger.info(f"Double-click at ({x}, {y})")
    pyautogui.doubleClick(x=x, y=y)
    return {"success": True, "x": x, "y": y, "action_coords": [x, y]}


@tool(
    name="type_text",
    description="Type text at the current cursor position. Handles Unicode, special characters, and long text correctly.",
    parameters={
        "text":        {"type": "string",  "description": "Text to type"},
        "press_enter": {"type": "boolean", "description": "Press Enter after typing", "default": False},
    },
    risk_level="safe",
)
def type_text(text: str, press_enter: bool = False) -> dict:
    """
    Uses clipboard paste instead of typewrite() to handle:
    - Unicode / non-ASCII characters (Hindi names, emoji, etc.)
    - Long strings (typewrite is slow at scale)
    - Special characters that pyautogui misinterprets

    Falls back to typewrite for very short ASCII-only strings
    where keypress-level accuracy matters (e.g. single letters).
    """
    import pyperclip
    import pyautogui
    import time

    logger.info(f"type_text: {text[:60]}{'...' if len(text) > 60 else ''}")

    try:
        # Use clipboard paste — handles ALL characters correctly
        old_clipboard = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)
        # Restore old clipboard
        pyperclip.copy(old_clipboard)

        if press_enter:
            pyautogui.press("enter")

        curr_x, curr_y = pyautogui.position()
        return {"success": True, "length": len(text), "action_coords": [curr_x, curr_y]}

    except Exception as e:
        logger.warning(f"type_text clipboard method failed ({e}), falling back to typewrite")
        try:
            pyautogui.typewrite(text, interval=0.05)
            if press_enter:
                pyautogui.press("enter")
            curr_x, curr_y = pyautogui.position()
            return {"success": True, "length": len(text), "action_coords": [curr_x, curr_y]}
        except Exception as e2:
            return {"success": False, "error": str(e2)}


@tool(
    name="hotkey",
    description="Press a keyboard shortcut (e.g. ctrl+c, alt+tab, win+d).",
    parameters={
        "keys": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of keys to hold simultaneously, e.g. ['ctrl', 'c']",
        }
    },
    risk_level="safe",
)
def hotkey(keys: List[str]) -> dict:
    logger.info(f"Hotkey: {'+'.join(keys)}")
    pyautogui.hotkey(*keys)
    return {"success": True, "keys": keys}


@tool(
    name="scroll",
    description="Scroll the mouse wheel up or down.",
    parameters={
        "direction": {"type": "string", "description": "'up' or 'down'"},
        "amount": {"type": "integer", "description": "Number of scroll clicks (default: 3)"},
    },
    risk_level="safe",
)
def scroll(direction: str = "down", amount: int = 3) -> dict:
    clicks = amount if direction == "up" else -amount
    logger.info(f"Scroll {direction} by {amount}")
    pyautogui.scroll(clicks)
    return {"success": True, "direction": direction, "amount": amount}


@tool(
    name="press_key",
    description="Press a single keyboard key (e.g. enter, escape, tab, delete).",
    parameters={"key": {"type": "string", "description": "Key name (PyAutoGUI key string)"}},
    risk_level="safe",
)
def press_key(key: str) -> dict:
    logger.info(f"Press key: {key}")
    pyautogui.press(key)
    return {"success": True, "key": key}


@tool(
    name="move_mouse",
    description="Move the mouse cursor to an (x, y) coordinate without clicking.",
    parameters={
        "x": {"type": "integer", "description": "X coordinate"},
        "y": {"type": "integer", "description": "Y coordinate"},
    },
    risk_level="safe",
)
def move_mouse(x: int, y: int) -> dict:
    pyautogui.moveTo(x=x, y=y, duration=0.2)
    return {"success": True, "x": x, "y": y}


@tool(
    name="wait_for_text",
    description="Wait for specific text to appear on the screen.",
    parameters={
        "text": {"type": "string", "description": "Text to wait for"},
        "timeout": {"type": "integer", "description": "Max seconds to wait (default: 5)", "default": 5}
    },
    risk_level="safe",
)
def wait_for_text(text: str, timeout: int = 5) -> dict:
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = find_on_screen(text)
        if result.get("found"):
            return {"success": True, "message": f"Text '{text}' appeared"}
        time.sleep(1)
    return {"success": False, "error": f"Timed out waiting for text '{text}'"}
