"""
Executor — runs a single plan step through the safety validator and tool registry.
"""
import asyncio
import inspect
import logging
import traceback
from typing import Any

from tools.registry import get_tool
from tools.safety import validate_action

logger = logging.getLogger(__name__)


class ExecutorResult:
    def __init__(self, success: bool, result: Any, error: str = ""):
        self.success = success
        self.result = result
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
        }


async def run_step(tool_name: str, args: dict, bypass_safety: bool = False) -> ExecutorResult:
    """
    Execute one plan step:
    1. Safety validation (blocks dangerous commands, unless bypassed)
    2. Permission check (may require user confirmation — caller handles this)
    3. Tool execution
    """
    if bypass_safety:
        logger.warning(f"Safety bypass active for: {tool_name}({args})")

    if not bypass_safety:
        # Safety check
        validation = validate_action(tool_name, args)

        if not validation.allowed:
            logger.warning(f"BLOCKED: {tool_name}({args}) — {validation.reason}")
            return ExecutorResult(
                success=False,
                result=None,
                error=f"Blocked by safety validator: {validation.reason}",
            )

        if validation.requires_confirm:
            # Signal to the loop that confirmation is needed
            # The loop will emit an ask_user WebSocket event and pause
            logger.info(f"Confirmation required for: {tool_name}({args})")
            return ExecutorResult(
                success=False,
                result={"requires_confirm": True, "tool": tool_name, "args": args},
                error="requires_confirmation",
            )

    # Execute
    try:
        logger.info(f"Executing: {tool_name}({args})")

        tool_def = get_tool(tool_name)
        if not tool_def:
            return ExecutorResult(success=False, result=None, error=f"Unknown tool: {tool_name}")

        try:
            async with asyncio.timeout(30):
                if inspect.iscoroutinefunction(tool_def.fn):
                    result = await tool_def.fn(**args)
                else:
                    result = await asyncio.to_thread(lambda: tool_def.fn(**args))
        except asyncio.TimeoutError:
            logger.error(f"Tool '{tool_name}' timed out after 30s")
            return ExecutorResult(
                success=False,
                result=None,
                error=f"Tool '{tool_name}' timed out after 30 seconds.",
            )

        success = result.get("success", True) if isinstance(result, dict) else True
        return ExecutorResult(
            success=success,
            result=result,
            error=result.get("error", "") if isinstance(result, dict) else "",
        )
    except Exception as e:
        err_msg = str(e).strip() or traceback.format_exc().strip()
        logger.error(f"Tool execution failed: {tool_name} — {err_msg}")
        return ExecutorResult(success=False, result=None, error=err_msg)
