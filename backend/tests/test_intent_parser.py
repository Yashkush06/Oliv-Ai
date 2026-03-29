"""Tests for agent/intent_parser.py — structured output from vague text."""
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch


VALID_INTENT = json.dumps({
    "intent": "browser_task",
    "goal": "Search for 'cat videos' on YouTube",
    "entities": {"site": "youtube.com", "query": "cat videos"},
    "suggested_tools": ["open_url", "browser_type"],
})

INVALID_JSON_RESPONSE = "Sure! I'll open YouTube and search for cat videos for you."

PARTIAL_INTENT = json.dumps({
    "intent": "open_app",
    "goal": "Open Notepad",
})


@pytest.fixture(autouse=True)
def patch_tools_list():
    fake_tools = [{"name": "open_url", "description": "Open a URL"}]
    with patch("agent.intent_parser.list_tools", return_value=fake_tools):
        yield


class TestIntentParserSuccess:

    def test_parses_valid_json_intent(self):
        mock_router = MagicMock()
        mock_router.generate_response.return_value = VALID_INTENT

        with patch("agent.intent_parser.get_router", return_value=mock_router):
            from agent.intent_parser import parse_intent
            result = parse_intent("open youtube and search cat videos")

        assert result["intent"] == "browser_task"
        assert "YouTube" in result["goal"]
        assert result["entities"]["query"] == "cat videos"
        assert "open_url" in result["suggested_tools"]

    def test_fills_missing_fields_with_defaults(self):
        """Partial intent JSON still gets defaults for missing keys."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = PARTIAL_INTENT

        with patch("agent.intent_parser.get_router", return_value=mock_router):
            from agent.intent_parser import parse_intent
            result = parse_intent("open notepad")

        assert result["intent"] == "open_app"
        assert result.get("entities") == {}
        assert result.get("suggested_tools") == []

    def test_strips_markdown_fences(self):
        """Model wraps JSON in markdown fences — parser should strip them."""
        fenced = "```json\n" + VALID_INTENT + "\n```"
        mock_router = MagicMock()
        mock_router.generate_response.return_value = fenced

        with patch("agent.intent_parser.get_router", return_value=mock_router):
            from agent.intent_parser import parse_intent
            result = parse_intent("open youtube and search cat videos")

        assert result["intent"] == "browser_task"


class TestIntentParserFallback:

    def test_falls_back_to_raw_input_on_failure(self):
        """If LLM always returns invalid JSON, fallback wraps raw input."""
        mock_router = MagicMock()
        mock_router.generate_response.return_value = INVALID_JSON_RESPONSE

        with patch("agent.intent_parser.get_router", return_value=mock_router):
            from agent.intent_parser import parse_intent
            result = parse_intent("do something vague")

        assert result["intent"] == "general_task"
        assert result["goal"] == "do something vague"
        assert result["entities"] == {}
        assert result["suggested_tools"] == []
