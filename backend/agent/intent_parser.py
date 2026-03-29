"""
Intent Parser — converts vague user input into a structured goal object.
This runs BEFORE the planner to give it clean, structured input.

Example:
  Input:  "can you open youtube and search for cat videos"
  Output: {
    "intent": "browser_task",
    "goal": "Search for 'cat videos' on YouTube",
    "entities": {"site": "youtube.com", "query": "cat videos"},
    "suggested_tools": ["open_url", "browser_type"]
  }
"""
import json
import logging
import re
from typing import Optional

from llm.router import get_router
from tools.registry import list_tools

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """You are Oliv, an intent parser for an AI desktop assistant.

Your job is to convert a user's natural language request into a structured JSON object.

AVAILABLE TOOLS:
{tool_list}

OUTPUT FORMAT (strict JSON, no markdown):
{{
  "intent": "<short snake_case description of what the user wants>",
  "goal": "<clear, specific one-sentence goal>",
  "entities": {{<key: value pairs extracted from the request>}},
  "suggested_tools": [<list of tool names that will likely be needed>]
}}

RULES:
- Output ONLY valid JSON. No explanation, no markdown, no code fences.
- Be specific. "open YouTube and search cat videos" → goal: "Search for 'cat videos' on YouTube"
- suggested_tools must only contain tool names from the AVAILABLE TOOLS list.
- If unsure of a tool, leave suggested_tools empty.
"""


def parse_intent(user_input: str) -> dict:
    """
    Parse a user's natural language request into a structured intent.
    Falls back to a simple wrapper if LLM fails.
    """
    router = get_router()
    tool_list = "\n".join(
        f"- {t['name']}: {t['description']}" for t in list_tools()
    )
    system_prompt = INTENT_SYSTEM_PROMPT.format(tool_list=tool_list)

    for attempt in range(3):
        try:
            raw = router.generate_response(
                prompt=user_input,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=512,
                task_type="intent_parsing",
            )
            # Strip any accidental markdown fences
            clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
            intent = json.loads(clean)
            # Validate required fields
            intent.setdefault("intent", "unknown")
            intent.setdefault("goal", user_input)
            intent.setdefault("entities", {})
            intent.setdefault("suggested_tools", [])

            # Strip any hallucinated tool names the LLM invented
            valid_tool_names = {t["name"] for t in list_tools()}
            invalid_tools = [t for t in intent["suggested_tools"] if t not in valid_tool_names]
            if invalid_tools:
                logger.warning(f"Intent parser suggested unknown tools (removed): {invalid_tools}")
            intent["suggested_tools"] = [
                t for t in intent["suggested_tools"] if t in valid_tool_names
            ]

            logger.info(f"Intent parsed: {intent['intent']} — {intent['goal']}")
            return intent
        except Exception as e:
            logger.warning(f"Intent parsing attempt {attempt+1} failed: {e}")
            user_input = (
                f"{user_input}\n\n"
                f"Attempt {attempt + 1} failed with error: {e}\n"
                f"Return ONLY valid JSON matching the required format. No explanation."
            )

    # Fallback: return a minimal wrapper
    logger.warning("Intent parser failed twice; using raw fallback.")
    return {
        "intent": "general_task",
        "goal": user_input,
        "entities": {},
        "suggested_tools": [],
    }
