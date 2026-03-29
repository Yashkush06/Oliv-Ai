"""Tests for safety.py — blocked patterns and approval-mode gating."""
import pytest
from unittest.mock import patch, MagicMock

# We need to ensure tools are importable from the backend dir
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.safety import validate_action, BLOCKED_PATTERNS, ValidationResult


# ── Blocked patterns ──────────────────────────────────────────────────────────

class TestBlockedPatterns:
    """Each dangerous command should be caught regardless of approval mode."""

    @pytest.mark.parametrize("command", [
        "rm -rf /",
        "rm -rf C:\\Users",
        "del /s C:\\Windows",
        "rd /s C:\\Users",
        "format C:",
        "system32\\cmd.exe",
        "shutdown /r",
        "shutdown /s",
        "reg delete HKLM\\Software",
        "bcdedit /set bootstatuspolicy",
        "diskpart",
        "cipher /w:C",
        "net user admin /delete",
        "taskkill /F /IM system",
        "icacls C:\\secret /grant Everyone:F",
    ])
    def test_dangerous_commands_blocked(self, tmp_config_dir, command):
        result = validate_action("run_command", {"command": command})
        assert result.allowed is False
        assert result.requires_confirm is False

    def test_safe_command_passes(self, tmp_config_dir):
        with patch("config.resolver.resolve_permission", return_value="auto"):
            with patch("tools.registry.get_tool") as mock_get:
                mock_get.return_value = MagicMock(risk_level="safe")
                result = validate_action("run_command", {"command": "echo hello"})
        assert result.allowed is True

    def test_blocked_pattern_in_nested_arg(self, tmp_config_dir):
        result = validate_action("run_command", {"args": {"cmd": "rm -rf /tmp"}})
        assert result.allowed is False


# ── Approval mode gating ──────────────────────────────────────────────────────

class TestApprovalModeGating:

    def _run_with_mode(self, mode: str, risk_level: str):
        from config.manager import save_config, load_config
        cfg = load_config()
        cfg["user_preferences"]["approval_mode"] = mode
        cfg["setup_complete"] = True
        save_config(cfg)

        with patch("tools.registry.get_tool") as mock_tool:
            mock_tool.return_value = MagicMock(risk_level=risk_level)
            return validate_action("open_app", {"app_name": "notepad"})

    def test_safe_mode_requires_confirm_for_moderate(self, tmp_config_dir):
        result = self._run_with_mode("safe", "moderate")
        assert result.allowed is True
        assert result.requires_confirm is True

    def test_smart_mode_requires_confirm_for_moderate(self, tmp_config_dir):
        result = self._run_with_mode("smart", "moderate")
        assert result.allowed is True
        assert result.requires_confirm is True

    def test_smart_mode_confirm_for_dangerous(self, tmp_config_dir):
        result = self._run_with_mode("smart", "dangerous")
        assert result.allowed is True
        assert result.requires_confirm is True

    def test_autonomous_mode_never_confirms(self, tmp_config_dir):
        result = self._run_with_mode("autonomous", "dangerous")
        assert result.allowed is True
        assert result.requires_confirm is False
