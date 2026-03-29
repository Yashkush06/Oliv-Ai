"""
Shared pytest fixtures for Oliv AI backend tests.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Config isolation ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """
    Point OLIV_CONFIG_DIR to a temp directory so tests never touch
    the real ~/.oliv-ai/config.json.
    """
    monkeypatch.setenv("OLIV_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def default_config(tmp_config_dir):
    """Load a fresh default config in the temp dir."""
    from config.manager import load_config
    return load_config()


@pytest.fixture
def saved_config(tmp_config_dir):
    """Write a known config to disk and return it."""
    from config.manager import save_config, load_config
    cfg = load_config()
    cfg["setup_complete"] = True
    cfg["model_config"]["provider"] = "ollama"
    cfg["model_config"]["model"] = "llava"
    cfg["user_preferences"]["approval_mode"] = "smart"
    save_config(cfg)
    return cfg


# ── LLM mock ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_router():
    """A mock LLMRouter that returns configurable responses."""
    router = MagicMock()
    router.generate_response.return_value = '{"steps": []}'
    router.test_connection.return_value = True
    return router


@pytest.fixture
def mock_router_patched(mock_router, monkeypatch):
    """Patches get_router() globally to return mock_router."""
    monkeypatch.setattr("llm.router._router_instance", mock_router)
    return mock_router
