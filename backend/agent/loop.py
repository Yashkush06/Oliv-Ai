"""
Agent loop — the core orchestration engine.

Flow: intent parse → plan → (safety → execute → reflect → critic → advise) × N → done

Design goals
────────────
* **Never get stuck** — no hard `break` on step failure. Every failure is
  either recovered via FixAgent / replan, or skipped with a logged warning.
* **Think after every step** — the StepAdvisor reads the live screen and
  decides whether to proceed, adapt args, skip, replan, or declare done.
* **Screen-aware planning** — live OCR of the desktop is injected into every
  plan/replan prompt so the LLM knows exactly what is visible.
* **Single source of truth** — skip-sets, timeouts, and iteration caps all
  live in agent.constants to prevent future drift.

All events are emitted as structured WebSocket messages via an event_emitter
callback so the frontend can render real-time progress.
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from agent.constants import (
    SKIP_VISUAL_VERIFICATION_TOOLS,
    MAX_TASK_REPLANS,
    MAX_FIX_ATTEMPTS,
    CRITIC_TIMEOUT_SECONDS,
)
from agent.intent_parser import parse_intent
from agent.planner import plan_task
from agent.executor import run_step, ExecutorResult
from agent.reflector import ReflectionStatus, reflect
from agent.critic import Critic, CriticResult
from agent.step_advisor import advise_next_step, get_screen_text_for_advisor, get_screen_context_for_advisor
from memory.store import add_memory
from perception.screenshot import capture_screen_b64

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 50          # hard cap on total steps (including injected fixes)
MAX_STEP_RETRIES = 2         # retries before handing off to FixAgent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_event(
    event_type: str,
    task_id: str,
    step: int = 0,
    total_steps: int = 0,
    tool: str = "",
    args: dict = None,
    status: str = "pending",
    message: str = "",
    data: Any = None,
) -> dict:
    """Create a structured WebSocket event."""
    return {
        "type": event_type,
        "task_id": task_id,
        "step": step,
        "total_steps": total_steps,
        "tool": tool,
        "args": args or {},
        "status": status,
        "message": message,
        "data": data,
        "timestamp": _now(),
    }


# ─── Global task state ────────────────────────────────────────────────────────
_current_task = {"running": False, "task_id": None, "should_stop": False}


def acquire_lock(task_id: str) -> bool:
    """Synchronously acquire the task lock before scheduling background work."""
    if _current_task["running"]:
        return False
    _current_task.update({"running": True, "task_id": task_id, "should_stop": False})
    return True


# ─── Disambiguation arg-key resolution ───────────────────────────────────────

_DISAMBIGUATION_ARG_KEYS = ("text", "query", "label", "value", "url", "name")


def _patch_step_with_clarification(step_args: dict, clarification: str) -> dict:
    """
    Apply a user disambiguation answer to the correct step arg key.
    Tries common key names in priority order; falls back to 'text'.
    """
    for key in _DISAMBIGUATION_ARG_KEYS:
        if key in step_args:
            step_args[key] = clarification
            return step_args
    # Absolute fallback
    step_args["text"] = clarification
    return step_args


# ─── FixAgent — generate one alternative step on failure ─────────────────────

_FIX_PROMPT = """You are Oliv, an autonomous Windows agent.

A planned step just failed. Generate exactly ONE alternative step to achieve the same goal.

ORIGINAL GOAL: {goal}
FAILED STEP: {failed_tool}({failed_args})
FAILURE REASON: {error}
CURRENT SCREEN OCR: {screen_text}

AVAILABLE TOOLS:
{tool_list}

Respond ONLY with valid JSON (no markdown):
{{
  "tool": "<tool_name>",
  "args": {{<key: value pairs>}},
  "reason": "<what this alternative achieves>"
}}

If no fix is possible, respond: {{"tool": "", "args": {{}}, "reason": "no fix available"}}
"""


async def _fix_step(
    goal: str,
    failed_tool: str,
    failed_args: dict,
    error: str,
    screen_text: str,
) -> Optional[dict]:
    """
    Ask the LLM for one alternative step when the planned step has failed.
    Returns a Step-compatible dict or None if no fix is available.
    """
    try:
        from llm.router import get_router
        from tools.registry import list_tools
        from agent.planner import _format_tool_list

        tool_list = _format_tool_list(list_tools())
        router = get_router()
        prompt = _FIX_PROMPT.format(
            goal=goal,
            failed_tool=failed_tool,
            failed_args=json.dumps(failed_args),
            error=error[:300],
            screen_text=screen_text[:600],
            tool_list=tool_list,
        )
        raw = await router.agenerate_response(
            prompt=prompt,
            system_prompt="You are a precise autonomous agent. Output only valid JSON.",
            temperature=0.2,
            max_tokens=256,
            task_type="fix_agent",
        )
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        data = json.loads(clean)
        if not data.get("tool"):
            return None
        return data
    except Exception as e:
        logger.warning(f"FixAgent failed: {e}")
        return None


# ─── Main task runner ─────────────────────────────────────────────────────────

async def run_task(
    user_goal: str,
    emit: Callable[[dict], None],
    confirm_queue: Optional[asyncio.Queue] = None,
    answer_queue: Optional[asyncio.Queue] = None,
    task_id: Optional[str] = None,
) -> dict:
    """
    Run a full agent task.
    - emit() is called with each structured event dict (WebSocket fan-out)
    - confirm_queue is used for Smart Mode confirmations
    - answer_queue is used for disambiguation answers
    """
    task_id = task_id or str(uuid.uuid4())[:8]
    _current_task.update({"running": True, "task_id": task_id, "should_stop": False})

    critic = Critic()

    try:
        # ── 1. Parse intent ────────────────────────────────────────────────
        emit(_make_event("log", task_id, message=f"Parsing intent: {user_goal[:80]}..."))
        intent = await asyncio.to_thread(parse_intent, user_goal)
        emit(_make_event("log", task_id, message=f"Intent: {intent['goal']}", data=intent))

        # ── 2. Plan (with live screen context) ────────────────────────────
        emit(_make_event("log", task_id, message="Capturing screen context for planning..."))
        screen_context = await asyncio.to_thread(get_screen_text_for_advisor)

        emit(_make_event("log", task_id, message="Generating execution plan..."))
        try:
            plan = await asyncio.to_thread(plan_task, intent, None, screen_context)
        except RuntimeError as e:
            emit(_make_event("task_done", task_id, status="failure", message=str(e)))
            return {"success": False, "error": str(e)}

        # ── 2a. Conversational response (no actions needed) ───────────────
        if plan.is_conversational:
            emit(_make_event(
                "task_done", task_id, status="conversational",
                message="This was a conversational request — no desktop actions taken.",
            ))
            return {"success": True, "steps_executed": 0, "conversational": True}

        total = len(plan.steps)
        if total == 0:
            emit(_make_event("task_done", task_id, status="success", message="No actions needed."))
            return {"success": True, "steps_executed": 0}

        emit(_make_event("log", task_id, total_steps=total,
                         message=f"Plan ready: {total} step(s)"))

        # ── 2b. Plan confirmation ──────────────────────────────────────────
        steps_data = [{"tool": s.tool, "args": s.args, "reason": s.reason} for s in plan.steps]
        emit(_make_event(
            "plan_confirm", task_id, total_steps=total,
            message=f"Please review the {total}-step plan before execution.",
            data={"steps": steps_data},
        ))
        if confirm_queue:
            confirmed = await confirm_queue.get()
            if not confirmed:
                emit(_make_event("task_done", task_id, status="cancelled",
                                 message="Task cancelled by user before execution."))
                return {"success": False, "error": "Task cancelled by user."}

        # ── 3. Execute each step ───────────────────────────────────────────
        results: list[dict] = []
        retry_count = 0
        fix_attempts = 0
        # Global replan budget for the ENTIRE task (not reset on step success).
        task_replan_count = 0

        i = 0
        while i < len(plan.steps):
            if i >= MAX_ITERATIONS:
                emit(_make_event("log", task_id, message=f"Reached max iterations ({MAX_ITERATIONS}). Stopping."))
                break

            step = plan.steps[i]
            step_num = i + 1

            if _current_task["should_stop"]:
                emit(_make_event("task_done", task_id, step=step_num, total_steps=len(plan.steps),
                                 status="stopped", message="Task stopped by user."))
                break

            emit(_make_event(
                "step_start", task_id, step=step_num, total_steps=len(plan.steps),
                tool=step.tool, args=step.args, status="pending",
                message=step.reason,
            ))

            # Capture 'Before' screenshot for state diffing (fix #6: use capture_screen_b64)
            before_b64 = await asyncio.to_thread(capture_screen_b64)

            # Execute — executor owns the 30-second timeout (no outer wait_for, fix #1)
            result = await run_step(step.tool, step.args)

            # ── Disambiguation prompt ─────────────────────────────────────
            if not result.success and result.error and "Found multiple distinct matches" in result.error:
                emit(_make_event(
                    "prompt_user", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, args=step.args, status="pending",
                    message=f"Ambiguity detected: {result.error}",
                ))
                if answer_queue is not None:
                    user_clarification = await answer_queue.get()
                    emit(_make_event("log", task_id, message=f"User clarified: {user_clarification}"))
                    # Fix #7: patch whichever arg key the tool actually uses
                    step.args = _patch_step_with_clarification(step.args, user_clarification)
                    result = await run_step(step.tool, step.args)

            # ── Confirmation requirement ──────────────────────────────────
            if result.error == "requires_confirmation":
                emit(_make_event(
                    "ask_user", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, args=step.args, status="pending",
                    message=f"Confirm action: {step.reason}",
                ))
                if confirm_queue is not None:
                    confirmed = await confirm_queue.get()
                    if not confirmed:
                        emit(_make_event("step_done", task_id, step=step_num,
                                         total_steps=len(plan.steps),
                                         tool=step.tool, status="skipped",
                                         message="User denied this action."))
                        i += 1
                        continue
                    result = await run_step(step.tool, step.args, bypass_safety=True)

            # ── UI settle ─────────────────────────────────────────────────
            await asyncio.sleep(1.5)

            # ── Phase 1: Code-level reflection ────────────────────────────
            reflection = reflect(
                step.tool, step.args, result,
                retry_count,
                expected_result=step.reason,
                before_b64=before_b64,
            )
            step_passed = True

            # ── Handling Reflection Outcomes ──
            if reflection.status == ReflectionStatus.FAILURE:
                if reflection.should_retry and retry_count < MAX_STEP_RETRIES:
                    # Retry needed
                    retry_count = reflection.retry_count
                    emit(_make_event(
                        "step_error", task_id, step=step_num, total_steps=len(plan.steps),
                        tool=step.tool, status="retry",
                        message=reflection.message,
                    ))
                    await asyncio.sleep(0.5)
                    continue  # retry same step
                
                # Else: Permanent block (safety) or retries exhausted
                emit(_make_event(
                    "step_error", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, status="failure",
                    message=reflection.message,
                    data={"error": result.error},
                ))
                results.append({"step": step_num, "tool": step.tool, "success": False})
                step_passed = False
                
                fix_inserted = False
                if fix_attempts < MAX_FIX_ATTEMPTS and "Blocked by safety" not in (result.error or ""):
                    screen_text = await asyncio.to_thread(get_screen_text_for_advisor)
                    fix_data = await _fix_step(
                        goal=intent["goal"],
                        failed_tool=step.tool,
                        failed_args=step.args,
                        error=result.error or reflection.message,
                        screen_text=screen_text,
                    )
                    if fix_data and fix_data.get("tool"):
                        from agent.planner import Step as PlanStep
                        fix_step_obj = PlanStep(**fix_data)
                        plan.steps.insert(i + 1, fix_step_obj)
                        emit(_make_event("log", task_id, step=step_num,
                                          message=f"FixAgent: inserting alternative → {fix_data['tool']}({fix_data['args']})"))
                        fix_attempts += 1
                        fix_inserted = True
                
                retry_count = 0
                if fix_inserted:
                    i += 1
                    continue
                # If no fix inserted, step_passed is False and we fall through to StepAdvisor

            # ── Phase 2: Critic visual verification ───────────────────────
            skip_critic = step.tool in SKIP_VISUAL_VERIFICATION_TOOLS
            critic_result: Optional[CriticResult] = None
            if step_passed and not skip_critic and step.reason:
                emit(_make_event(
                    "log", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, message=f"Critic verifying: '{step.reason[:60]}'...",
                ))
                # Pass before_b64 so Critic can do before/after diff analysis
                critic_result = await critic.wait_and_verify(
                    step.reason,
                    timeout=CRITIC_TIMEOUT_SECONDS,
                    before_b64=before_b64,
                )

            if critic_result:
                screenshot_str = (critic_result.screenshot_b64[:200] + "..."
                                  if critic_result.screenshot_b64 else None)
                emit(_make_event(
                    "critic_result", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool,
                    status="passed" if critic_result.passed else "failed",
                    message=critic_result.reason,
                    data={
                        "screenshot": screenshot_str,
                        "confidence": getattr(critic_result, "confidence", None),
                        "observation": getattr(critic_result, "observation", ""),
                    },
                ))

            # ── Critic failed → targeted replan (fix #5: no break on exhaustion) ──
            if step_passed and critic_result and not critic_result.passed:
                step_passed = False
                replan_inserted = False
                if task_replan_count < MAX_TASK_REPLANS:
                    task_replan_count += 1
                    failure_context = (
                        f"Step '{step.tool}' executed but Critic says the expected outcome "
                        f"'{step.reason}' was NOT confirmed on screen. "
                        f"Critic reason: {critic_result.reason}. "
                        f"Please re-plan the remaining steps with an alternative approach."
                    )
                    emit(_make_event(
                        "plan_replan", task_id, step=step_num, total_steps=len(plan.steps),
                        tool=step.tool, status="replanning",
                        message=f"Critic failed. Re-planning (task attempt {task_replan_count}/{MAX_TASK_REPLANS})...",
                    ))
                    try:
                        screen_ctx = await asyncio.to_thread(get_screen_text_for_advisor)
                        new_plan = await asyncio.to_thread(plan_task, intent, failure_context, screen_ctx)
                        if new_plan.steps:
                            plan.steps = plan.steps[:i] + new_plan.steps
                            logger.info(f"Re-planned: {len(new_plan.steps)} new step(s) from position {i+1}")
                            replan_inserted = True
                            retry_count = 0
                            await asyncio.sleep(0.3)
                    except RuntimeError as e:
                        logger.warning(f"Re-plan failed: {e}")
                
                if replan_inserted:
                    continue  # Replace current step, restart loop on new plan step i

                # Replan budget exhausted or failed — log and skip this step (fix #5: no break)
                emit(_make_event(
                    "step_error", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, status="critic_failed",
                    message=f"Critic unconfirmed after {task_replan_count} replan(s) — skipping step.",
                    data={"critic_reason": critic_result.reason},
                ))
                results.append({"step": step_num, "tool": step.tool, "success": False})
                retry_count = 0
                # Fall through to StepAdvisor

            # ── SUCCESS ───────────────────────────────────────────────────
            if step_passed:
                verified_msg = (
                    f"Step completed and visually verified: {step.tool}"
                    if (critic_result and critic_result.passed)
                    else reflection.message
                )
                emit(_make_event(
                    "step_done", task_id, step=step_num, total_steps=len(plan.steps),
                    tool=step.tool, args=step.args, status="success",
                    message=verified_msg, data=result.result,
                ))
                results.append({"step": step_num, "tool": step.tool, "success": True})
                retry_count = 0
                fix_attempts = 0  # reset fix budget on step success

            # ── StepAdvisor: think about the next step ────────────────────
            if i + 1 < len(plan.steps):
                # Use vision-enriched context when a vision model is configured
                screen_text = await asyncio.to_thread(get_screen_context_for_advisor)
                remaining = [
                    {"tool": s.tool, "args": s.args, "reason": s.reason}
                    for s in plan.steps[i + 1:]
                ]
                
                if not step_passed:
                    verdict_msg = f"Critic failure: {critic_result.reason}" if critic_result else f"Execution failure: {reflection.message}"
                else:
                    verdict_msg = critic_result.reason if critic_result else "not verified"

                advice = await asyncio.to_thread(
                    advise_next_step,
                    goal=intent["goal"],
                    last_step={"tool": step.tool, "args": step.args, "reason": step.reason},
                    critic_verdict=verdict_msg,
                    remaining_steps=remaining,
                    screen_text=screen_text,
                )
                # Guard: if the Critic already visually confirmed this step,
                # don't let a stale UIA read from the Advisor undo that.
                # Background windows (Discord, Task Manager, etc.) often appear
                # in UIA right after a click and fool the Advisor into replanning.
                critic_confirmed = (
                    step_passed
                    and critic_result is not None
                    and critic_result.passed
                    and getattr(critic_result, "confidence", 1.0) >= 0.7
                )
                if critic_confirmed and advice.decision == "replan":
                    logger.warning(
                        f"[Advisor] Overriding REPLAN→PROCEED: Critic confirmed step at "
                        f"{getattr(critic_result, 'confidence', 1.0):.0%} confidence. "
                        f"Advisor reason was: {advice.reason}"
                    )
                    advice.decision = "proceed"

                emit(_make_event(
                    "log", task_id, step=step_num, total_steps=len(plan.steps),
                    message=f"[Advisor] {advice.decision.upper()}: {advice.reason}",
                ))

                if advice.decision == "done":
                    emit(_make_event(
                        "task_done", task_id, status="success",
                        message=f"Goal achieved early: {advice.reason}",
                    ))
                    # save to memory before returning
                    _save_task_memory(task_id, user_goal, intent, plan, results)
                    return {"success": True, "task_id": task_id, "steps": results}

                elif advice.decision == "skip":
                    emit(_make_event("log", task_id, step=step_num,
                                      message=f"[Advisor] Skipping next step: {plan.steps[i+1].tool}"))
                    i += 2  # advance past both current and skipped
                    continue

                elif advice.decision == "adapt" and advice.new_args:
                    plan.steps[i + 1].args.update(advice.new_args)
                    emit(_make_event("log", task_id, step=step_num,
                                      message=f"[Advisor] Adapting next step args: {advice.new_args}"))

                elif advice.decision == "replan" and task_replan_count < MAX_TASK_REPLANS:
                    task_replan_count += 1
                    emit(_make_event("log", task_id, step=step_num,
                                      message=f"[Advisor] Triggering replan (task attempt {task_replan_count}/{MAX_TASK_REPLANS})"))
                    try:
                        new_plan = await asyncio.to_thread(plan_task, intent, None, screen_text)
                        if new_plan.steps:
                            plan.steps = plan.steps[:i + 1] + new_plan.steps
                            logger.info(f"[Advisor] Replan injected {len(new_plan.steps)} steps")
                    except RuntimeError as e:
                        logger.warning(f"[Advisor] Replan failed: {e}")

            i += 1
            await asyncio.sleep(0.1)

        # ── 4. Done ────────────────────────────────────────────────────────
        success_count = sum(1 for r in results if r["success"])
        summary = f"Completed {success_count}/{len(results)} steps."
        final_status = "success" if success_count == len(results) else "partial"
        emit(_make_event("task_done", task_id, total_steps=len(plan.steps),
                         status=final_status, message=summary))

        _save_task_memory(task_id, user_goal, intent, plan, results)
        return {"success": True, "task_id": task_id, "steps": results}

    except Exception as e:
        logger.exception(f"Agent loop error: {e}")
        emit(_make_event("task_done", task_id, status="failure", message=str(e)))
        return {"success": False, "error": str(e)}
    finally:
        _current_task["running"] = False


def _save_task_memory(task_id: str, user_goal: str, intent: dict, plan, results: list) -> None:
    """Persist task outcome to memory. Feedback ('thumbs_up') is applied later via the API."""
    try:
        add_memory({
            "task_id": task_id,
            "type": "task",
            "goal": user_goal,
            "intent": intent.get("intent"),
            "steps": len(plan.steps),
            "success": all(r["success"] for r in results),
            "plan_steps": [{"tool": s.tool, "args": s.args} for s in plan.steps],
            # feedback will be patched to 'thumbs_up' via update_memory_feedback()
            # when the user rates the task in the UI
        })
    except Exception as e:
        logger.warning(f"Memory save failed: {e}")


# ─── Task control helpers ─────────────────────────────────────────────────────

def stop_task():
    """Signal the current task to stop."""
    _current_task["should_stop"] = True


def reset_lock():
    """Forcefully reset the task lock (use if task hangs)."""
    _current_task.update({"running": False, "task_id": None, "should_stop": False})
    logger.info("Task lock manually reset.")


def get_status() -> dict:
    return {
        "running": _current_task["running"],
        "task_id": _current_task["task_id"],
    }
