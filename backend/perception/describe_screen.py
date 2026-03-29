"""
Screen description utility — asks the vision LLM to describe what's currently
visible on screen in natural language.

Used by:
  - StepAdvisor: adds visual context alongside UIA text
  - FixAgent: helps understand what went wrong visually
  - Debugging: gives human-readable screen state

Returns a structured dict; gracefully returns empty description if no vision
model is configured.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Prompt used for general screen description
_DESCRIBE_PROMPT = (
    "You are a Windows desktop observer. Look at this screenshot carefully.\n\n"
    "Respond with ONLY valid JSON (no markdown):\n"
    "{\n"
    '  "active_app": "<name of the foreground application or window title>",\n'
    '  "description": "<2-3 sentence natural language summary of what is visible>",\n'
    '  "visible_elements": ["<list of up to 8 key UI elements, text, or buttons visible>"]\n'
    "}\n\n"
    "Be specific and factual. Focus on what a human would notice first."
)


def describe_current_screen(quality: str = "low") -> dict:
    """
    Capture a screenshot and ask the vision LLM to describe what's visible.

    Args:
        quality: "low" (faster, JPEG) or "high" (PNG, more detail).

    Returns:
        {
            "active_app": str,
            "description": str,
            "visible_elements": List[str],
        }
        or {} if vision is not available/fails.
    """
    try:
        from config.manager import get_value
        vision_model = get_value("model_config.vision_model")
        if not vision_model:
            logger.debug("describe_current_screen: no vision model configured.")
            return {}

        from perception.screenshot import capture_screen_b64
        screenshot_b64 = capture_screen_b64(quality=quality)
        if not screenshot_b64:
            return {}

        from agent.reflector import VisionClient
        client = VisionClient(vision_model)

        raw = _call_vision_describe(client, screenshot_b64)
        return _parse_describe_response(raw)

    except Exception as e:
        logger.warning(f"describe_current_screen failed: {e}")
        return {}


def describe_screen_as_text(quality: str = "low") -> str:
    """
    Convenience wrapper that returns the description as a plain text string
    suitable for injecting into LLM prompts.

    Returns empty string if vision is unavailable.
    """
    result = describe_current_screen(quality=quality)
    if not result:
        return ""
    parts = []
    if result.get("active_app"):
        parts.append(f"Active app: {result['active_app']}")
    if result.get("description"):
        parts.append(result["description"])
    if result.get("visible_elements"):
        parts.append("Visible: " + ", ".join(result["visible_elements"][:6]))
    return " | ".join(parts)


def _call_vision_describe(client, screenshot_b64: str) -> str:
    """
    Call the VisionClient to get a description.
    We call the backend directly rather than going through assess() since we need
    the raw text response, not a boolean.
    """
    try:
        if client._backend == "ollama":
            return _describe_ollama(client, screenshot_b64)
        elif client._backend in ("api", "openai", "anthropic", "groq"):
            return _describe_api(client, screenshot_b64)
    except Exception as e:
        logger.warning(f"Vision describe backend call failed: {e}")
    return ""


def _describe_ollama(client, screenshot_b64: str) -> str:
    import httpx
    from config.manager import get_value

    base_url = get_value("model_config.base_url", "http://localhost:11434")
    payload = {
        "model": client._model_name,
        "prompt": _DESCRIBE_PROMPT,
        "images": [screenshot_b64],
        "stream": False,
    }
    resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=45)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _describe_api(client, screenshot_b64: str) -> str:
    from openai import OpenAI
    from config.manager import get_value

    api_key = get_value("model_config.api_key") or ""
    base_url = get_value("model_config.base_url")
    client_kwargs = {"api_key": api_key}
    if base_url and client._backend not in ("openai",):
        client_kwargs["base_url"] = base_url

    oa_client = OpenAI(**client_kwargs)
    content = [
        {"type": "text", "text": _DESCRIBE_PROMPT},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "auto"},
        },
    ]
    response = oa_client.chat.completions.create(
        model=client._model_name,
        messages=[{"role": "user", "content": content}],
        max_tokens=256,
    )
    return response.choices[0].message.content.strip()


def _parse_describe_response(raw: str) -> dict:
    """Parse the JSON response from the vision LLM, with fallbacks."""
    import json
    import re

    if not raw:
        return {}

    # Strip markdown fences if present
    clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    try:
        data = json.loads(clean)
        return {
            "active_app": str(data.get("active_app", "")),
            "description": str(data.get("description", "")),
            "visible_elements": list(data.get("visible_elements", [])),
        }
    except json.JSONDecodeError:
        # LLM returned free text — use it as-is for description
        logger.debug(f"describe_screen: could not parse JSON, using raw text")
        return {"active_app": "", "description": raw[:300], "visible_elements": []}
