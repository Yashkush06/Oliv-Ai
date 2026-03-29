"""Tests for agent/planner.py — JSON retry, schema validation, tool name checking."""
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch


VALID_PLAN_JSON = json.dumps({
    "steps": [
        {"tool": "open_url", "args": {"url": "https://youtube.com"}, "reason": "Navigate to YouTube"},
    ]
})

INVALID_JSON = "sure! here are the steps: open youtube then search"

VALID_BUT_UNKNOWN_TOOL = json.dumps({
    "steps": [
        {"tool": "nonexistent_tool", "args": {}, "reason": "Does not exist"},
    ]
})


@pytest.fixture(autouse=True)
def patch_tools():
    """Patch tool registry so planner tests don't need real tools imported."""
    from tools.registry import ToolDefinition
    fake_tools = [
        ToolDefinition(name="open_url", description="Open a URL", parameters={"url": {}}, risk_level="safe", fn=lambda: None),
        ToolDefinition(name="browser_type", description="Type in browser", parameters={"selector": {}, "text": {}}, risk_level="safe", fn=lambda: None),
    ]
    def fake_get(name):
        return next((t for t in fake_tools if t.name == name), None)
    
    # We need to return dicts for list_tools but objects for get_tool
    fake_tools_dicts = [
        {"name": t.name, "description": t.description, "parameters": t.parameters, "risk_level": t.risk_level}
        for t in fake_tools
    ]
    
    with patch("agent.planner.list_tools", return_value=fake_tools_dicts):
        with patch("tools.registry.get_tool", side_effect=fake_get):
            yield


class TestPlannerSuccess:

    def test_valid_plan_returned(self):
        """Router returns valid JSON → Plan with steps."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = VALID_PLAN_JSON

        with patch("agent.planner.get_router", return_value=mock_router):
            from agent.planner import plan_task
            plan = plan_task({"goal": "Open YouTube", "entities": {}, "suggested_tools": ["open_url"]})

        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_url"
        assert plan.steps[0].args == {"url": "https://youtube.com"}

    def test_empty_steps_for_conversation(self):
        """Model can return empty steps for conversational replies."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = json.dumps({"steps": []})

        with patch("agent.planner.get_router", return_value=mock_router):
            from agent.planner import plan_task
            plan = plan_task({"goal": "What time is it?", "entities": {}, "suggested_tools": []})

        assert plan.steps == []


class TestPlannerRetry:

    def test_retries_on_invalid_json(self):
        """First two responses are invalid JSON; third is valid. Planner should succeed."""
        mock_router = MagicMock()
        mock_router.generate_response.side_effect = [
            INVALID_JSON,
            INVALID_JSON,
            VALID_PLAN_JSON,
        ]

        with patch("agent.planner.get_router", return_value=mock_router):
            from agent.planner import plan_task
            plan = plan_task({"goal": "Open YouTube", "entities": {}, "suggested_tools": []})

        assert len(plan.steps) == 1

    def test_fails_after_all_retries_exhausted(self):
        """All 3 attempts return invalid JSON → RuntimeError raised."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = INVALID_JSON

        with patch("agent.planner.get_router", return_value=mock_router):
            from agent.planner import plan_task
            with pytest.raises(RuntimeError, match="Planner failed"):
                plan_task({"goal": "Open YouTube", "entities": {}, "suggested_tools": []})

    def test_fails_on_unknown_tool_name(self):
        """Plan references a tool not in the registry → RuntimeError."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = VALID_BUT_UNKNOWN_TOOL

        with patch("agent.planner.get_router", return_value=mock_router):
            from agent.planner import plan_task
            with pytest.raises(RuntimeError, match="Planner failed"):
                plan_task({"goal": "Do something", "entities": {}, "suggested_tools": []})
