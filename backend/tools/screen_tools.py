"""Screen tools — screenshot capture, OCR, and screen-text search.

find_on_screen() strategy (no external OCR binary required):
  1. Windows UI Automation (ctypes/UIA) — reads accessibility tree, zero new deps
  2. pyautogui.locateOnScreen image template — pixel match fallback
  3. pytesseract OCR — if installed (optional)
"""
import base64
import io
import logging
import time
from typing import Optional

import mss
import mss.tools
from PIL import Image

from tools.registry import tool

logger = logging.getLogger(__name__)


def _capture_screen(region: Optional[dict] = None) -> tuple[Optional[Image.Image], str]:
    """Internal: capture screen, return (PIL Image, base64 string)."""
    try:
        with mss.mss() as sct:
            monitor = region if region else sct.monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return img, b64
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        return None, ""


@tool(
    name="read_screen",
    description="Capture the current screen and return a base64-encoded PNG image.",
    parameters={
        "region": {
            "type": "object",
            "description": "Optional region: {top, left, width, height}. Omit for full screen.",
            "properties": {
                "top": {"type": "integer"},
                "left": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
        }
    },
    risk_level="safe",
)
def read_screen(region: Optional[dict] = None) -> dict:
    img, b64 = _capture_screen(region)
    if img is None:
        return {"success": False, "error": "Screenshot capture failed."}
    return {
        "success": True,
        "image_base64": b64,
        "width": img.width,
        "height": img.height,
    }


def _is_in_dashboard(x: int, y: int) -> bool:
    """Check if coordinates fall inside the Oliv AI Dashboard window."""
    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle("Oliv AI")
        if windows:
            d = windows[0]
            if d.left <= x <= d.right and d.top <= y <= d.bottom:
                # But don't ignore if it's maximized and covering the whole screen,
                # unless we are sure it's just the side panel. 
                # To be safe, if we find it in the dashboard, we return True.
                return True
    except Exception:
        pass
    return False


# ─── Window activation helper ─────────────────────────────────────────────────

def _activate_element_window(control) -> None:
    """
    Bring the top-level window containing `control` to the foreground.
    This ensures that subsequent pyautogui.click() calls at the element's
    screen coordinates actually land on the correct window, not on
    whatever window currently has focus (e.g. the Oliv Dashboard browser).
    """
    try:
        import uiautomation as auto
        import ctypes

        # Walk up the tree to find the top-level window
        parent = control
        for _ in range(50):
            p = parent.GetParentControl()
            if p is None or p == auto.GetRootControl():
                break
            parent = p

        # Try Win32 SetForegroundWindow (most reliable)
        try:
            hwnd = parent.NativeWindowHandle
            if hwnd:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

        # Also try UIA SetFocus on the found control itself
        # (brings cursor to the right input field for type_text)
        try:
            control.SetFocus()
        except Exception:
            pass

        time.sleep(0.15)  # let the window settle in foreground

    except Exception as e:
        logger.debug(f"Could not activate element window: {e}")


# ─── Strategy 1: Windows UI Automation ───────────────────────────────────────

def _find_via_uia(text: str) -> Optional[dict]:
    """
    Walk the Windows UI Automation tree to find an element whose Name or
    AutomationId contains 'text'. Returns {"x", "y", "name"} or None.

    Uses `uiautomation` package for clean access to Windows accessibility APIs.
    Works for: WhatsApp search bars, buttons, menus, text fields.

    When a match is found, the element's parent window is activated (brought
    to the foreground) to ensure clicks land on the correct window.
    """
    try:
        import uiautomation as auto

        target_lower = text.lower().strip()
        
        # Don't search too deep or too long
        auto.SetGlobalSearchTimeout(2.0)
        
        # We need a custom condition to match target text in multiple properties.
        # Just check if the target string is a substring of the combined element text.
        # This is much more robust against punctuation, concatenation, and exact phrasing
        # than splitting into word sets.

        def _match_condition(control, depth) -> bool:
            try:
                name = (control.Name or "").lower()
                auto_id = (control.AutomationId or "").lower()
                value = ""
                if auto.PatternId.ValuePattern in control.GetSupportedPatternIds():
                    try:
                        value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
                        value = (getattr(value_pattern, "Value", "") or "").lower()
                    except Exception:
                        pass

                searchable_text = f"{name} {auto_id} {value}"
                # If it's explicitly typed "no pole", look for it as a substring
                return target_lower in searchable_text
            except Exception:
                return False

        unique_matches = []
        root = auto.GetRootControl()
        for c, depth in auto.WalkTree(root, includeTop=False, maxDepth=35):
            if _match_condition(c, depth):
                try:
                    rect = c.BoundingRectangle
                    # Ensure the element has a valid, visible bounding box
                    if rect.right > rect.left and rect.bottom > rect.top and rect.left >= 0 and rect.top >= 0:
                        x = (rect.left + rect.right) // 2
                        y = (rect.top + rect.bottom) // 2
                        if not _is_in_dashboard(x, y):
                            if not any(abs(x - u["x"]) < 20 and abs(y - u["y"]) < 20 for u in unique_matches):
                                unique_matches.append({"x": x, "y": y, "name": c.Name or text, "_control": c})
                except Exception:
                    pass
        
        if len(unique_matches) > 1:
            names = [m["name"] for m in unique_matches]
            return {"ambiguous": True, "error": f"Found multiple distinct matches for '{text}': {', '.join(names)}. Please clarify which one."}
        
        if unique_matches:
            match = unique_matches[0]
            # Activate the target window so clicks land on the correct app
            _activate_element_window(match.pop("_control"))
            return match
            
        return None

    except Exception as e:
        logger.debug(f"UIA strategy unavailable: {e}")
        return None


# ─── Strategy 2: pyautogui image-based locate ─────────────────────────────────

def _find_via_pyautogui_locate(text: str) -> Optional[dict]:
    """
    Render 'text' as a small image and use pyautogui.locateOnScreen()
    to find it via pixel matching.

    This is reliable for known static labels. Less reliable for dynamic content.
    """
    try:
        import pyautogui
        from PIL import Image as PILImage, ImageDraw, ImageFont

        # Render the text to a small grayscale image
        img = PILImage.new("RGB", (len(text) * 10 + 20, 30), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((5, 5), text, fill=(0, 0, 0))

        # Save to temp buffer
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        for location in pyautogui.locateAllOnScreen(buf, confidence=0.7, grayscale=True):
            x = location.left + location.width // 2
            y = location.top + location.height // 2
            if not _is_in_dashboard(x, y):
                return {"x": x, "y": y}
    except Exception as e:
        logger.debug(f"pyautogui locate strategy failed: {e}")
    return None


# ─── Strategy 3: easyocr (fallback for WebView2/Custom UI) ────────────────

_EASYOCR_READER = None

def _get_easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr
        # Initialize reader globally so it doesn't reload the 100MB+ model every frame
        _EASYOCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _EASYOCR_READER

def _find_via_easyocr(text: str) -> Optional[dict]:
    """
    Use EasyOCR to find text on screen. This is a very robust fallback for
    WebView2 / Electron apps (like WhatsApp) that block UIA access, and
    it does not require external Tesseract binaries.
    """
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return None

    img, _ = _capture_screen()
    if img is None:
        return None

    try:
        # EasyOCR expects numpy array
        img_np = np.array(img)
        # BGR (from fromstring) is fine for EasyOCR, but let's be safe
        
        # Pull from global cache (will cache the model on first run)
        reader = _get_easyocr_reader()
        results = reader.readtext(img_np)
        
        target_lower = text.lower().strip()
        matches = []
        
        # Group all text into a single string to handle phrases split across boxes
        # (Though EasyOCR usually groups words well, sometimes it breaks them up)
        for bbox, text_found, prob in results:
            found_lower = text_found.lower().strip()
            
            # Simple substring match is more robust than strict word sets
            if target_lower in found_lower and prob > 0.4:
                # bbox is [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                x_coords = [p[0] for p in bbox]
                y_coords = [p[1] for p in bbox]
                x = int(sum(x_coords) / 4)
                y = int(sum(y_coords) / 4)
                if not _is_in_dashboard(x, y):
                    if not any(abs(x - m["x"]) < 20 and abs(y - m["y"]) < 20 for m in matches):
                        matches.append({"x": x, "y": y, "conf": prob, "text": text_found})
                        
        # If no single box contained the phrase, try to see if adjacent boxes form it
        if not matches and " " in target_lower:
            words = target_lower.split()
            # If the first word is found with high confidence, just use that as a fallback guess
            # since clicking the first word of a sentence usually clicks the whole button.
            for bbox, text_found, prob in results:
                if words[0] in text_found.lower().strip() and prob > 0.6:
                    x = int(sum([p[0] for p in bbox]) / 4)
                    y = int(sum([p[1] for p in bbox]) / 4)
                    if not _is_in_dashboard(x, y):
                        matches.append({"x": x, "y": y, "conf": prob, "text": text_found})
                        break
                
        if len(matches) > 1:
            names = [m["text"] for m in matches]
            return {"ambiguous": True, "error": f"Found multiple distinct matches for '{text}': {', '.join(names)}. Please clarify which one."}

        if matches:
            best = max(matches, key=lambda m: m["conf"])
            return best
    except Exception as e:
        logger.debug(f"EasyOCR strategy failed: {e}")
    return None


# ─── Strategy 4: pytesseract OCR (legacy optional) ────────────────────────────

def _find_via_ocr(text: str) -> Optional[dict]:
    """Use pytesseract if available."""
    try:
        import pytesseract
    except ImportError:
        return None

    img, _ = _capture_screen()
    if img is None:
        return None

    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        target = text.lower().strip()
        matches = []
        
        # Reconstruct lines because data["text"] is just individual split words!
        # Checking if "no pole" is inside data["text"][i] is mathematically impossible.
        n_boxes = len(data["text"])
        for i in range(n_boxes):
            word = data["text"][i].lower().strip()
            conf = int(data["conf"][i])
            if not word or conf < 30:
                continue
                
            # If target is a single word, or target is inside this single word
            if target in word:
                x = data["left"][i] + data["width"][i] // 2
                y = data["top"][i] + data["height"][i] // 2
                if not _is_in_dashboard(x, y):
                    matches.append({"x": x, "y": y, "conf": conf})
            
            # If target is multi-word, check if the first word matches and just click it
            elif " " in target and target.startswith(word):
                x = data["left"][i] + data["width"][i] // 2
                y = data["top"][i] + data["height"][i] // 2
                if not _is_in_dashboard(x, y):
                    matches.append({"x": x, "y": y, "conf": conf})

        if matches:
            best = max(matches, key=lambda m: m["conf"])
            return best
    except Exception as e:
        logger.debug(f"OCR strategy failed: {e}")
    return None


# ─── Public: find_on_screen ───────────────────────────────────────────────────

def find_on_screen(text: str) -> dict:
    """
    Find text on screen using the best available strategy.

    Priority:
      1. Windows UI Automation (accessibility tree) — fastest, no deep WebView2
      2. pyautogui image locate — precise template match
      3. easyocr — robust ML fallback for WebView2/Electron (WhatsApp)
      4. pytesseract — legacy OCR fallback
    """
    # Strategy 1: UIA
    result = _find_via_uia(text)
    if result:
        if result.get("ambiguous"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "found": True, "x": result["x"], "y": result["y"],
                "method": "uia", "word": result.get("name", text)}

    # Strategy 2: Image locate
    result = _find_via_pyautogui_locate(text)
    if result:
        return {"success": True, "found": True, "x": result["x"], "y": result["y"],
                "method": "pyautogui"}

    # Strategy 3: EasyOCR (needed for secure WebViews like WhatsApp)
    result = _find_via_easyocr(text)
    if result:
        if result.get("ambiguous"):
            return {"success": False, "error": result["error"]}
        return {"success": True, "found": True, "x": result["x"], "y": result["y"],
                "method": "easyocr"}

    # Strategy 4: Legacy Pytesseract
    result = _find_via_ocr(text)
    if result:
        return {"success": True, "found": True, "x": result["x"], "y": result["y"],
                "method": "pytesseract"}

    logger.warning(f"find_on_screen: '{text}' not found via any strategy")
    return {"success": True, "found": False, "message": f"'{text}' not found on screen."}


def get_screen_text() -> dict:
    """OCR the full screen via pytesseract (if available)."""
    try:
        import pytesseract
    except ImportError:
        return {
            "success": False,
            "error": "pytesseract not installed. Run: pip install pytesseract (and install Tesseract OCR for Windows).",
        }

    img, _ = _capture_screen()
    if img is None:
        return {"success": False, "error": "Screenshot capture failed."}

    try:
        text = pytesseract.image_to_string(img)
        return {"success": True, "text": text.strip()}
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return {"success": False, "error": str(e)}


def wait_for_text(text: str, timeout: int = 15) -> dict:
    """
    Poll the screen every second until 'text' is visible or timeout expires.
    Uses the multi-strategy find_on_screen.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = find_on_screen(text)
        if result.get("found"):
            return result
        if not result.get("success"):
            return result
        time.sleep(1)

    return {
        "success": False,
        "found": False,
        "error": f"'{text}' did not appear on screen within {timeout}s.",
    }
