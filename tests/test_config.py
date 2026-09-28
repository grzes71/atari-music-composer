"""Unit tests for configuration management, priority resolution, and legacy compatibility."""

import os
import tempfile
import warnings
from pathlib import Path
import pytest
from click.testing import CliRunner

from config import Config, ConfigValidationError, create_arg_parser
from atari_music.cli import cli


def _clear_ai_env(monkeypatch):
    """Helper to remove all AI configuration environment variables."""
    for var in [
        "AI_PROVIDER",
        "AI_API_KEY",
        "AI_BASE_URL",
        "AI_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "LOG_LEVEL",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_default_values_when_no_env_and_no_args(monkeypatch):
    """When no .env file, env vars, or CLI args exist, code defaults are used."""
    _clear_ai_env(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_env = Path(tmpdir) / ".env.nonexistent"
        with pytest.warns(UserWarning, match="not found"):
            config = Config.from_args(args=[], env_path=non_existent_env, validate=False)

        assert config.ai_provider == "deepseek"
        assert config.ai_model == "deepseek-flash"
        assert config.ai_base_url == "https://api.deepseek.com"
        assert config.ai_api_key == ""
        assert config.log_level == "INFO"
        assert config.sources["AI_MODEL"] == "4) Code default"
        assert config.sources["AI_PROVIDER"] == "4) Code default"
        assert config.sources["LOG_LEVEL"] == "4) Code default"

        # Backward compatibility properties
        assert config.deepseek_model == "deepseek-flash"
        assert config.deepseek_base_url == "https://api.deepseek.com"
        assert config.deepseek_api_key == ""


def test_env_file_takes_precedence_over_defaults(monkeypatch):
    """Values from .env file override code defaults."""
    _clear_ai_env(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text(
            "AI_PROVIDER=deepseek\n"
            "AI_MODEL=deepseek-from-dotenv\n"
            "AI_BASE_URL=https://api.custom.com\n"
            "AI_API_KEY=sk-key-from-dotenv\n"
            "LOG_LEVEL=WARNING\n"
        )

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.ai_provider == "deepseek"
        assert config.ai_model == "deepseek-from-dotenv"
        assert config.ai_base_url == "https://api.custom.com"
        assert config.ai_api_key == "sk-key-from-dotenv"
        assert config.log_level == "WARNING"
        assert config.sources["AI_MODEL"] == "3) .env file"
        assert config.sources["LOG_LEVEL"] == "3) .env file"


def test_system_env_takes_precedence_over_dotenv(monkeypatch):
    """System environment variables override .env file values."""
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "model-from-system-env")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("AI_MODEL=model-from-dotenv\nLOG_LEVEL=INFO\n")

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.ai_model == "model-from-system-env"
        assert config.log_level == "DEBUG"
        assert config.sources["AI_MODEL"] == "2) System environment"
        assert config.sources["LOG_LEVEL"] == "2) System environment"


def test_system_env_not_overwritten_by_dotenv(monkeypatch):
    """Loading .env file MUST NEVER mutate or overwrite existing system environment variables."""
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "system-immutable-model")
    monkeypatch.setenv("AI_API_KEY", "system-immutable-key")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text(
            "AI_MODEL=file-model\n"
            "AI_API_KEY=file-key\n"
            "EXTRA_UNSET_VAR=from-file\n"
        )

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        # Config took the system environment value
        assert config.ai_model == "system-immutable-model"
        assert config.ai_api_key == "system-immutable-key"
        # os.environ itself was NOT mutated
        assert os.environ["AI_MODEL"] == "system-immutable-model"
        assert os.environ["AI_API_KEY"] == "system-immutable-key"
        assert "EXTRA_UNSET_VAR" not in os.environ


def test_cli_argument_highest_priority(monkeypatch):
    """CLI arguments override system env, .env, and defaults."""
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("AI_MODEL", "model-from-system-env")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("AI_MODEL=model-from-dotenv\n")

        config = Config.from_args(
            args=["--model", "model-from-cli", "--log-level", "ERROR"],
            env_path=env_file,
            validate=False,
        )
        assert config.ai_model == "model-from-cli"
        assert config.log_level == "ERROR"
        assert config.sources["AI_MODEL"] == "1) CLI argument"
        assert config.sources["LOG_LEVEL"] == "1) CLI argument"


def test_cli_provider_overrides_ai_provider(monkeypatch):
    """--provider CLI argument explicitly overrides AI_PROVIDER from env or .env."""
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER", "deepseek")

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("AI_PROVIDER=deepseek\n")

        config = Config.from_args(
            args=["--provider", "openai"],
            env_path=env_file,
            validate=False,
        )
        assert config.ai_provider == "openai"
        assert config.sources["AI_PROVIDER"] == "1) CLI argument"


def test_cli_env_file_option(monkeypatch):
    """--env-file CLI option loads configuration from specified custom .env file."""
    _clear_ai_env(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        default_env = Path(tmpdir) / ".env"
        default_env.write_text("AI_MODEL=default-env-model\n")

        custom_env = Path(tmpdir) / "custom.env"
        custom_env.write_text("AI_MODEL=custom-env-model\nAI_PROVIDER=openai\n")

        config = Config.from_args(
            args=["--env-file", str(custom_env)],
            env_path=default_env,
            validate=False,
        )
        assert config.ai_model == "custom-env-model"
        assert config.ai_provider == "openai"
        assert config.env_file == custom_env
        assert config.sources["AI_MODEL"] == "3) .env file"


def test_backward_compatibility_with_legacy_deepseek_env(monkeypatch):
    """Legacy DEEPSEEK_* settings in .env and environment are seamlessly recognized."""
    _clear_ai_env(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text(
            "DEEPSEEK_API_KEY=sk-legacy-deepseek-key\n"
            "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1\n"
            "DEEPSEEK_MODEL=deepseek-coder\n"
        )

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.ai_api_key == "sk-legacy-deepseek-key"
        assert config.ai_base_url == "https://api.deepseek.com/v1"
        assert config.ai_model == "deepseek-coder"
        # Backward compatibility aliases
        assert config.deepseek_api_key == "sk-legacy-deepseek-key"
        assert config.deepseek_base_url == "https://api.deepseek.com/v1"
        assert config.deepseek_model == "deepseek-coder"


def test_backward_compatibility_with_legacy_openai_env(monkeypatch):
    """Legacy OPENAI_* settings in .env and environment are seamlessly recognized as fallbacks."""
    _clear_ai_env(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text(
            "OPENAI_API_KEY=sk-legacy-openai-key\n"
            "OPENAI_BASE_URL=https://api.openai.com/v1\n"
            "OPENAI_MODEL=gpt-4o\n"
        )

        config = Config.from_args(args=[], env_path=env_file, validate=False)
        assert config.ai_api_key == "sk-legacy-openai-key"
        assert config.ai_base_url == "https://api.openai.com/v1"
        assert config.ai_model == "gpt-4o"


def test_validation_fails_on_placeholder_or_empty_key():
    """Validation raises ConfigValidationError if key is placeholder or empty."""
    cfg_placeholder = Config(ai_api_key="your_api_key_here")
    with pytest.raises(ConfigValidationError, match="AI_API_KEY is not configured"):
        cfg_placeholder.validate()

    cfg_empty = Config(ai_api_key="")
    with pytest.raises(ConfigValidationError, match="AI_API_KEY is not configured"):
        cfg_empty.validate()

    # Legacy argument compatibility in constructor
    cfg_legacy_empty = Config(deepseek_api_key="")
    with pytest.raises(ConfigValidationError, match="AI_API_KEY is not configured"):
        cfg_legacy_empty.validate()


def test_validation_succeeds_on_valid_key():
    """Validation passes when a real key and valid log level are set."""
    cfg = Config(ai_api_key="sk-real-secret-key-12345", log_level="INFO")
    cfg.validate()  # Should not raise


def test_masked_api_key():
    """Masked API key displays only first and last characters."""
    cfg = Config(ai_api_key="sk-1234567890abcdef1234")
    assert cfg.masked_api_key(visible_chars=4) == "sk-1...1234"

    cfg_placeholder = Config(ai_api_key="your_api_key_here")
    assert "placeholder" in cfg_placeholder.masked_api_key()

    cfg_empty = Config(ai_api_key="")
    assert cfg_empty.masked_api_key() == "(not set)"


def test_cli_click_global_env_file_option(tmp_path: Path):
    """Verify atari-music --env-file custom.env ai-compose uses custom env file and respects --provider override."""
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("AI_PROVIDER=deepseek\nAI_MODEL=custom-model-test\n")

    out_file = tmp_path / "out.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--env-file",
            str(custom_env),
            "ai-compose",
            "--provider",
            "mock",
            "-o",
            str(out_file),
        ],
    )
    assert result.exit_code == 0
    assert out_file.exists()
    assert "Requesting composition from provider 'mock'" in result.output
