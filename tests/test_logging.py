"""Unit tests for centralized logging, level configuration, and secret protection."""

from __future__ import annotations

import io
import json
import logging
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from atari_music.ai.client import generate_composition_with_retry
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.providers.openai import OpenAICompositionProvider
from atari_music.ai.schema import AICompositionDoc
from atari_music.cli import cli
from atari_music.logging_config import (
    DEFAULT_LOG_LEVEL,
    LOG_LEVEL_MAP,
    clear_registered_secrets,
    mask_secret,
    normalize_log_level,
    redact_text,
    register_secret,
    sanitize_for_logging,
    setup_logging,
)


@pytest.fixture(autouse=True)
def clean_logging_state():
    """Ensure clean logging state before and after each test."""
    clear_registered_secrets()
    yield
    clear_registered_secrets()
    # Reset root logger to default
    setup_logging(DEFAULT_LOG_LEVEL)


# =============================================================================
# 1. Central Configuration and Level Resolution Tests
# =============================================================================

def test_normalize_log_level_standard_names():
    """Verify standard level strings (case-insensitive) map to correct logging integers."""
    assert normalize_log_level("DEBUG") == logging.DEBUG
    assert normalize_log_level("debug") == logging.DEBUG
    assert normalize_log_level("INFO") == logging.INFO
    assert normalize_log_level("info") == logging.INFO
    assert normalize_log_level("WARNING") == logging.WARNING
    assert normalize_log_level("warning") == logging.WARNING
    assert normalize_log_level("ERROR") == logging.ERROR
    assert normalize_log_level("error") == logging.ERROR
    assert normalize_log_level("CRITICAL") == logging.CRITICAL
    assert normalize_log_level("critical") == logging.CRITICAL


def test_normalize_log_level_integers():
    """Verify that integer level values pass through correctly."""
    assert normalize_log_level(logging.DEBUG) == logging.DEBUG
    assert normalize_log_level(logging.INFO) == logging.INFO
    assert normalize_log_level(logging.WARNING) == logging.WARNING


def test_normalize_log_level_invalid_raises():
    """Verify that invalid log level strings raise ValueError."""
    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        normalize_log_level("VERBOSE")

    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        normalize_log_level("TRACE")


def test_normalize_log_level_default_and_env(monkeypatch):
    """Verify default behavior when level is None, and LOG_LEVEL environment override."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert normalize_log_level(None) == logging.WARNING

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert normalize_log_level(None) == logging.DEBUG


def test_setup_logging_stream_and_level():
    """Verify setup_logging configures root and atari_music logger and outputs to stream."""
    stream = io.StringIO()
    root = setup_logging(level="DEBUG", stream=stream)

    assert root.level == logging.DEBUG
    logger = logging.getLogger("atari_music.test_module")
    logger.debug("Test debug message 123")
    logger.info("Test info message 456")

    output = stream.getvalue()
    assert "Test debug message 123" in output
    assert "Test info message 456" in output


def test_setup_logging_filters_lower_priority_messages():
    """Verify WARNING level suppresses DEBUG and INFO messages."""
    stream = io.StringIO()
    setup_logging(level="WARNING", stream=stream)

    logger = logging.getLogger("atari_music.test_module")
    logger.debug("Should be suppressed")
    logger.info("Also suppressed")
    logger.warning("Should appear")

    output = stream.getvalue()
    assert "Should be suppressed" not in output
    assert "Also suppressed" not in output
    assert "Should appear" in output


# =============================================================================
# 2. Secret Redaction & Protection Tests
# =============================================================================

def test_mask_secret():
    """Verify masking logic for secrets."""
    assert mask_secret("sk-1234567890abcdef") == "sk-1...cdef"
    assert mask_secret("short") == "******"
    assert mask_secret("") == "(not set)"
    assert mask_secret("your_api_key_here") == "(placeholder: your_api_key_here)"


def test_sanitize_for_logging_masks_sensitive_keys():
    """Verify recursive payload sanitization masks keys containing secrets."""
    payload = {
        "model": "deepseek-flash",
        "api_key": "sk-super-secret-key-99999",
        "nested": {
            "Authorization": "Bearer sk-bearer-token-11111",
            "safe_param": 42,
        },
        "list_items": [
            {"password": "hidden_pass", "name": "sample"},
        ],
    }

    clean = sanitize_for_logging(payload)
    assert "sk-super-secret-key-99999" not in json.dumps(clean)
    assert "hidden_pass" not in json.dumps(clean)
    assert clean["nested"]["safe_param"] == 42


def test_redacting_formatter_masks_registered_secrets():
    """Verify RedactingFormatter guarantees registered secrets never appear in output."""
    raw_secret = "sk-live-secret-never-leak-987654321"
    register_secret(raw_secret)

    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    logger = logging.getLogger("atari_music.secrets_test")
    logger.debug("Connecting with API key: %s", raw_secret)
    logger.debug("Raw URL: https://api.deepseek.com?token=%s", raw_secret)
    logger.debug("Header: Authorization: Bearer %s", raw_secret)

    output = stream.getvalue()
    # The raw secret MUST NEVER be present in the output
    assert raw_secret not in output
    assert "sk-l...4321" in output or "[REDACTED]" in output


# =============================================================================
# 3. LLM Provider Diagnostic Logging in DEBUG
# =============================================================================

def test_openai_provider_debug_logging_and_secret_masking():
    """Verify OpenAI provider logs request diagnostics and masks secrets in DEBUG mode."""
    secret_key = "sk-very-secret-openai-api-key-1234567890"

    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    provider = OpenAICompositionProvider(
        api_key=secret_key,
        model="test-model",
        base_url="https://api.openai.com/v1",
    )

    # Mock OpenAI client
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.content = '{"format": "atari-music-composition", "version": 1, "patterns": []}'
    mock_choice.message.parsed = None

    mock_completion = MagicMock()
    mock_completion.id = "chatcmpl-test-12345"
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.return_value = mock_completion

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    req = CompositionRequest(style="dungeon", mood=["dark"], duration_seconds=16)

    import sys
    with patch.dict(sys.modules, {"openai": mock_openai}):
        try:
            provider.generate_composition(req)
        except Exception:
            pass  # Schema validation might fail on minimal JSON, but we check logging

    log_output = stream.getvalue()

    # 1. Diagnostics MUST be present
    assert "LLM API Request -> Endpoint: https://api.openai.com/v1" in log_output
    assert "Model: test-model" in log_output
    assert "Messages:" in log_output
    assert "LLM API Request Parameters:" in log_output
    assert "LLM API Request Payload:" in log_output
    assert "LLM API Response received [id=chatcmpl-test-12345]" in log_output

    # 2. Secret key MUST NEVER appear in plain text
    assert secret_key not in log_output


# =============================================================================
# 4. Composition Repair Loop Logging in DEBUG
# =============================================================================

def test_repair_loop_debug_logging():
    """Verify Composition Repair Loop logs attempt numbers, validation failure, feedback, and success."""
    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    req = CompositionRequest(style="action", bpm=120, channels=4)
    # Scenario "invalid_then_valid" fails attempt 1 on NOTE_OVERLAP and succeeds attempt 2
    mock_provider = MockAICompositionProvider(scenario="invalid_then_valid")

    doc = generate_composition_with_retry(req, mock_provider, max_retries=2)
    assert isinstance(doc, AICompositionDoc)

    log_output = stream.getvalue()

    # Verify repair loop diagnostics
    assert "Composition Repair Loop: starting attempt 1/3" in log_output
    assert "Composition validation FAILED on attempt 1" in log_output
    assert "NOTE_OVERLAP" in log_output
    assert "scheduling retry attempt 2" in log_output
    assert "Composition Repair Loop: starting attempt 2/3" in log_output
    assert "Composition validation PASSED on attempt 2" in log_output


# =============================================================================
# 5. CLI Global Option --log-level Tests
# =============================================================================

def test_cli_help_shows_log_level_option():
    """Verify atari-music CLI help displays global --log-level option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--log-level" in result.output
    assert "DEBUG" in result.output
    assert "CRITICAL" in result.output


def test_cli_log_level_debug_activation():
    """Verify passing --log-level DEBUG configures the logger and outputs debug logs."""
    runner = CliRunner()
    # Invoke a quick command with --log-level DEBUG
    result = runner.invoke(cli, ["--log-level", "DEBUG", "compose", "--help"])
    assert result.exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


def test_cli_log_level_invalid_rejected():
    """Verify invalid --log-level value is rejected by CLI parser."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--log-level", "INVALID_LEVEL", "compose", "--help"])
    assert result.exit_code != 0
    assert "Invalid value for '--log-level'" in result.output


def test_cli_stream_separation_stdout_clean_json_under_debug():
    """Verify stdout receives only machine-readable JSON while logs go to stderr."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--log-level", "DEBUG", "ai-compose", "--style", "action", "--provider", "mock"],
    )
    assert result.exit_code == 0
    # stdout must parse cleanly as JSON
    parsed = json.loads(result.stdout)
    assert parsed.get("format") == "atari-music-composition"
    assert "patterns" in parsed
    # stderr must contain the diagnostic logs and progress messages
    assert "DEBUG" in result.stderr
    assert "Requesting composition from provider" in result.stderr
    assert "Composition validation PASSED" in result.stderr


# =============================================================================
# 6. Music DSL Prompt Logging in DEBUG
# =============================================================================

def test_openai_provider_dsl_prompt_debug_logging():
    """Verify OpenAI provider logs Music DSL system prompt, user prompt, and payload under DEBUG."""
    secret_key = "sk-dsl-prompt-secret-key-9876543210"

    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    provider = OpenAICompositionProvider(
        api_key=secret_key,
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
    )

    mock_choice = MagicMock()
    mock_choice.message.content = 'TITLE "DSL Log Test"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'

    mock_completion = MagicMock()
    mock_completion.id = "chatcmpl-dsl-debug-001"
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    req = CompositionRequest(style="dungeon", format="dsl", dsl_version="v1.1", duration_seconds=16)

    import sys
    with patch.dict(sys.modules, {"openai": mock_openai}):
        result = provider.generate_composition_dsl(req)

    assert "TITLE" in result
    log_output = stream.getvalue()

    # 1. DSL Prompts MUST be logged at DEBUG level
    assert "Music DSL System Prompt (version=v1.1):" in log_output
    assert "Do not specify pattern length." in log_output
    assert "Music DSL User Prompt:" in log_output
    assert "LLM API Request -> Endpoint: https://api.deepseek.com/v1" in log_output
    assert "Format: dsl" in log_output
    assert "LLM API Request Payload (DSL):" in log_output
    assert "LLM API Response received (DSL" in log_output

    # 2. Secret key MUST NOT be present in plain text
    assert secret_key not in log_output


def test_openai_provider_dsl_repair_prompt_debug_logging():
    """Verify repair feedback and previous DSL are logged under DEBUG level when repairing."""
    secret_key = "sk-dsl-repair-secret-9999"

    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    provider = OpenAICompositionProvider(
        api_key=secret_key,
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
    )

    mock_choice = MagicMock()
    mock_choice.message.content = 'TITLE "Repaired"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'

    mock_completion = MagicMock()
    mock_completion.id = "chatcmpl-dsl-repair-002"
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    req = CompositionRequest(style="action", format="dsl", dsl_version="v1.1")

    import sys
    with patch.dict(sys.modules, {"openai": mock_openai}):
        provider.generate_composition_dsl(
            req,
            feedback="Line 5: Pattern exceeds explicit length",
            previous_dsl="[PATTERN A length=8]\nCH1 LEAD V14\nC4/16",
        )

    log_output = stream.getvalue()
    assert "Music DSL Repair Prompt:" in log_output
    assert "Line 5: Pattern exceeds explicit length" in log_output
    assert "Previous Music DSL to repair:" in log_output


def test_mock_provider_dsl_prompt_debug_logging():
    """Verify MockAICompositionProvider logs DSL prompts in DEBUG mode."""
    stream = io.StringIO()
    setup_logging(level="DEBUG", stream=stream)

    provider = MockAICompositionProvider()
    req = CompositionRequest(style="action", format="dsl", dsl_version="v1.1")

    provider.generate_composition_dsl(req)
    log_output = stream.getvalue()

    assert "Music DSL System Prompt (mock, version=v1.1):" in log_output
    assert "Music DSL User Prompt (mock):" in log_output


