"""
Shared screenshot utility for Critic and Reflector.
Single source of truth for screen capture logic.

Features:
  - Smart downscaling to max 1280px wide (75% token savings for vision APIs)
  - JPEG compression option for fast Critic polls
  - Region capture for focused screenshots around action targets
  - Full-resolution PNG fallback for compatibility
"""
import base64
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Max width for resized screenshots sent to vision LLMs (balances quality vs token cost)
_MAX_WIDTH = 1280


def _resize_for_vision(img) -> "Image":
    """Resize image to max _MAX_WIDTH wide, preserving aspect ratio."""
    try:
        from PIL import Image
        w, h = img.size
        if w > _MAX_WIDTH:
            ratio = _MAX_WIDTH / w
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
    except Exception as e:
        logger.debug(f"Image resize failed: {e}")
    return img


def _encode_image(img, quality: str = "high") -> str:
    """
    Encode PIL Image to base64 string.
    quality="high" → PNG (lossless, for detailed analysis)
    quality="low"  → JPEG q=65 (smaller, for fast Critic polls)
    """
    buf = io.BytesIO()
    if quality == "low":
        img.save(buf, format="JPEG", quality=65, optimize=True)
    else:
        img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def capture_screen_b64(quality: str = "high") -> Optional[str]:
    """
    Take a full-screen screenshot of monitor 1, downscale to max 1280px wide,
    and return as a base64-encoded image string.

    Args:
        quality: "high" (PNG, lossless) or "low" (JPEG q=65, ~4x smaller).

    Returns None if the capture fails for any reason.
    """
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        img = _resize_for_vision(img)
        return _encode_image(img, quality=quality)

    except Exception as e:
        logger.warning(f"Screen capture failed: {e}")
        return None


def capture_region_b64(
    x: int, y: int, width: int, height: int, quality: str = "high"
) -> Optional[str]:
    """
    Capture a specific region of the screen (useful for focusing on a clicked area
    or a specific window, reducing noise given to the vision LLM).

    Args:
        x, y: Top-left corner of the region (screen coordinates).
        width, height: Size of the region.
        quality: "high" (PNG) or "low" (JPEG).

    Returns base64-encoded image or None on failure.
    """
    try:
        import mss
        from PIL import Image

        region = {"left": x, "top": y, "width": width, "height": height}
        with mss.mss() as sct:
            shot = sct.grab(region)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        img = _resize_for_vision(img)
        return _encode_image(img, quality=quality)

    except Exception as e:
        logger.warning(f"Region capture failed: {e}")
        return None
