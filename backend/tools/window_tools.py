"""
Window management tools — snap, resize, list, focus windows.
Built on pygetwindow + win32gui for reliable Windows control.
"""
import logging
import subprocess
from typing import Optional
import pygetwindow as gw
from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="list_windows",
    description="List all open windows with their titles.",
    parameters={},
    risk_level="safe",
)
def list_windows() -> dict:
    try:
        windows = [
            {"title": w.title, "visible": w.visible, "minimized": w.isMinimized}
            for w in gw.getAllWindows()
            if w.title.strip()
        ]
        return {"success": True, "windows": windows[:40]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="maximize_window",
    description="Maximize a window by its title.",
    parameters={"title": {"type": "string", "description": "Partial or full window title"}},
    risk_level="safe",
)
def maximize_window(title: str) -> dict:
    try:
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return {"success": False, "error": f"No window found: {title}"}
        win = windows[0]
        win.maximize()
        return {"success": True, "title": win.title}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="minimize_window",
    description="Minimize a window by its title.",
    parameters={"title": {"type": "string", "description": "Partial or full window title"}},
    risk_level="safe",
)
def minimize_window(title: str) -> dict:
    try:
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return {"success": False, "error": f"No window found: {title}"}
        windows[0].minimize()
        return {"success": True, "title": windows[0].title}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="close_window",
    description="Close a window by its title.",
    parameters={"title": {"type": "string", "description": "Partial or full window title"}},
    risk_level="moderate",
)
def close_window(title: str) -> dict:
    try:
        windows = gw.getWindowsWithTitle(title)
        if not windows:
            return {"success": False, "error": f"No window found: {title}"}
        windows[0].close()
        return {"success": True, "title": title}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="snap_window",
    description="Snap a window to left half, right half, or fullscreen using Windows shortcuts.",
    parameters={
        "title":    {"type": "string", "description": "Window title to focus first"},
        "position": {"type": "string", "description": "'left', 'right', or 'fullscreen'"},
    },
    risk_level="safe",
)
def snap_window(title: str, position: str) -> dict:
    import pyautogui, time
    try:
        windows = gw.getWindowsWithTitle(title)
        if windows:
            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.3)

        snap_keys = {
            "left":       ["win", "left"],
            "right":      ["win", "right"],
            "fullscreen": ["win", "up"],
        }
        keys = snap_keys.get(position.lower())
        if not keys:
            return {"success": False, "error": f"Unknown position: {position}"}

        pyautogui.hotkey(*keys)
        return {"success": True, "title": title, "position": position}
    except Exception as e:
        return {"success": False, "error": str(e)}
