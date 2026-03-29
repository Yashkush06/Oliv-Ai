"""Tests for llm/router.py — initialization, routing, and test_connection."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch


def _make_config(provider="ollama", model="llama3", api_key=None, api_provider=None):
    return {
        "model_config": {
            "provider": provider,
            "model": model,
            "base_url": "http://localhost:11434",
            "api_provider": api_provider,
            "api_key": api_key,
            "timeout_seconds": 10,
        }
    }


class TestRouterInit:

    def test_ollama_provider_creates_ollama_client(self):
        with patch("llm.router.OllamaClient") as MockOllama:
            MockOllama.return_value = MagicMock()
            from llm.router import LLMRouter
            router = LLMRouter(_make_config("ollama"))
            MockOllama.assert_called_once()

    def test_api_provider_creates_api_client(self):
        with patch("llm.router.APIClient") as MockAPI:
            MockAPI.return_value = MagicMock()
            from llm.router import LLMRouter
            router = LLMRouter(_make_config("api", api_key="sk-test", api_provider="openai"))
            MockAPI.assert_called_once()

    def test_unknown_provider_raises(self):
        from llm.router import LLMRouter
        with pytest.raises(ValueError, match="Unknown provider"):
            LLMRouter(_make_config("unsupported_llm"))


class TestRouterGenerateResponse:

    def test_generate_response_returns_content(self):
        mock_client = MagicMock()
        mock_client.generate.return_value = MagicMock(content="Paris")

        with patch("llm.router.OllamaClient", return_value=mock_client):
            from llm.router import LLMRouter
            router = LLMRouter(_make_config("ollama"))
            result = router.generate_response("What is the capital of France?")

        assert result == "Paris"

    def test_generate_response_passes_system_prompt(self):
        mock_client = MagicMock()
        mock_client.generate.return_value = MagicMock(content="ok")

        with patch("llm.router.OllamaClient", return_value=mock_client):
            from llm.router import LLMRouter
            router = LLMRouter(_make_config("ollama"))
            router.generate_response("Hello", system_prompt="You are a helpful assistant.", temperature=0.5)

        call_kwargs = mock_client.generate.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "You are a helpful assistant."
        assert call_kwargs.kwargs.get("temperature") == 0.5


class TestRouterHotReload:

    def test_reload_switches_client(self):
        mock_ollama = MagicMock()
        mock_api = MagicMock()

        with patch("llm.router.OllamaClient", return_value=mock_ollama):
            with patch("llm.router.APIClient", return_value=mock_api):
                from llm.router import LLMRouter
                router = LLMRouter(_make_config("ollama"))
                assert router._client is mock_ollama

                router.reload(_make_config("api", api_key="sk-x", api_provider="openai"))
                assert router._client is mock_api


class TestTestConnection:

    def test_passes_through_to_client(self):
        mock_client = MagicMock()
        mock_client.test_connection.return_value = True

        with patch("llm.router.OllamaClient", return_value=mock_client):
            from llm.router import LLMRouter
            router = LLMRouter(_make_config("ollama"))
            assert router.test_connection() is True


class TestGlobalSingleton:

    def test_get_router_raises_before_init(self):
        import llm.router as r
        r._router_instance = None
        from llm.router import get_router
        with pytest.raises(RuntimeError, match="not initialized"):
            get_router()

    def test_init_router_sets_instance(self):
        mock_client = MagicMock()
        with patch("llm.router.OllamaClient", return_value=mock_client):
            import llm.router as r
            r._router_instance = None
            from llm.router import init_router, get_router
            init_router(_make_config("ollama"))
            assert get_router() is not None
