"""Unit tests for configuration management and priority resolution."""

import os
import tempfile
import warnings
from pathlib import Path
import pytest

from config import Config, ConfigValidationError, create_arg_parser


def test_default_values_when_no_env_and_no_args(monkeypatch):
    """When no .env file, env vars, or CLI args exist, code defaults are used."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_env = Path(tmpdir) / ".env.nonexistent"
        with pytest.warns(UserWarning, match="not found"):
            config = Config.from_args(args=[], env_path=non_existent_env, validate=False)

        assert config.deepseek_model == "deepseek-flash"
        assert config.deepseek_base_url == "https://api.deepseek.com"
        assert config.log_level == "INFO"
        assert config.sources["DEEPSEEK_MODEL"] == "4) Code default"
        assert config.sources["LOG_LEVEL"] == "4) Code default"


def test_env_file_takes_precedence_over_defaults(monkeypatch):
    """Values from .env file override code defaults."""
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("DEEPSEEK_MODEL=deepseek-from-dotenv\nLOG_LEVEL=WARNING\n")

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.deepseek_model == "deepseek-from-dotenv"
        assert config.log_level == "WARNING"
        assert config.sources["DEEPSEEK_MODEL"] == "3) .env file"
        assert config.sources["LOG_LEVEL"] == "3) .env file"


def test_system_env_takes_precedence_over_dotenv(monkeypatch):
    """System environment variables override .env file values."""
    monkeypatch.setenv("DEEPSEEK_MODEL", "model-from-system-env")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("DEEPSEEK_MODEL=model-from-dotenv\nLOG_LEVEL=INFO\n")

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.deepseek_model == "model-from-system-env"
        assert config.log_level == "DEBUG"
        assert config.sources["DEEPSEEK_MODEL"] == "2) System environment"
        assert config.sources["LOG_LEVEL"] == "2) System environment"


def test_cli_argument_highest_priority(monkeypatch):
    """CLI arguments override system env, .env, and defaults."""
    monkeypatch.setenv("DEEPSEEK_MODEL", "model-from-system-env")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("DEEPSEEK_MODEL=model-from-dotenv\n")

        config = Config.from_args(
            args=["--model", "model-from-cli", "--log-level", "ERROR"],
            env_path=env_file,
            validate=False,
        )
        assert config.deepseek_model == "model-from-cli"
        assert config.log_level == "ERROR"
        assert config.sources["DEEPSEEK_MODEL"] == "1) CLI argument"
        assert config.sources["LOG_LEVEL"] == "1) CLI argument"


def test_validation_fails_on_placeholder_or_empty_key():
    """Validation raises ConfigValidationError if key is placeholder or empty."""
    cfg_placeholder = Config(deepseek_api_key="your_api_key_here")
    with pytest.raises(ConfigValidationError, match="DEEPSEEK_API_KEY is not configured"):
        cfg_placeholder.validate()

    cfg_empty = Config(deepseek_api_key="")
    with pytest.raises(ConfigValidationError, match="DEEPSEEK_API_KEY is not configured"):
        cfg_empty.validate()


def test_validation_succeeds_on_valid_key():
    """Validation passes when a real key and valid log level are set."""
    cfg = Config(deepseek_api_key="sk-real-secret-key-12345", log_level="INFO")
    cfg.validate()  # Should not raise


def test_masked_api_key():
    """Masked API key displays only first and last characters."""
    cfg = Config(deepseek_api_key="sk-1234567890abcdef1234")
    assert cfg.masked_api_key(visible_chars=4) == "sk-1...1234"

    cfg_placeholder = Config(deepseek_api_key="your_api_key_here")
    assert "placeholder" in cfg_placeholder.masked_api_key()

    cfg_empty = Config(deepseek_api_key="")
    assert cfg_empty.masked_api_key() == "(not set)"
