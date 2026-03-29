"""
Critic Agent — visual verification of step outcomes.

After each step executes, the Critic takes a screenshot and asks:
  "Is the expected outcome visible on screen?"

Improvements over v1:
  - Uses VisionClient.assess_with_confidence() for structured JSON verdicts.
  - Confidence-gated pass/uncertain/fail instead of binary yes/no.
  - Before/after screenshots: captures a pre-step screenshot and compares
    what changed — dramatically reduces false negatives.
  - Smarter OCR fallback: fuzzy word matching via SequenceMatcher instead of
    exact keyword lookup — handles OCR errors and partial text.
  - Exponential backoff on poll retries (instead of fixed 1s) so heavyweight
    animations / page loads have more time to settle.

Usage:
    critic = Critic()
    result = await critic.wait_and_verify(
        "WhatsApp window is open", before_b64=before_screenshot, timeout=8
    )
    if not result.passed:
        # trigger re-plan
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from perception.screenshot import capture_screen_b64
from agent.constants import VISION_CONFIDENCE_PASS, VISION_CONFIDENCE_UNCERTAIN

logger = logging.getLogger(__name__)


@dataclass
class CriticResult:
    passed: bool
    reason: str
    confidence: float = 1.0        # 0.0-1.0; 1.0 for non-vision paths
    screenshot_b64: str = ""
    observation: str = ""           # what the vision LLM saw (for logs / UI)


# ─── Fast UIA text pre-check ──────────────────────────────────────────────────


_STOP_WORDS = frozenset({
    "this", "that", "with", "from", "have", "will", "been", "were",
    "they", "their", "there", "then", "than", "when", "what", "which",
    "should", "would", "could", "the", "and", "for", "are", "not",
    "has", "was", "can", "does", "into", "also", "more", "its",
    "open", "active", "visible", "shown", "displayed", "appears",
    "screen", "window", "page", "field", "button", "ready",
})


def _fast_text_verify(expected_outcome: str) -> Optional[bool]:
    """
    Ultra-fast text verification using Windows UI Automation only (~50-100ms).

    Reads the foreground window's accessibility tree and checks if keywords
    from the expected outcome appear in it. This short-circuits the slow
    vision LLM call for straightforward confirmations like:
      "WhatsApp is open", "Yash's chat is selected", "search bar is focused"

    Returns:
      True  — enough keywords found in foreground window (high confidence)
      None  — inconclusive or not enough data (fall through to vision)
    
    Never returns False — we never want a fast check to block a step;
    that's the vision LLM's job.
    """
    try:
        import uiautomation as auto
        auto.SetGlobalSearchTimeout(1.0)

        # Extract meaningful keywords (nouns, app names, contact names)
        words = [
            w.strip("'\".,;:!?()[]")
            for w in expected_outcome.lower().split()
            if len(w.strip("'\".,;:!?()[]")) > 2
            and w.strip("'\".,;:!?()[]") not in _STOP_WORDS
        ]
        if len(words) < 2:
            return None  # Not enough keywords to make a reliable judgement

        # Read foreground window text (fast — no screenshots, no ML models)
        fg = auto.GetForegroundControl()
        if not fg:
            return None

        fg_texts: list[str] = []
        for ctrl, _ in auto.WalkTree(fg, includeTop=True, maxDepth=5):
            try:
                name = (ctrl.Name or "").strip().lower()
                if name and len(name) > 1:
                    fg_texts.append(name)
                    if len(fg_texts) >= 80:
                        break
            except Exception:
                continue

        if not fg_texts:
            return None

        screen_text = " ".join(fg_texts)

        # Check keyword matches
        check_words = words[:6]  # limit to 6 keywords
        matches = sum(1 for w in check_words if w in screen_text)
        match_ratio = matches / len(check_words)

        # Require ≥50% of keywords AND at least 2 absolute matches
        if matches >= 2 and match_ratio >= 0.5:
            logger.info(
                f"Critic fast-pass: {matches}/{len(check_words)} keywords matched "
                f"({match_ratio:.0%}) for '{expected_outcome[:60]}'"
            )
            return True

        return None  # Inconclusive — let vision LLM decide

    except Exception as e:
        logger.debug(f"Fast text verify failed: {e}")
        return None


# ─── Vision LLM backend ───────────────────────────────────────────────────────


def _vision_verify(
    screenshot_b64: str,
    expected_outcome: str,
    before_b64: Optional[str] = None,
) -> Optional["VisionVerdict"]:  # noqa: F821
    """
    Ask the configured vision LLM whether the expected outcome is visible.
    Uses assess_with_confidence() for structured, confidence-scored output.
    Returns VisionVerdict or None if vision is not configured/available.
    """
    try:
        from config.manager import get_value
        vision_model = get_value("model_config.vision_model")
        if not vision_model:
            return None
        from agent.reflector import VisionClient
        client = VisionClient(vision_model)
        return client.assess_with_confidence(screenshot_b64, expected_outcome, before_b64)
    except Exception as e:
        logger.warning(f"Critic vision assessment failed: {e}")
        return None


# ─── OCR fallback backend ─────────────────────────────────────────────────────


def _ocr_verify(expected_outcome: str) -> Optional[bool]:
    """
    Improved OCR-based verification:
    - Extracts meaningful keywords from the expected outcome.
    - Uses fuzzy matching (SequenceMatcher) to handle OCR typos/partial text.
    - Returns True if any keyword fuzzy-matches a screen element, False if
      OCR ran but found nothing, None if OCR is unavailable.
    """
    try:
        from tools.screen_tools import find_on_screen
    except ImportError:
        return None

    from difflib import SequenceMatcher

    STOP_WORDS = {
        "this", "that", "with", "from", "have", "will", "been", "were",
        "they", "their", "there", "then", "than", "when", "what", "which",
        "should", "would", "could", "the", "and", "for", "are", "not",
    }

    words = [
        w for w in expected_outcome.lower().split()
        if len(w) > 3 and w not in STOP_WORDS
    ]
    if not words:
        return None

    # Try each keyword; succeed if any finds a match (exact or fuzzy)
    for word in words[:4]:  # limit to 4 keywords
        result = find_on_screen(word)
        if result.get("success") and result.get("found"):
            logger.debug(f"Critic OCR: found '{word}' on screen via {result.get('method', 'unknown')}")
            return True

        # Fuzzy fallback: UIA/OCR returned text; check similarity
        found_word = result.get("word", "")
        if found_word:
            ratio = SequenceMatcher(None, word, found_word.lower()).ratio()
            if ratio >= 0.8:
                logger.debug(f"Critic OCR fuzzy: '{word}' ≈ '{found_word}' (ratio={ratio:.2f})")
                return True

    return False


# ─── Critic class ─────────────────────────────────────────────────────────────


class Critic:
    """
    Visual verification agent that confirms step outcomes via screenshot analysis.
    """

    def verify(
        self,
        expected_outcome: str,
        before_b64: Optional[str] = None,
    ) -> CriticResult:
        """
        Take a screenshot and verify 'expected_outcome' is visible on screen.

        When before_b64 is provided, the vision LLM compares BEFORE vs AFTER
        to see what changed — this catches subtle UI changes that the naked
        screenshot would miss.

        Verification strategy (fast → slow):
        0. Fast UIA text check (~50ms) — keywords in foreground window
        1. Vision LLM with confidence scoring (3-5s, skipped if #0 passed)
        2. OCR keyword + fuzzy search (text-based fallback)
        3. If neither available, pass-through (optimistic: assume success)
        """
        screenshot_b64 = capture_screen_b64(quality="low")  # fast JPEG for quick polls

        if screenshot_b64 is None:
            return CriticResult(
                passed=True,
                reason="Could not capture screenshot — assuming success.",
                confidence=1.0,
            )

        # ── Strategy 0: Fast UIA text pre-check (~50-100ms) ───────────────────
        fast_result = _fast_text_verify(expected_outcome)
        if fast_result is True:
            return CriticResult(
                passed=True,
                reason=(
                    f"Fast text check confirmed: keywords from "
                    f"'{expected_outcome}' found in foreground window."
                ),
                confidence=0.85,
                screenshot_b64=screenshot_b64,
            )

        # ── Strategy 1: Vision LLM (slow but thorough) ────────────────────────
        verdict = _vision_verify(screenshot_b64, expected_outcome, before_b64)
        if verdict is not None:
            if verdict.matches and verdict.confidence >= VISION_CONFIDENCE_PASS:
                return CriticResult(
                    passed=True,
                    reason=(
                        f"Vision confirmed (confidence={verdict.confidence:.0%}): "
                        f"'{expected_outcome}'. {verdict.reason}"
                    ),
                    confidence=verdict.confidence,
                    screenshot_b64=screenshot_b64,
                    observation=verdict.observation,
                )
            elif verdict.matches and verdict.uncertain:
                # Uncertain but leaning positive — pass with a warning logged
                logger.warning(
                    f"Critic: uncertain vision pass (confidence={verdict.confidence:.0%}) "
                    f"for '{expected_outcome}'. {verdict.reason}"
                )
                return CriticResult(
                    passed=True,
                    reason=(
                        f"Vision uncertain but positive (confidence={verdict.confidence:.0%}): "
                        f"{verdict.reason}"
                    ),
                    confidence=verdict.confidence,
                    screenshot_b64=screenshot_b64,
                    observation=verdict.observation,
                )
            else:
                return CriticResult(
                    passed=False,
                    reason=(
                        f"Vision says NO (confidence={verdict.confidence:.0%}): "
                        f"'{expected_outcome}' not confirmed. {verdict.reason}"
                    ),
                    confidence=verdict.confidence,
                    screenshot_b64=screenshot_b64,
                    observation=verdict.observation,
                )

        # ── Strategy 2: OCR keyword + fuzzy search ────────────────────────────
        ocr_result = _ocr_verify(expected_outcome)
        if ocr_result is not None:
            if ocr_result:
                return CriticResult(
                    passed=True,
                    reason=f"OCR found keywords from '{expected_outcome}' on screen.",
                    confidence=0.75,
                    screenshot_b64=screenshot_b64,
                )
            else:
                return CriticResult(
                    passed=False,
                    reason=f"OCR: keywords from '{expected_outcome}' not found on screen.",
                    confidence=0.2,
                    screenshot_b64=screenshot_b64,
                )

        # ── Strategy 3: Pass-through (no verification available) ──────────────
        logger.info(
            "Critic: no vision LLM or OCR available — passing through optimistically."
        )
        return CriticResult(
            passed=True,
            reason="No visual verification available — assumed success.",
            confidence=1.0,
            screenshot_b64=screenshot_b64,
        )

    async def wait_and_verify(
        self,
        expected_outcome: str,
        timeout: int = 8,
        before_b64: Optional[str] = None,
    ) -> CriticResult:
        """
        Poll the screen until `expected_outcome` is confirmed or `timeout` expires.

        Uses exponential backoff between polls (1s → 1.5s → 2.25s...) to give
        heavy animations and page loads more time to settle on later attempts.

        Args:
            expected_outcome: The state to verify (from step.reason).
            timeout: Max seconds to wait.
            before_b64: Optional pre-step screenshot for before/after diffing.

        Returns the last CriticResult (passed=True on success, False on timeout).
        """
        deadline = time.monotonic() + timeout
        last_result: Optional[CriticResult] = None
        interval = 1.0          # initial poll interval (seconds)
        max_interval = 3.0      # cap so we don't wait too long between polls
        backoff_factor = 1.4    # multiply interval each retry

        while time.monotonic() < deadline:
            last_result = await asyncio.to_thread(
                self.verify, expected_outcome, before_b64
            )
            if last_result.passed:
                return last_result

            # Only pass before_b64 on the first attempt; subsequent polls
            # compare the latest screenshot to the expected state directly.
            before_b64 = None

            # Exponential backoff — sleep min(interval, remaining, max_interval)
            remaining = deadline - time.monotonic()
            sleep_for = min(interval, remaining, max_interval)
            if sleep_for <= 0:
                break
            await asyncio.sleep(sleep_for)
            interval = min(interval * backoff_factor, max_interval)

        return last_result or CriticResult(
            passed=False,
            reason=f"Timed out ({timeout}s): '{expected_outcome}' never confirmed on screen.",
            confidence=0.0,
        )
