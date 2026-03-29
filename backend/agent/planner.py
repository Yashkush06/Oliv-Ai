"""
Planner — takes a structured intent and produces a validated list of steps.
Output is Pydantic-validated. Invalid JSON from LLM triggers retry (max 2x).
"""
import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, ValidationError

from llm.router import get_router
from tools.registry import list_tools, get_tool

logger = logging.getLogger(__name__)


class Step(BaseModel):
    tool: str
    args: dict
    reason: str


class Plan(BaseModel):
    steps: List[Step]
    is_conversational: bool = False


PLANNER_SYSTEM_PROMPT = """You are Oliv, an AI agent that plans tasks on a Windows computer.

Given a user goal, produce a step-by-step execution plan.

AVAILABLE TOOLS:
{tool_list}

STRICT OUTPUT FORMAT (valid JSON only, no markdown):
{{
  "steps": [
    {{
      "tool": "<tool_name>",
      "args": {{<tool arguments as key-value pairs>}},
      "reason": "<a short STATE DESCRIPTION of what should be visually verified on screen after executing this step (e.g. 'The search bar contains Yash'). Do NOT write an action or instruction.>"
    }}
  ]
}}

TOOL PREFERENCE ORDER (always use the highest-priority option that applies):
1. open_app("app_name")   — ALWAYS use this to launch applications. Never manually click Start or use Win+S.
2. click_text("Label")    — PREFERRED for ANY button, link, or UI element with visible text
3. wait_for_text("text")  — use ONLY to confirm a dialog, window title, or page that you are CERTAIN renders as plain readable text (e.g., "Notepad", "Google Chrome"). See WAIT_FOR_TEXT RULES below.
4. click(x, y)            — LAST RESORT only. Never hardcode window-relative pixel coords;
                           if you must use x/y, use rough screen-center values only.

FORBIDDEN ACTIONS (the agent CANNOT see these in screenshots — they will cause failures):
- NEVER click the Start button, taskbar, or system tray
- NEVER use hotkey(["win","s"]) or hotkey(["win"]) to open Start/Search
- NEVER plan steps that interact with the taskbar or notification area
- To launch apps, ALWAYS use open_app("app_name") instead

RULES:
- Output ONLY valid JSON matching the format above. No explanation outside JSON.
- Use ONLY tool names from AVAILABLE TOOLS. Never invent tools.
- Break the task into the minimum number of steps needed.
- NEVER generate consecutive duplicate steps (e.g., do not plan `type_text` twice in a row for the same input).
- Each step must have all required args for the tool.
- Only use wait_for_text to confirm an app loaded if you are absolutely certain of the EXACT visible text. If unsure, do not use wait_for_text; the Critic's vision verification will confirm the app is open.

WAIT_FOR_TEXT RULES (read carefully before using it):
  SAFE to use for: window/dialog titles ("Notepad", "Settings"), browser page headings, chat app names.
  NEVER use for:
    - Navigation buttons or icons (Search, Home, Library, Browse, Play, Pause, Skip — these are rendered as SVG icons in media apps and will NEVER be found by text search)
    - ANY element inside Spotify, YouTube Music, Netflix, or similar media/streaming apps
    - Sidebar items, tab labels, or toolbar icons in Electron/WebView2 apps
    - Any element where you are not 100% certain it appears as plain OCR-readable text
  If you need to navigate within Spotify or similar apps: use hotkey("ctrl+l") to open search, or click_text on the actual song/artist/playlist name text instead.
- If the task is a conversation (not an action), return: {{"steps": []}}
- For searching on websites like YouTube or Google, formulate the search URL directly (e.g., "https://www.youtube.com/results?search_query=...") in the open_url step instead of navigating to the homepage and typing in the search bar. This prevents UI timeouts.
"""


def _format_tool_list(tools: list) -> str:
    """
    Format tools with full arg descriptions so the LLM knows which args to fill.
    """
    lines = []
    for t in tools:
        param_strs = []
        for p_name, p_info in t["parameters"].items():
            p_type = p_info.get("type", "string")
            p_desc = p_info.get("description", "")
            param_strs.append(f'{p_name} ({p_type}): "{p_desc}"')
        params_joined = ", ".join(param_strs) if param_strs else "no parameters"
        lines.append(f'- {t["name"]}: {t["description"]}\n    Args: {params_joined}')
    return "\n".join(lines)


def _validate_plan_args(plan: "Plan") -> None:
    """
    Ensure each step has all required args (those without 'default' in the schema).
    Raises ValueError on first violation — triggers a planner retry.
    """
    for step in plan.steps:
        tool_def = get_tool(step.tool)
        if not tool_def:
            available = [t["name"] for t in list_tools()]
            raise ValueError(
                f"Unknown tool '{step.tool}' in plan. "
                f"Available tools are: {available}"
            )
        for param_name, param_info in tool_def.parameters.items():
            if "default" not in param_info and param_name not in step.args:
                raise ValueError(
                    f"Step '{step.tool}' is missing required arg '{param_name}'. "
                    f"Got args: {step.args}"
                )


def _dedup_consecutive_steps(plan: "Plan") -> "Plan":
    """Remove back-to-back identical tool+args steps (LLM sometimes duplicates)."""
    if not plan.steps:
        return plan
    deduped = [plan.steps[0]]
    for step in plan.steps[1:]:
        prev = deduped[-1]
        if step.tool == prev.tool and step.args == prev.args:
            logger.warning(f"Removed duplicate consecutive step: {step.tool}({step.args})")
            continue
        deduped.append(step)
    return Plan(steps=deduped)


def plan_task(intent: dict, context: Optional[str] = None, screen_context: Optional[str] = None) -> Plan:
    """
    Convert an intent object into a validated execution plan.
    Retries up to 2 times on invalid JSON or schema violations.
    """
    router = get_router()
    tool_list = _format_tool_list(list_tools())
    system_prompt = PLANNER_SYSTEM_PROMPT.format(tool_list=tool_list)

    goal = intent.get("goal", "").strip()
    if not goal:
        raise ValueError("Intent must contain a non-empty 'goal' field.")
    suggested = intent.get("suggested_tools", [])
    entities = intent.get("entities", {})

    from memory.store import search_memories
    good_past_plans = search_memories(goal, memory_type="task")
    relevant_examples = [p for p in good_past_plans if p.get("feedback") == "thumbs_up"]

    prompt_parts = [f"Goal: {goal}"]
    if suggested:
        prompt_parts.append(f"Suggested tools: {', '.join(suggested)}")
    if entities:
        prompt_parts.append(f"Extracted entities: {json.dumps(entities)}")
    if context:
        prompt_parts.append(f"Current state: {context}")
    if screen_context:
        prompt_parts.append(f"CURRENT SCREEN (live OCR/UI text): {screen_context[:600]}")
    
    if relevant_examples:
        prompt_parts.append("\nHere are similar tasks you completed successfully in the past. Use these step sequences as strong hints for your plan:")
        for ex in relevant_examples[:2]:  # Use up to 2 most recent relevant good examples
            steps_str = json.dumps([{"tool": s["tool"], "args": s["args"]} for s in ex.get("plan_steps", [])])
            prompt_parts.append(f"Past Goal: {ex.get('goal')}\nSuccessful Steps: {steps_str}")


    prompt = "\n".join(prompt_parts)

    last_error = None
    for attempt in range(3):
        try:
            raw = router.generate_response(
                prompt=prompt if attempt == 0 else (
                    f"{prompt}\n\n"
                    f"Attempt {attempt} failed with the following error:\n{last_error}\n\n"
                    f"Fix the issue and return ONLY valid JSON matching the required schema. No explanation."
                ),
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=1024,
                task_type="step_planning",
            )
            clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
            data = json.loads(clean)
            if data.get("steps") == [] or data == {"steps": []}:
                logger.info("Planner identified goal as conversational — returning empty plan.")
                return Plan(steps=[], is_conversational=True)
            plan = Plan(**data)

            # Validate tool names and required arguments
            _validate_plan_args(plan)

            # Remove consecutive duplicate steps
            plan = _dedup_consecutive_steps(plan)

            logger.info(
                f"Plan generated via {getattr(router, 'active_model', 'unknown model')}: "
                f"{len(plan.steps)} steps"
            )
            return plan

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = e
            logger.warning(f"Planner attempt {attempt+1} failed: {e}")

    raise RuntimeError(f"Planner failed after 3 attempts. Last error: {last_error}")
