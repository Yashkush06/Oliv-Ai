"""Tests for config/manager.py — load, save, update, get/set, vision_model field."""
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestLoadConfig:

    def test_returns_defaults_when_no_file(self, tmp_config_dir):
        from config.manager import load_config, DEFAULT_CONFIG
        cfg = load_config()
        assert cfg["setup_complete"] is False
        assert cfg["model_config"]["provider"] == DEFAULT_CONFIG["model_config"]["provider"]

    def test_merges_missing_keys_from_defaults(self, tmp_config_dir):
        """A config on disk missing new keys should get them filled from defaults."""
        config_path = tmp_config_dir / "config.json"
        config_path.write_text(json.dumps({"setup_complete": True}))

        from config.manager import load_config
        cfg = load_config()
        # Old key preserved
        assert cfg["setup_complete"] is True
        # New key backfilled
        assert "model_config" in cfg
        assert "vision_model" in cfg["model_config"]

    def test_returns_defaults_on_corrupt_file(self, tmp_config_dir):
        config_path = tmp_config_dir / "config.json"
        config_path.write_text("this is not json {{{{")

        from config.manager import load_config
        cfg = load_config()
        assert cfg["setup_complete"] is False


class TestSaveAndUpdate:

    def test_saves_and_reloads(self, tmp_config_dir):
        from config.manager import save_config, load_config
        cfg = load_config()
        cfg["setup_complete"] = True
        cfg["model_config"]["model"] = "qwen2.5"
        save_config(cfg)

        reloaded = load_config()
        assert reloaded["setup_complete"] is True
        assert reloaded["model_config"]["model"] == "qwen2.5"

    def test_update_config_deep_merges(self, tmp_config_dir):
        from config.manager import update_config, load_config
        # Set an initial state
        update_config({"model_config": {"model": "llama3"}})
        # Partial update should not wipe other model_config keys
        update_config({"model_config": {"provider": "api"}})
        cfg = load_config()
        assert cfg["model_config"]["model"] == "llama3"
        assert cfg["model_config"]["provider"] == "api"


class TestGetSetValue:

    def test_dot_notation_get(self, tmp_config_dir):
        from config.manager import get_value, save_config, load_config
        cfg = load_config()
        cfg["user_preferences"]["approval_mode"] = "autonomous"
        save_config(cfg)

        val = get_value("user_preferences.approval_mode")
        assert val == "autonomous"

    def test_dot_notation_set(self, tmp_config_dir):
        from config.manager import set_value, get_value
        set_value("model_config.vision_model", "ollama:llava")
        val = get_value("model_config.vision_model")
        assert val == "ollama:llava"

    def test_missing_key_returns_default(self, tmp_config_dir):
        from config.manager import get_value
        val = get_value("nonexistent.key.path", "fallback")
        assert val == "fallback"


class TestApprovalMode:

    @pytest.mark.parametrize("mode", ["safe", "smart", "autonomous"])
    def test_approval_mode_values(self, tmp_config_dir, mode):
        from config.manager import set_value, get_value
        set_value("user_preferences.approval_mode", mode)
        assert get_value("user_preferences.approval_mode") == mode


class TestVisionModelConfig:

    def test_vision_model_defaults_to_none(self, tmp_config_dir):
        from config.manager import load_config
        cfg = load_config()
        assert cfg["model_config"]["vision_model"] is None

    def test_vision_model_can_be_set(self, tmp_config_dir):
        from config.manager import set_value, get_value
        set_value("model_config.vision_model", "api:gpt-4o")
        assert get_value("model_config.vision_model") == "api:gpt-4o"
