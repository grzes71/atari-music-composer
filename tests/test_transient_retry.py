"""Unit tests for exponential backoff on HTTP 503 and 429 transient errors."""

import sys
from unittest.mock import MagicMock, patch
import pytest

from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.openai import OpenAICompositionProvider, _is_transient_http_error
from atari_music.ai.schema import AIProviderAPIError, AICompositionDoc


def test_is_transient_http_error_detection():
    """Verify various forms of 503 and 429 errors are recognized."""
    # Attribute status_code
    err_503 = Exception("Server error")
    err_503.status_code = 503
    is_trans, code, _ = _is_transient_http_error(err_503)
    assert is_trans is True
    assert code == 503

    err_429 = Exception("Rate limited")
    err_429.status_code = 429
    is_trans, code, _ = _is_transient_http_error(err_429)
    assert is_trans is True
    assert code == 429

    # Response attribute status_code
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    err_resp_503 = Exception("Error")
    err_resp_503.response = mock_resp
    is_trans, code, _ = _is_transient_http_error(err_resp_503)
    assert is_trans is True
    assert code == 503

    # Error message substring
    err_msg_503 = RuntimeError("Error 503: Service Unavailable")
    is_trans, code, _ = _is_transient_http_error(err_msg_503)
    assert is_trans is True
    assert code == 503

    err_msg_429 = RuntimeError("Error: Rate limit exceeded, please slow down")
    is_trans, code, _ = _is_transient_http_error(err_msg_429)
    assert is_trans is True
    assert code == 429

    # Non-transient error
    err_400 = Exception("Bad Request")
    err_400.status_code = 400
    is_trans, code, _ = _is_transient_http_error(err_400)
    assert is_trans is False


def test_openai_retries_on_503_and_succeeds():
    """Provider recovers from HTTP 503 after exponential backoff."""
    provider = OpenAICompositionProvider(
        api_key="sk-test-key",
        max_transient_retries=3,
        initial_backoff=0.01,  # Fast backoff for unit testing
        backoff_factor=2.0,
    )

    err_503 = Exception("HTTP 503 Service Unavailable")
    err_503.status_code = 503

    mock_client = MagicMock()
    # First attempt fails with 503, second attempt succeeds
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "Recovered Track", "bpm": 120},
        "intent": {"style": "heroic", "mood": ["epic"]},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [],
        "patterns": [],
        "sequence": ["A"],
        "loop_point": 0,
    }
    mock_completion = MagicMock()
    mock_completion.id = "resp-503-ok"
    mock_completion.choices = [mock_choice]

    mock_client.beta.chat.completions.parse.side_effect = [err_503, mock_completion]

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    sleep_calls = []
    with patch.dict(sys.modules, {"openai": mock_openai}), patch("time.sleep", side_effect=sleep_calls.append):
        req = CompositionRequest(style="heroic")
        result = provider.generate_composition(req)

    assert result["metadata"]["title"] == "Recovered Track"
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(0.01, abs=0.005)
    assert mock_client.beta.chat.completions.parse.call_count == 2


def test_openai_retries_on_429_exponential_backoff():
    """Provider applies exponential backoff on multiple 429 rate limit errors."""
    provider = OpenAICompositionProvider(
        api_key="sk-test-key",
        max_transient_retries=4,
        initial_backoff=0.01,
        backoff_factor=2.0,
    )

    err_429 = Exception("Rate limit exceeded")
    err_429.status_code = 429

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "After 429", "bpm": 120},
        "intent": {"style": "fantasy", "mood": ["epic"]},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [],
        "patterns": [],
        "sequence": ["A"],
        "loop_point": 0,
    }
    mock_completion = MagicMock()
    mock_completion.id = "resp-429-ok"
    mock_completion.choices = [mock_choice]

    # Two 429 failures, then success on attempt 3
    mock_client.beta.chat.completions.parse.side_effect = [err_429, err_429, mock_completion]

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    sleep_calls = []
    with patch.dict(sys.modules, {"openai": mock_openai}), patch("time.sleep", side_effect=sleep_calls.append):
        req = CompositionRequest(style="fantasy")
        result = provider.generate_composition(req)

    assert result["metadata"]["title"] == "After 429"
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(0.01, abs=0.005)
    assert sleep_calls[1] == pytest.approx(0.02, abs=0.005)
    assert mock_client.beta.chat.completions.parse.call_count == 3


def test_openai_exhausts_transient_retries_and_raises():
    """Provider raises AIProviderAPIError after all transient retries are exhausted."""
    provider = OpenAICompositionProvider(
        api_key="sk-test-key",
        max_transient_retries=3,
        initial_backoff=0.001,
        backoff_factor=2.0,
    )

    err_503 = Exception("503 Service Unavailable")
    err_503.status_code = 503

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = err_503

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    sleep_calls = []
    with patch.dict(sys.modules, {"openai": mock_openai}), patch("time.sleep", side_effect=sleep_calls.append):
        req = CompositionRequest(style="dungeon")
        with pytest.raises(AIProviderAPIError) as exc_info:
            provider.generate_composition(req)

    assert "503" in str(exc_info.value)
    assert len(sleep_calls) == 2  # 3 attempts = 2 backoff sleeps between them
    assert mock_client.beta.chat.completions.parse.call_count == 3


def test_non_transient_error_does_not_retry():
    """Non-transient errors (e.g. 400 Bad Request) do not sleep or retry."""
    provider = OpenAICompositionProvider(
        api_key="sk-test-key",
        max_transient_retries=3,
        initial_backoff=1.0,
    )

    err_400 = Exception("400 Bad Request: Invalid model")
    err_400.status_code = 400

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = err_400
    mock_client.chat.completions.create.side_effect = err_400

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    sleep_calls = []
    with patch.dict(sys.modules, {"openai": mock_openai}), patch("time.sleep", side_effect=sleep_calls.append):
        req = CompositionRequest(style="dungeon")
        with pytest.raises(AIProviderAPIError):
            provider.generate_composition(req)

    assert len(sleep_calls) == 0  # No sleeping on non-transient errors
