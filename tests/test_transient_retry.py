"""Unit tests for exponential backoff on HTTP 503 and 429 transient errors."""

import sys
from unittest.mock import MagicMock, patch
import pytest

from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.openai import (
    OpenAICompositionProvider,
    _is_transient_http_error,
    extract_retry_delay,
)
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


def test_extract_retry_delay_from_messages_headers_and_body():
    """Verify server-specified retry delays are extracted accurately from messages, headers, and body."""
    # 1. Google 429 message variants with seconds
    err1 = Exception("Resource exhausted (e.g. check quota). Please retry in 57.489879459s.")
    assert extract_retry_delay(err1, default_backoff=5.0) == pytest.approx(58.489879459, abs=0.01)

    err2 = Exception("Nadal blokada! Odczekaj jeszcze 35 sekund (Please retry in 35.180037217s).")
    assert extract_retry_delay(err2, default_backoff=5.0) == pytest.approx(36.180037217, abs=0.01)

    err3 = Exception("Rate limit reached. Retry after 20 seconds.")
    assert extract_retry_delay(err3, default_backoff=5.0) == pytest.approx(21.0, abs=0.01)

    err4 = Exception("Too many requests, try again in 15s")
    assert extract_retry_delay(err4, default_backoff=5.0) == pytest.approx(16.0, abs=0.01)

    err5 = Exception("Please wait 10s before retrying")
    assert extract_retry_delay(err5, default_backoff=5.0) == pytest.approx(11.0, abs=0.01)

    # 2. HTTP response Retry-After header
    class HeaderResponse:
        headers = {"retry-after": "45"}

    err_header = Exception("Rate limited")
    err_header.response = HeaderResponse()
    assert extract_retry_delay(err_header, default_backoff=5.0) == pytest.approx(46.0, abs=0.01)

    # 3. HTTP response Retry-After-Ms header
    class MsHeaderResponse:
        headers = {"retry-after-ms": "2500"}

    err_ms_header = Exception("Rate limited")
    err_ms_header.response = MsHeaderResponse()
    assert extract_retry_delay(err_ms_header, default_backoff=5.0) == pytest.approx(3.5, abs=0.01)

    # 4. Google RPC details in response body
    err_body = Exception("Resource exhausted")
    err_body.body = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27.5s"}],
        }
    }
    assert extract_retry_delay(err_body, default_backoff=5.0) == pytest.approx(28.5, abs=0.01)

    # 5. Wrapped cause exception
    wrapped_err = AIProviderAPIError("Wrapped failure")
    wrapped_err.__cause__ = err1
    assert extract_retry_delay(wrapped_err, default_backoff=5.0) == pytest.approx(58.489879459, abs=0.01)

    # 6. Default backoff fallback when no delay found
    err_generic = Exception("Generic 503 error without delay info")
    assert extract_retry_delay(err_generic, default_backoff=7.5) == pytest.approx(7.5, abs=0.01)


def test_openai_respects_google_retry_delay():
    """Provider waits the exact server-requested delay (+ safety margin) rather than a rigid shorter backoff."""
    provider = OpenAICompositionProvider(
        api_key="sk-test-key",
        max_transient_retries=3,
        initial_backoff=5.0,
        max_backoff=30.0,  # Even though max_backoff is 30s, server delay overrides it!
    )

    google_429_err = Exception(
        "Error code: 429 - {'error': {'message': 'Resource has been exhausted. Please retry in 57.489879459s.'}}"
    )
    google_429_err.status_code = 429

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.refusal = None
    mock_choice.message.parsed = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "Google Recovered", "bpm": 120},
        "intent": {"style": "heroic", "mood": ["epic"]},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [],
        "patterns": [],
        "sequence": ["A"],
        "loop_point": 0,
    }
    mock_completion = MagicMock()
    mock_completion.id = "resp-google-ok"
    mock_completion.choices = [mock_choice]

    mock_client.beta.chat.completions.parse.side_effect = [google_429_err, mock_completion]

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    sleep_calls = []
    with patch.dict(sys.modules, {"openai": mock_openai}), patch("time.sleep", side_effect=sleep_calls.append):
        req = CompositionRequest(style="heroic")
        result = provider.generate_composition(req)

    assert result["metadata"]["title"] == "Google Recovered"
    assert len(sleep_calls) == 1
    # Exactly ~58.49s (57.489879459 + 1.0 safety margin), NOT capped at 30.0s or starting at 5.0s!
    assert sleep_calls[0] == pytest.approx(58.489879459, abs=0.01)
    assert mock_client.beta.chat.completions.parse.call_count == 2

