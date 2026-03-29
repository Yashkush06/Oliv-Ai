"""
Reflector — evaluates whether a step succeeded.

Phase 1: success = no exception raised.
Phase 2: VisionClient uses a vision-capable LLM (LLaVA/GPT-4o) to visually
         verify whether the step achieved its goal.

Improvements over v1:
  - Chain-of-thought vision prompts: structured JSON output with observation,
    confidence score (0.0-1.0), and reason instead of bare yes/no.
  - VisionVerdict dataclass: rich result with confidence-gated pass/fail.
  - Before/after diff prompting: when a before screenshot is available, the LLM
    explicitly compares what changed to validate the action.
  - assess_with_confidence(): new primary method used by Critic and Reflector.
  - Confidence thresholds from constants: VISION_CONFIDENCE_PASS / UNCERTAIN.
"""
import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from perception.screenshot import capture_screen_b64
from agent.constants import (
    SKIP_VISUAL_VERIFICATION_TOOLS,
    VISION_CONFIDENCE_PASS,
    VISION_CONFIDENCE_UNCERTAIN,
)

logger = logging.getLogger(__name__)


class ReflectionStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"


@dataclass
class Reflection:
    status: ReflectionStatus
    message: str
    should_retry: bool = False
    retry_count: int = 0


# ─── VisionVerdict — rich output from VisionClient ───────────────────────────

@dataclass
class VisionVerdict:
    """
    Structured result from a vision assessment.
    Replaces the bare boolean returned by assess().
    """
    matches: bool          # Did the expected outcome appear to happen?
    confidence: float      # 0.0 (totally wrong) → 1.0 (perfectly confirmed)
    observation: str       # What the vision LLM actually sees on screen
    reason: str            # Why it decided matches=True/False
    uncertain: bool = False  # True if 0.4 <= confidence < 0.7 (lenient pass)


# ─── Chain-of-thought vision prompts ─────────────────────────────────────────

_VERIFY_PROMPT_SINGLE = """\
You are an AI agent verifying that a Windows desktop action succeeded.
The intended outcome of the action was: '{expected}'

Look at the screenshot carefully. Identify what is visible.

Respond with ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "observation": "<2-3 sentences: exactly what you see on screen right now>",
  "matches_expected": <true or false>,
  "confidence": <0.0 to 1.0, where 1.0 = completely certain it matches>,
  "reason": "<one concise sentence explaining your decision>"
}}

Confidence guide:
  0.9-1.0: The expected outcome is clearly visible on screen.
  0.7-0.9: Very likely correct, minor uncertainty (e.g. partial view).
  0.4-0.7: Ambiguous — could be a transitional state or intermediate step.
  0.0-0.4: The expected outcome does NOT appear to be visible.
"""

_VERIFY_PROMPT_DIFF = """\
You are an AI agent verifying that a Windows desktop action succeeded.
You are given a BEFORE screenshot and an AFTER screenshot.
The intended outcome of the action was: '{expected}'

Compare the two screenshots. Identify what changed between BEFORE and AFTER.

Respond with ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "observation": "<what changed between BEFORE and AFTER screenshots>",
  "matches_expected": <true or false>,
  "confidence": <0.0 to 1.0, where 1.0 = completely certain it matches>,
  "reason": "<one concise sentence: does the visible change match the expected outcome?>"
}}

Confidence guide:
  0.9-1.0: The change clearly matches the expected outcome.
  0.7-0.9: Very likely correct, minor uncertainty.
  0.4-0.7: Ambiguous — partial change or intermediate state.
  0.0-0.4: No visible change, or the change does NOT match the expected outcome.
"""


# ─── Phase 2 Vision Client ────────────────────────────────────────────────────

class VisionClient:
    """
    Visual verification via a vision-capable LLM.

    Supported backends:
    - "gemini"          → Google Gemini Flash vision (uses configured gemini_api_key)
    - "ollama:llava"    → Ollama vision model (e.g. llava, bakllava)
    - "api:gpt-4o"      → OpenAI-compatible vision API

    Config key: model_config.vision_model
      Format:  "gemini"  |  "ollama:llava"  |  "api:gpt-4o"
    """

    def __init__(self, vision_model: str, router=None):
        """
        vision_model: e.g. "ollama:llava" or "api:gpt-4o"
        router: LLMRouter (only used as fallback; vision calls go direct to provider)
        """
        self._spec = vision_model
        self._router = router
        self._backend, self._model_name = self._parse_spec(vision_model)

    @staticmethod
    def _parse_spec(spec: str):
        """Parse "backend:model_name" notation.

        Special cases:
          "gemini"       → backend='gemini', uses configured gemini_api_key + gemini_model
          "ollama:llava" → backend='ollama', model='llava'
          "api:gpt-4o"   → backend='api',    model='gpt-4o'
        """
        lower = spec.lower().strip()
        # Bare 'gemini' keyword — route to Gemini vision backend
        if lower in ("gemini", "gemini-flash", "gemini-pro"):
            return "gemini", spec
        if ":" in spec:
            parts = spec.split(":", 1)
            return parts[0].lower(), parts[1]
        # Default: treat as ollama model
        return "ollama", spec


    # ── Primary method (replaces assess() as the main entry point) ────────────

    def assess_with_confidence(
        self,
        screenshot_b64: str,
        expected_result: str,
        before_b64: Optional[str] = None,
    ) -> VisionVerdict:
        """
        Send screenshot(s) to the vision LLM and return a rich VisionVerdict
        with confidence score, observation, and reason.

        Uses chain-of-thought JSON prompts for structured, reliable output.
        Falls back to a low-confidence failure verdict on any error.
        """
        prompt = (
            _VERIFY_PROMPT_DIFF.format(expected=expected_result)
            if before_b64
            else _VERIFY_PROMPT_SINGLE.format(expected=expected_result)
        )

        try:
            if self._backend == "gemini":
                raw = self._call_gemini(screenshot_b64, prompt, before_b64)
            elif self._backend == "ollama":
                raw = self._call_ollama(screenshot_b64, prompt, before_b64)
            elif self._backend in ("api", "openai", "anthropic", "groq"):
                raw = self._call_api(screenshot_b64, prompt, before_b64)
            else:
                logger.warning(f"Unknown vision backend: {self._backend}")
                return self._failure_verdict("Unknown vision backend")

            return self._parse_verdict(raw)

        except Exception as e:
            logger.warning(f"VisionClient.assess_with_confidence failed: {e}")
            return self._failure_verdict(str(e))

    def assess(self, screenshot_b64: str, expected_result: str, before_b64: Optional[str] = None) -> bool:
        """
        Legacy boolean wrapper — calls assess_with_confidence() under the hood.
        Returns True if confidence >= VISION_CONFIDENCE_UNCERTAIN (lenient).
        Kept for backward compatibility with any code still using the old API.
        """
        verdict = self.assess_with_confidence(screenshot_b64, expected_result, before_b64)
        logger.debug(
            f"Vision assess (legacy): matches={verdict.matches}, "
            f"confidence={verdict.confidence:.2f}, reason={verdict.reason!r}"
        )
        return verdict.matches and verdict.confidence >= VISION_CONFIDENCE_UNCERTAIN

    # ── Backend callers ───────────────────────────────────────────────────────

    def _call_gemini(self, screenshot_b64: str, prompt: str, before_b64: Optional[str] = None) -> str:
        """Call Google Gemini vision via GeminiClient.generate_with_vision()."""
        from config.manager import get_value
        from llm.gemini_client import GeminiClient

        api_key = get_value("model_config.gemini_api_key") or ""
        if not api_key:
            raise ValueError("Gemini vision requested but gemini_api_key is not configured")

        # Use gemini_model from config (default: gemini-2.0-flash which supports vision)
        model = get_value("model_config.gemini_model", "gemini-2.0-flash")
        client = GeminiClient(api_key=api_key, model=model)
        raw = client.generate_with_vision(prompt=prompt, screenshot_b64=screenshot_b64, before_b64=before_b64)
        logger.debug(f"Vision (gemini/{model}) raw response: {raw[:200]!r}")
        return raw

    def _call_ollama(self, screenshot_b64: str, prompt: str, before_b64: Optional[str] = None) -> str:
        """Call Ollama vision endpoint (supports llava, bakllava, etc.)."""
        import httpx
        from config.manager import get_value

        base_url = get_value("model_config.base_url", "http://localhost:11434")
        images = [before_b64, screenshot_b64] if before_b64 else [screenshot_b64]

        payload = {
            "model": self._model_name,
            "prompt": prompt,
            "images": images,
            "stream": False,
        }
        resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        logger.debug(f"Vision (ollama) raw response: {raw[:200]!r}")
        return raw

    def _call_api(self, screenshot_b64: str, prompt: str, before_b64: Optional[str] = None) -> str:
        """Call OpenAI-compatible vision API (GPT-4o, GPT-4-vision)."""
        from openai import OpenAI
        from config.manager import get_value

        api_key = get_value("model_config.api_key") or ""
        base_url = get_value("model_config.base_url")

        client_kwargs = {"api_key": api_key}
        if base_url and self._backend not in ("openai",):
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        # Determine MIME type based on whether it's JPEG (low quality) or PNG
        def _mime(b64: str) -> str:
            # JPEG base64 starts with /9j; PNG starts with iVBOR
            return "image/jpeg" if b64.startswith("/9j") else "image/png"

        content = [{"type": "text", "text": prompt}]
        if before_b64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{_mime(before_b64)};base64,{before_b64}",
                    "detail": "auto",
                },
            })
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{_mime(screenshot_b64)};base64,{screenshot_b64}",
                "detail": "auto",
            },
        })

        response = client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": content}],
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        logger.debug(f"Vision (api) raw response: {raw[:200]!r}")
        return raw

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_verdict(self, raw: str) -> "VisionVerdict":
        """
        Parse the JSON response from the vision LLM into a VisionVerdict.
        Falls back gracefully if the LLM outputs free text instead of JSON.
        """
        # Strip markdown fences
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

        try:
            data = json.loads(clean)
            matches = bool(data.get("matches_expected", False))
            confidence = float(data.get("confidence", 0.5 if matches else 0.2))
            confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]
            observation = str(data.get("observation", ""))
            reason = str(data.get("reason", ""))
            uncertain = VISION_CONFIDENCE_UNCERTAIN <= confidence < VISION_CONFIDENCE_PASS

            logger.info(
                f"Vision verdict: matches={matches}, confidence={confidence:.2f}, "
                f"uncertain={uncertain}, reason={reason!r}"
            )
            return VisionVerdict(
                matches=matches,
                confidence=confidence,
                observation=observation,
                reason=reason,
                uncertain=uncertain,
            )

        except (json.JSONDecodeError, ValueError):
            # LLM returned free text — parse the old-style yes/no as fallback
            lower = raw.lower().strip()
            matches = lower.startswith("yes")
            confidence = 0.6 if matches else 0.3
            logger.debug(f"Vision: could not parse JSON, fell back to text: {raw[:80]!r}")
            return VisionVerdict(
                matches=matches,
                confidence=confidence,
                observation=raw[:200],
                reason="(parsed from free-text response)",
                uncertain=(confidence < VISION_CONFIDENCE_PASS),
            )

    @staticmethod
    def _failure_verdict(reason: str) -> "VisionVerdict":
        return VisionVerdict(
            matches=False,
            confidence=0.0,
            observation="",
            reason=f"Vision assessment failed: {reason}",
        )


# ─── Capture helper ──────────────────────────────────────────────────────────

def _draw_marker(b64_str: str, coords: list) -> str:
    """Draw a red crosshair marker at the given (x,y) location to guide the Vision LLM."""
    try:
        from PIL import Image, ImageDraw

        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        draw = ImageDraw.Draw(img)

        x, y = coords[0], coords[1]
        r = 25
        # Draw a red circle outline
        draw.ellipse([(x - r, y - r), (x + r, y + r)], outline="red", width=6)
        # Draw the crosshair lines
        draw.line([(x - r*2, y), (x + r*2, y)], fill="red", width=4)
        draw.line([(x, y - r*2), (x, y + r*2)], fill="red", width=4)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to draw visual marker: {e}")
        return b64_str


def _get_vision_client() -> Optional[VisionClient]:
    """Return a VisionClient if a vision model is configured, else None."""
    try:
        from config.manager import get_value
        vision_model = get_value("model_config.vision_model")
        if not vision_model:
            return None
        return VisionClient(vision_model)
    except Exception:
        return None


# ─── Main Reflector ──────────────────────────────────────────────────────────

def reflect(
    tool_name: str,
    args: dict,
    executor_result,
    retry_count: int = 0,
    max_retries: int = 2,
    expected_result: Optional[str] = None,
    before_b64: Optional[str] = None,
) -> Reflection:
    """
    Determine whether a step succeeded.

    Phase 1 (always): success = no exception raised.
    Phase 2 (when vision model configured): additionally verifies visually
              using confidence-scored chain-of-thought reasoning.
    """
    result = executor_result

    # Hard block — never retry
    if result.error and "Blocked by safety" in result.error:
        return Reflection(
            status=ReflectionStatus.FAILURE,
            message=f"Action permanently blocked: {result.error}",
            should_retry=False,
        )

    # Confirmation required — let the loop handle it
    if result.error == "requires_confirmation":
        return Reflection(
            status=ReflectionStatus.FAILURE,
            message="Waiting for user confirmation.",
            should_retry=False,
        )

    # Execution-level failure
    if not result.success:
        if retry_count < max_retries:
            return Reflection(
                status=ReflectionStatus.RETRY,
                message=f"Step failed (attempt {retry_count + 1}/{max_retries + 1}): {result.error}",
                should_retry=True,
                retry_count=retry_count + 1,
            )
        return Reflection(
            status=ReflectionStatus.FAILURE,
            message=f"Step failed after {max_retries + 1} attempts: {result.error}",
            should_retry=False,
        )

    # ── Phase 2: Visual verification (informational only) ─────────────────────
    # NOTE: Phase 2 is advisory — it logs a vision assessment but does NOT
    # cause retries or failures. Step success is determined by Phase 1 (no exception).
    # The Critic in loop.py is the authoritative visual gatekeeper that handles
    # replanning. Retrying steps here caused open_url to re-navigate (Playwright
    # timeouts) and click tools to re-fire on wrong targets.
    vision_client = _get_vision_client() if tool_name not in SKIP_VISUAL_VERIFICATION_TOOLS else None

    if vision_client and expected_result:
        logger.info(f"Phase 2: Running vision assessment for step '{tool_name}' (advisory)")
        screenshot = capture_screen_b64()

        if screenshot:
            action_coords = (
                executor_result.result.get("action_coords")
                if executor_result and executor_result.result and isinstance(executor_result.result, dict)
                else None
            )
            if action_coords:
                screenshot = _draw_marker(screenshot, action_coords)

            verdict = vision_client.assess_with_confidence(screenshot, expected_result, before_b64)

            if verdict.matches and verdict.confidence >= VISION_CONFIDENCE_PASS:
                return Reflection(
                    status=ReflectionStatus.SUCCESS,
                    message=(
                        f"Step completed and visually confirmed (confidence={verdict.confidence:.0%}): "
                        f"{tool_name}. {verdict.observation}"
                    ),
                    should_retry=False,
                )
            elif verdict.matches and verdict.uncertain:
                # Uncertain but leaning positive — log and pass through
                logger.warning(
                    f"Phase 2 (advisory): vision uncertain for '{tool_name}' "
                    f"(confidence={verdict.confidence:.0%}) — {verdict.reason}. Critic will verify."
                )
            else:
                logger.warning(
                    f"Phase 2 (advisory): vision says no for '{tool_name}' "
                    f"(confidence={verdict.confidence:.0%}) — {verdict.reason}. Critic will verify."
                )

    # Phase 1 success (no exception raised by tool)
    return Reflection(
        status=ReflectionStatus.SUCCESS,
        message=f"Step completed: {tool_name}",
        should_retry=False,
    )
