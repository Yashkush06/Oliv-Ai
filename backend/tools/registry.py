"""
Tool registry: decorator-based registration of all agent tools.
Each tool declares its name, description, parameters, and risk_level.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, "ToolDefinition"] = {}


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    risk_level: str       # "safe" | "moderate" | "dangerous"
    fn: Callable


def tool(name: str, description: str, parameters: dict, risk_level: str = "safe"):
    """Decorator to register a function as a tool."""
    def decorator(fn: Callable):
        _REGISTRY[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            risk_level=risk_level,
            fn=fn,
        )
        logger.debug(f"Registered tool: {name} (risk={risk_level})")
        return fn
    return decorator


def get_tool(name: str) -> Optional[ToolDefinition]:
    return _REGISTRY.get(name)


def list_tools() -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "risk_level": t.risk_level,
        }
        for t in _REGISTRY.values()
    ]


def execute_tool(name: str, args: dict) -> Any:
    """Execute a registered tool by name with given args."""
    tool_def = get_tool(name)
    if not tool_def:
        raise ValueError(f"Unknown tool: '{name}'. Available: {list(_REGISTRY.keys())}")
    try:
        result = tool_def.fn(**args)
        return result
    except TypeError as e:
        raise ValueError(f"Invalid args for tool '{name}': {e}")
