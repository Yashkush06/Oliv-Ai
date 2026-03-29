"""System tools — open apps, run commands, list processes."""
import logging
import subprocess
import os
import time
import psutil
import pyautogui
import pygetwindow as gw

from tools.registry import tool
from config.resolver import resolve_app

logger = logging.getLogger(__name__)

# ─── App Registry ─────────────────────────────────────────────────────────────
# Maps normalized app names → preferred launch strategy.
# Priority: uri (UWP/Store) > exe (Win32) > search_name (Win+S fallback)

APP_REGISTRY: dict[str, dict] = {
    "whatsapp":    {"uri": "whatsapp:",          "process": "WhatsApp.exe",    "search_name": "WhatsApp"},
    "calculator":  {"uri": "ms-calculator:",    "process": "Calculator.exe", "search_name": "Calculator"},
    "settings":    {"uri": "ms-settings:",       "process": "SystemSettings.exe", "search_name": "Settings"},
    "photos":      {"uri": "ms-photos:",         "process": "Microsoft.Photos.exe", "search_name": "Photos"},
    "mail":        {"uri": "ms-outlookmail:",    "process": "HxOutlook.exe", "search_name": "Mail"},
    "spotify":     {"uri": "spotify:",           "process": "Spotify.exe",    "search_name": "Spotify"},
    "slack":       {"exe": "slack.exe",           "process": "slack.exe",      "search_name": "Slack"},
    "discord":     {"exe": "discord.exe",         "process": "Discord.exe",    "search_name": "Discord"},
    "chrome":      {"exe": "chrome.exe",           "process": "chrome.exe",     "search_name": "Google Chrome"},
    "firefox":     {"exe": "firefox.exe",          "process": "firefox.exe",    "search_name": "Firefox"},
    "edge":        {"exe": "msedge.exe",            "process": "msedge.exe",     "search_name": "Microsoft Edge"},
    "notepad":     {"exe": "notepad.exe",           "process": "notepad.exe",    "search_name": "Notepad"},
    "paint":       {"exe": "mspaint.exe",           "process": "mspaint.exe",    "search_name": "Paint"},
    "vscode":      {"exe": "code",                  "process": "Code.exe",       "search_name": "Visual Studio Code"},
    "explorer":    {"exe": "explorer.exe",           "process": "explorer.exe",   "search_name": "File Explorer"},
    "terminal":    {"exe": "wt.exe",                 "process": "WindowsTerminal.exe", "search_name": "Terminal"},
    "powershell":  {"exe": "powershell.exe",          "process": "powershell.exe","search_name": "PowerShell"},
    "cmd":         {"exe": "cmd.exe",                 "process": "cmd.exe",        "search_name": "Command Prompt"},
    "word":        {"search_name": "Word"},
    "excel":       {"search_name": "Excel"},
    "powerpoint":  {"search_name": "PowerPoint"},
    "teams":       {"uri": "msteams:",             "process": "Teams.exe",      "search_name": "Microsoft Teams"},
    "zoom":        {"exe": "zoom.exe",               "process": "Zoom.exe",       "search_name": "Zoom"},
    "telegram":    {"exe": "telegram.exe",            "process": "Telegram.exe",   "search_name": "Telegram"},
    "vlc":         {"exe": "vlc.exe",                 "process": "vlc.exe",        "search_name": "VLC"},
}


def _normalize_app_name(name: str) -> str:
    """Lowercase and strip common suffixes for registry lookup."""
    return name.lower().strip().replace(" ", "")


def _launch_via_run_dialog(app_name: str) -> bool:
    """
    Launch an app via the Win+R Run dialog instead of Win+S search.
    
    Win+R opens a real dialog window (visible to screenshots and UIA),
    unlike Win+S which opens the Start overlay (invisible to the agent's
    vision system and causes confusion).
    """
    try:
        logger.info(f"Launching via Win+R: '{app_name}'")
        pyautogui.hotkey("win", "r")
        time.sleep(0.5)  # wait for Run dialog
        pyautogui.typewrite(app_name, interval=0.03)
        time.sleep(0.3)
        pyautogui.press("enter")
        return True
    except Exception as e:
        logger.warning(f"Win+R launch failed: {e}")
        return False


@tool(
    name="open_app",
    description="Open an application by name or category (e.g., 'browser', 'notepad', 'chrome', 'whatsapp').",
    parameters={"app_name": {"type": "string", "description": "App name or category"}},
    risk_level="moderate",
)
def open_app(app_name: str) -> dict:
    """
    Launch an app using the most reliable method available, in order:
      1. App Registry URI scheme  (best for UWP/Store apps like WhatsApp)
      2. App Registry .exe path   (best for Win32 apps)
      3. Category alias resolver  (browser → chrome, etc.)
      4. Win+S search fallback    (universal — works like a human would)
    """
    key = _normalize_app_name(app_name)
    entry = APP_REGISTRY.get(key)

    logger.info(f"open_app: '{app_name}' → key='{key}', registry={'found' if entry else 'miss'}")

    # ── Method 1: URI scheme (UWP / Windows Store apps) ──────────────────────
    if entry and entry.get("uri"):
        try:
            os.startfile(entry["uri"])
            logger.info(f"Launched '{app_name}' via URI: {entry['uri']}")
            return {"success": True, "app": app_name, "method": "uri", "detail": entry["uri"]}
        except Exception as e:
            logger.warning(f"URI launch failed for '{app_name}': {e}")

    # ── Method 2: .exe path (Win32 apps) ────────────────────────────────────
    if entry and entry.get("exe"):
        try:
            subprocess.Popen(entry["exe"], shell=True)
            logger.info(f"Launched '{app_name}' via exe: {entry['exe']}")
            return {"success": True, "app": app_name, "method": "exe", "detail": entry["exe"]}
        except Exception as e:
            logger.warning(f"EXE launch failed for '{app_name}': {e}")

    # ── Method 3: Category alias (browser, editor, terminal) ─────────────────
    if app_name.lower() in ("browser", "editor", "terminal"):
        resolved = resolve_app(app_name)
        try:
            subprocess.Popen(resolved, shell=True)
            return {"success": True, "app": resolved, "method": "alias", "detail": resolved}
        except Exception as e:
            logger.warning(f"Alias launch failed for '{app_name}': {e}")

    # ── Method 4: Win+R run dialog fallback (works for anything with an exe) ──
    # Win+R accepts executable names, not display names
    run_name = (entry or {}).get("exe") or (entry or {}).get("process") or app_name
    ok = _launch_via_run_dialog(run_name)
    if ok:
        return {"success": True, "app": app_name, "method": "win_run", "detail": run_name}

    return {"success": False, "error": f"All launch methods failed for '{app_name}'."}


@tool(
    name="focus_window",
    description="Bring a window to the foreground by its title.",
    parameters={"title": {"type": "string", "description": "Partial or full window title"}},
    risk_level="safe",
)
def focus_window(title: str) -> dict:
    try:
        windows = gw.getWindowsWithTitle(title)
        if windows:
            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            return {"success": True, "message": f"Focused window: {win.title}"}
        return {"success": False, "error": f"No window found with title: {title}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="run_command",
    description="Run a shell command. Use carefully — will be blocked if dangerous.",
    parameters={"command": {"type": "string", "description": "Shell command to run"}},
    risk_level="dangerous",
)
def run_command(command: str) -> dict:
    logger.info(f"Running command: {command}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 30s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="list_running_apps",
    description="List currently running application processes.",
    parameters={},
    risk_level="safe",
)
def list_running_apps() -> dict:
    apps = []
    seen = set()
    for proc in psutil.process_iter(["name", "pid"]):
        name = proc.info.get("name", "")
        if name and name not in seen:
            seen.add(name)
            apps.append({"name": name, "pid": proc.info.get("pid")})
    return {"success": True, "apps": apps[:50]}  # cap at 50


@tool(
    name="is_app_running",
    description="Check if an application is currently running.",
    parameters={"app_name": {"type": "string", "description": "Process name to check (e.g. 'chrome.exe')"}},
    risk_level="safe",
)
def is_app_running(app_name: str) -> dict:
    running = any(
        p.info.get("name", "").lower() == app_name.lower()
        for p in psutil.process_iter(["name"])
    )
    return {"success": True, "running": running, "app": app_name}
