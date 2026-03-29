"""
Safety validator: blocks dangerous commands and enforces approval mode.
Every tool execution passes through validate_action() before running.
"""
import re
import logging
from dataclasses import dataclass

from config.resolver import resolve_permission

logger = logging.getLogger(__name__)

# Patterns that are ALWAYS blocked regardless of approval mode
BLOCKED_PATTERNS = [
    r"rm\s+-[rRfF]{1,2}",                # rm -rf
    r"del\s+/[sS]",                       # del /s
    r"rd\s+/[sS]",                        # rd /s (remove dir)
    r"format\s+[a-zA-Z]:",               # format C:
    r"[Ss]ystem32",                       # anything touching System32
    r"shutdown\s+/[rRsS]",               # shutdown /r or /s
    r"reg\s+delete",                      # registry deletion
    r"bcdedit",                           # boot config edit
    r"diskpart",                          # disk partitioning
    r"cipher\s+/[wW]",                   # data wiping
    r"net\s+user\s+.+\s+/delete",        # user deletion
    r"taskkill\s+/[fF].*system",         # force-killing system processes
    r"icacls.*\/grant.*Everyone",        # dangerous permission grants
]


@dataclass
class ValidationResult:
    allowed: bool
    reason: str
    requires_confirm: bool


def validate_action(tool_name: str, args: dict) -> ValidationResult:
    """
    Validate a tool call before execution.
    1. Checks args against blocked patterns (hard block)
    2. Checks approval_mode for whether confirmation is needed
    """
    # Flatten all string argument values for pattern scanning
    arg_strings = _flatten_args(args)

    for pattern in BLOCKED_PATTERNS:
        for arg_val in arg_strings:
            if re.search(pattern, arg_val, re.IGNORECASE):
                logger.warning(f"BLOCKED: tool={tool_name}, pattern={pattern!r}, value={arg_val!r}")
                return ValidationResult(
                    allowed=False,
                    reason=f"Blocked: command matches dangerous pattern '{pattern}'",
                    requires_confirm=False,
                )

    # Check risk level via approval mode
    from tools.registry import get_tool
    tool_def = get_tool(tool_name)
    risk_level = tool_def.risk_level if tool_def else "moderate"

    permission = resolve_permission(tool_name, risk_level)
    requires_confirm = permission == "confirm"

    return ValidationResult(
        allowed=True,
        reason="OK",
        requires_confirm=requires_confirm,
    )


def _flatten_args(args: dict) -> list[str]:
    """Recursively collect all string values from an args dict."""
    results = []
    for v in args.values():
        if isinstance(v, str):
            results.append(v)
        elif isinstance(v, dict):
            results.extend(_flatten_args(v))
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    results.append(item)
    return results
