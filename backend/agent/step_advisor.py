"""
Step Advisor — observes the live screen state after each step and decides
whether the NEXT planned step is still valid, needs argument adaption,
needs a full replan, is already done, or should be skipped.

Improvements over v1:
  - Injects a vision LLM screen description alongside UIA text when a vision
    model is configured — bridges the gap between raw accessibility names and
    actual on-screen appearance.
  - get_screen_context_for_advisor() unifies UIA text + vision description
    into a single context string for the LLM prompt.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


ADVISOR_PROMPT = """You are Oliv, an autonomous Windows desktop agent.

You just executed a step. Observe the current screen state and decide what to do next.

ORIGINAL GOAL: {goal}
STEP JUST EXECUTED: {last_step_tool}({last_step_args})
EXPECTED OUTCOME WAS: {last_step_reason}
CRITIC VERDICT: {critic_verdict}
REMAINING PLANNED STEPS:
{remaining_steps}
CURRENT SCREEN STATE:
{screen_text}

SOURCE RELIABILITY (read before deciding):
- The ACTIVE/FOREGROUND window name is shown first in the screen state as "[ACTIVE WINDOW]".
- Lines starting with [UIA] include ALL open windows — background apps like Discord, Chrome, etc.
  will appear even if they are NOT the current window. Do NOT conclude an app is active
  just because its name appears in UIA — use [ACTIVE WINDOW] to determine what is in focus.
- Lines starting with [VISION HINT] come from an AI image model and CAN HALLUCINATE.
- If UIA shows the expected app/element IS present in the active window, trust it.
- NEVER choose "replan" because a background/inactive app appears in the UIA data.

Decide ONE of these actions for the NEXT step:
1. "proceed"  — next planned step is still correct, execute it as-is
2. "adapt"    — next planned step is roughly right but its arguments need updating (provide new_args)
3. "replan"   — the screen situation has changed enough to warrant a complete new plan
4. "done"     — the overall goal is already fully achieved, no further steps needed
5. "skip"     — the next step is no longer needed; skip it and proceed to the one after

IMPORTANT:
- Prefer "proceed" unless you have a CLEAR, STRONG reason to change.
- Only choose "done" if the original goal is visibly achieved on screen right now.
- Only choose "replan" if UIA confirms remaining steps are clearly wrong/impossible.
- For "adapt", provide only the keys that need to change in new_args.

Respond ONLY with valid JSON (no markdown):
{{
  "decision": "proceed|adapt|replan|skip|done",
  "reason": "<one concise sentence>",
  "new_args": {{}}
}}
"""


@dataclass
class AdvisorResult:
    decision: str          # one of: proceed, adapt, replan, skip, done
    reason: str
    new_args: dict = field(default_factory=dict)


def advise_next_step(
    goal: str,
    last_step: dict,
    critic_verdict: str,
    remaining_steps: list[dict],
    screen_text: str,
) -> AdvisorResult:
    """
    Ask the LLM what to do next, given live screen context.

    Parameters
    ----------
    goal : str
        The original user goal.
    last_step : dict
        The step that just ran: {"tool": ..., "args": ..., "reason": ...}
    critic_verdict : str
        Human-readable critic outcome (e.g. "passed" or critic reason string).
    remaining_steps : list[dict]
        Remaining planned steps (each: {"tool": ..., "reason": ...}).
    screen_text : str
        Combined screen context from get_screen_context_for_advisor().

    Returns
    -------
    AdvisorResult with decision + reason + optional new_args.
    """
    from llm.router import get_router

    remaining_summary = json.dumps(
        [{"tool": s.get("tool"), "reason": s.get("reason")} for s in remaining_steps[:6]],
        indent=2,
    )

    prompt = ADVISOR_PROMPT.format(
        goal=goal,
        last_step_tool=last_step.get("tool", ""),
        last_step_args=json.dumps(last_step.get("args", {})),
        last_step_reason=last_step.get("reason", ""),
        critic_verdict=critic_verdict,
        remaining_steps=remaining_summary,
        screen_text=screen_text[:1000],
    )

    try:
        router = get_router()
        raw = router.generate_response(
            prompt=prompt,
            system_prompt="You are a precise autonomous decision-making agent. Output only valid JSON.",
            temperature=0.1,
            max_tokens=256,
            task_type="advisor",
        )
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        data = json.loads(clean)

        decision = data.get("decision", "proceed").lower()
        if decision not in {"proceed", "adapt", "replan", "skip", "done"}:
            decision = "proceed"

        return AdvisorResult(
            decision=decision,
            reason=data.get("reason", ""),
            new_args=data.get("new_args", {}),
        )

    except Exception as e:
        logger.warning(f"StepAdvisor failed ({e}) — defaulting to 'proceed'")
        return AdvisorResult(decision="proceed", reason="Advisor unavailable.")


def get_screen_text_for_advisor() -> str:
    """
    Backward-compatible alias for get_screen_context_for_advisor().
    Returns UIA text only (no vision). Used by parts of the loop that
    don't need the heavier vision description.
    """
    return _get_uia_text()


def get_screen_context_for_advisor() -> str:
    """
    Build a rich screen context string for the StepAdvisor by combining:
      1. Windows UI Automation text (fast, authoritative ground truth)
      2. Vision LLM description (when a vision model is configured)

    Vision is clearly labelled as a low-confidence hint so the LLM advisor
    does not override strong UIA evidence with a hallucinated vision claim.
    Falls back to UIA-only if vision is unavailable or fails.
    """
    uia_text = _get_uia_text()

    # Try to get vision description — always secondary to UIA
    try:
        from perception.describe_screen import describe_screen_as_text
        vision_text = describe_screen_as_text(quality="low")
        if vision_text:
            return (
                f"[UIA - AUTHORITATIVE] {uia_text[:600]}\n"
                f"[VISION HINT - may hallucinate, lower confidence] {vision_text}"
            )
    except Exception as e:
        logger.debug(f"Vision description skipped: {e}")

    return uia_text


def _get_uia_text() -> str:
    """
    Get a focused text snapshot of the FOREGROUND window + limited desktop context.
    Foreground window is labeled clearly so the advisor knows what is actually active.
    Falls back to full desktop walk if foreground detection fails.
    """
    try:
        import uiautomation as auto
        auto.SetGlobalSearchTimeout(1.5)

        texts: list[str] = []

        # ── Step 1: foreground window (what the user sees) ─────────────────
        fg = auto.GetForegroundControl()
        fg_name = ""
        if fg:
            try:
                fg_name = (fg.Name or fg.ClassName or "").strip()
            except Exception:
                fg_name = ""

            # Walk only the foreground window for the primary context
            fg_texts: list[str] = []
            for ctrl, _ in auto.WalkTree(fg, includeTop=True, maxDepth=5):
                try:
                    name = (ctrl.Name or "").strip()
                    if name and len(name) > 1:
                        fg_texts.append(name)
                        if len(fg_texts) >= 80:
                            break
                except Exception:
                    continue

            if fg_texts:
                prefix = f"[ACTIVE WINDOW: {fg_name}] " if fg_name else "[ACTIVE WINDOW] "
                texts.append(prefix + " | ".join(fg_texts))

        # ── Step 2: top-level window names for broader context ─────────────
        root = auto.GetRootControl()
        top_names: list[str] = []
        for ctrl in root.GetChildren():
            try:
                name = (ctrl.Name or "").strip()
                if name and len(name) > 1 and name != fg_name:
                    top_names.append(name)
                    if len(top_names) >= 10:
                        break
            except Exception:
                continue
        if top_names:
            texts.append("[OTHER OPEN WINDOWS (background, not active)] " + " | ".join(top_names))

        return "\n".join(texts) if texts else ""

    except Exception as e:
        logger.debug(f"get_screen_text_for_advisor: {e}")
        return ""
