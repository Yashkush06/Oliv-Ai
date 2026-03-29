"""Import all tools to register them with the registry."""
from . import system_tools, input_tools, screen_tools, browser_tools  # noqa: F401
from . import file_tools, clipboard_tools, window_tools               # noqa
from .registry import tool, get_tool, list_tools, execute_tool
from .safety import validate_action

__all__ = ["tool", "get_tool", "list_tools", "execute_tool", "validate_action"]
