"""
Clipboard tools — essential for copy/paste automation.
Uses pyperclip (cross-platform) with Windows fallback via win32clipboard.
"""
import logging
from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="get_clipboard",
    description="Get the current text content of the clipboard.",
    parameters={},
    risk_level="safe",
)
def get_clipboard() -> dict:
    try:
        import pyperclip
        text = pyperclip.paste()
        return {"success": True, "text": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="set_clipboard",
    description="Set the clipboard to a specific text value.",
    parameters={"text": {"type": "string", "description": "Text to copy to clipboard"}},
    risk_level="safe",
)
def set_clipboard(text: str) -> dict:
    try:
        import pyperclip
        pyperclip.copy(text)
        return {"success": True, "text": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="copy_selection",
    description="Press Ctrl+C to copy the current selection to clipboard.",
    parameters={},
    risk_level="safe",
)
def copy_selection() -> dict:
    try:
        import pyautogui
        import time
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.3)
        import pyperclip
        text = pyperclip.paste()
        return {"success": True, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="paste_text",
    description="Paste text by setting clipboard then pressing Ctrl+V. Better than type_text for non-ASCII, long text, or special characters.",
    parameters={"text": {"type": "string", "description": "Text to paste"}},
    risk_level="safe",
)
def paste_text(text: str) -> dict:
    """
    This is the FIX for the type_text Unicode bug.
    typewrite() breaks on Hindi names, emoji, special chars.
    paste_text() handles everything correctly.
    """
    try:
        import pyperclip
        import pyautogui
        import time
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        return {"success": True, "text": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}
