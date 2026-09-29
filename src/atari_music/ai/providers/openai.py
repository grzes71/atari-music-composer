import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from atari_music.ai.prompts import (
    build_dsl_system_prompt,
    build_dsl_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from atari_music.ai.providers.base import AICompositionProvider, CompositionRequest
from atari_music.ai.schema import (
    AICompositionDoc,
    AIProviderAPIError,
    AIProviderDependencyError,
    AIProviderMissingKeyError,
    AIProviderStructuredOutputError,
)
from atari_music.logging_config import mask_secret, register_secret, sanitize_for_logging

logger = logging.getLogger(__name__)


def _sanitize_endpoint(url: Optional[str]) -> str:
    """Return sanitized endpoint URL without embedded user credentials or query secrets."""
    if not url:
        return "https://api.openai.com/v1"
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return url


def _is_transient_http_error(err: Exception) -> Tuple[bool, int, str]:
    """Determine if an exception represents a transient HTTP error (e.g. 503 or 429).

    Returns
    -------
    tuple[bool, int, str]
        (is_transient, status_code, description)
    """
    status = getattr(err, "status_code", None)
    if status is None:
        resp = getattr(err, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)

    if status == 429:
        return True, 429, "Rate Limit Exceeded (HTTP 429)"
    if status == 503:
        return True, 503, "Service Unavailable / Server Congested (HTTP 503)"
    if status in (502, 504, 520, 521, 522, 524):
        return True, status, f"Gateway / Server Error (HTTP {status})"

    cls_name = type(err).__name__
    if cls_name == "RateLimitError":
        return True, 429, "Rate Limit Exceeded (RateLimitError)"
    if cls_name in ("InternalServerError", "APITimeoutError", "APIConnectionError"):
        msg = str(err).lower()
        if "429" in msg or "rate limit" in msg:
            return True, 429, "Rate Limit Exceeded (HTTP 429)"
        return True, status or 503, f"Transient Server Error ({cls_name})"

    err_lower = str(err).lower()
    if "503" in err_lower or "service unavailable" in err_lower or "server overloaded" in err_lower:
        return True, 503, "Service Unavailable (HTTP 503)"
    if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
        return True, 429, "Rate Limit Exceeded (HTTP 429)"

    return False, 0, ""


def extract_retry_delay(
    err: Optional[Exception],
    default_backoff: float,
    max_delay: float = 300.0,
    safety_margin: float = 1.0,
) -> float:
    """Extract server-requested retry delay from headers or error message.

    Supports:
    1. HTTP 'Retry-After' (seconds) and 'Retry-After-Ms' (milliseconds) response headers.
    2. Google / OpenAI RPC RetryInfo in error response details (e.g. retryDelay: '57.489879459s').
    3. Natural language strings in error message, such as:
       - 'Please retry in 57.489879459s'
       - 'retry in 35.18s'
       - 'retry after 20s' / 'retry after 20 seconds'
       - 'try again in 15 seconds'
       - 'wait 10s' / 'reset in 10s'

    If a server-specified delay is detected, adds safety_margin (default 1.0s) so the retry
    strictly occurs after the server's rate-limit window resets, bounded by max_delay.
    If no server delay is detected, returns default_backoff.
    """
    if err is None:
        return default_backoff

    candidates = [err]
    cause = getattr(err, "__cause__", None)
    if cause is not None and isinstance(cause, Exception):
        candidates.append(cause)
    context = getattr(err, "__context__", None)
    if context is not None and isinstance(context, Exception):
        candidates.append(context)

    for target in candidates:
        # 1. HTTP response headers
        response = getattr(target, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                val_header = headers.get("retry-after") or headers.get("Retry-After")
                if val_header:
                    try:
                        parsed_val = float(val_header)
                        return min(max_delay, max(0.5, parsed_val + safety_margin))
                    except (ValueError, TypeError):
                        pass

                val_ms = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
                if val_ms:
                    try:
                        parsed_ms = float(val_ms) / 1000.0
                        return min(max_delay, max(0.5, parsed_ms + safety_margin))
                    except (ValueError, TypeError):
                        pass

        # 2. Structured error body (OpenAI / Google Cloud RPC)
        body = getattr(target, "body", None)
        if isinstance(body, dict):
            err_dict = body.get("error", {})
            if isinstance(err_dict, dict):
                details = err_dict.get("details", [])
                if isinstance(details, list):
                    for item in details:
                        if isinstance(item, dict) and "retryDelay" in item:
                            raw_rd = str(item["retryDelay"]).rstrip("s")
                            try:
                                parsed_rd = float(raw_rd)
                                return min(max_delay, max(0.5, parsed_rd + safety_margin))
                            except (ValueError, TypeError):
                                pass

        # 3. Regex inspection of error message string
        msg = str(target)
        patterns = [
            r"retry\s+in\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
            r"retry\s+after\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
            r"try\s+again\s+in\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
            r"retrydelay['\":\s]+(\d+(?:\.\d+)?)\s*s?",
            r"wait\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
            r"reset\s+in\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, msg, re.IGNORECASE)
            if match:
                try:
                    parsed_sec = float(match.group(1))
                    return min(max_delay, max(0.5, parsed_sec + safety_margin))
                except (ValueError, TypeError):
                    pass

    return default_backoff


class OpenAICompositionProvider(AICompositionProvider):
    """Generates Atari music composition JSON via OpenAI-compatible Chat Completions API with exponential backoff on 503/429."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_transient_retries: int = 4,
        initial_backoff: float = 5.0,
        backoff_factor: float = 2.0,
        max_backoff: float = 30.0,
        max_server_wait: float = 300.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("AI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.base_url = (
            base_url
            or os.environ.get("AI_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        self.model = (
            model
            or os.environ.get("AI_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "deepseek-flash"
        )
        self.max_transient_retries = max(
            1, int(os.environ.get("AI_MAX_TRANSIENT_RETRIES", max_transient_retries))
        )
        self.initial_backoff = float(os.environ.get("AI_INITIAL_BACKOFF", initial_backoff))
        self.backoff_factor = float(os.environ.get("AI_BACKOFF_FACTOR", backoff_factor))
        self.max_backoff = float(os.environ.get("AI_MAX_BACKOFF", max_backoff))
        self.max_server_wait = float(os.environ.get("AI_MAX_SERVER_WAIT", max_server_wait))
        self.last_usage: Optional[Dict[str, int]] = None
        self.usage_history: list[Dict[str, int]] = []

        if self.api_key:
            register_secret(self.api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def __repr__(self) -> str:
        masked = f"...{self.api_key[-4:]}" if self.api_key and len(self.api_key) >= 4 else "None"
        clean_base = _sanitize_endpoint(self.base_url)
        return f"OpenAICompositionProvider(model={self.model!r}, base_url={clean_base!r}, api_key={masked!r})"

    def _sanitize_error_message(self, err_text: str) -> str:
        """Mask API key in error messages."""
        if self.api_key and self.api_key in err_text:
            return err_text.replace(self.api_key, "******")
        return err_text

    def _get_client(self):
        """Instantiate configured OpenAI client instance."""
        if not self.api_key or self.api_key.strip() == "your_api_key_here":
            raise AIProviderMissingKeyError(
                "API key is not configured. Provide AI_API_KEY (or DEEPSEEK_API_KEY / OPENAI_API_KEY) in .env or environment."
            )

        try:
            import openai
        except ImportError as err:
            raise AIProviderDependencyError(
                "The 'openai' Python package is not installed. Install it with 'pip install openai' to use this provider."
            ) from err

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        return openai.OpenAI(**client_kwargs)

    def generate_composition(
        self,
        request: CompositionRequest,
        feedback: Optional[str] = None,
        previous_composition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        client = self._get_client()

        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(request)
        response_id: Optional[str] = None
        doc_dict: Optional[Dict[str, Any]] = None

        if feedback:
            repair_content = (
                f"{feedback}\n\n"
                f"Previous composition JSON to repair:\n"
                f"{json.dumps(previous_composition, indent=2) if previous_composition else '{}'}\n\n"
                f"Remember: Preserve all valid parts of the existing composition. "
                f"Modify ONLY what is necessary to resolve the reported validation errors. "
                f"Return the complete corrected composition matching the required schema."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": json.dumps(previous_composition, indent=2) if previous_composition else "{}"},
                {"role": "user", "content": repair_content},
            ]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

        # Diagnostic request logging (DEBUG)
        endpoint = _sanitize_endpoint(self.base_url)
        roles = [m.get("role", "unknown") for m in messages]
        request_params = {
            "endpoint": endpoint,
            "model": self.model,
            "messages_count": len(messages),
            "roles": roles,
            "has_feedback": bool(feedback),
        }
        logger.debug(
            "LLM API Request -> Endpoint: %s | Model: %s | Messages: %d | Roles: %s",
            endpoint,
            self.model,
            len(messages),
            roles,
        )
        logger.debug("LLM API Request Parameters: %s", request_params)

        # Full sanitized payload
        safe_payload = sanitize_for_logging({
            "model": self.model,
            "messages": messages,
            "endpoint": endpoint,
        })
        logger.debug("LLM API Request Payload:\n%s", json.dumps(safe_payload, indent=2))

        # Transient error retry loop with exponential backoff (for 503 / 429)
        for transient_attempt in range(1, self.max_transient_retries + 1):
            parsed_ok = False
            first_err: Optional[Exception] = None
            try:
                # Primary path: Native Structured Outputs via beta.chat.completions.parse
                if hasattr(client, "beta") and hasattr(client.beta, "chat") and hasattr(client.beta.chat, "completions"):
                    try:
                        logger.debug(
                            "Attempting Structured Output parsing via beta.chat.completions.parse (schema=%s)...",
                            AICompositionDoc.__name__,
                        )
                        completion = client.beta.chat.completions.parse(
                            model=self.model,
                            messages=messages,
                            response_format=AICompositionDoc,
                        )
                        response_id = getattr(completion, "id", None)
                        choice = completion.choices[0]
                        raw_content = choice.message.content or ""
                        response_size = len(raw_content) if raw_content else len(str(getattr(choice.message, "parsed", "")))
                        logger.debug(
                            "LLM API Response received [id=%s]: size ~%d chars",
                            response_id,
                            response_size,
                        )

                        usage_obj = getattr(completion, "usage", None)
                        if usage_obj is not None:
                            u_dict = {
                                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                                "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                                "total_tokens": getattr(usage_obj, "total_tokens", 0),
                            }
                            self.last_usage = u_dict
                            self.usage_history.append(u_dict)

                        if getattr(choice.message, "refusal", None):
                            raise AIProviderAPIError(f"Model refused request: {choice.message.refusal}")

                        if getattr(choice.message, "parsed", None) is not None:
                            parsed_doc = choice.message.parsed
                            if isinstance(parsed_doc, AICompositionDoc):
                                doc_dict = parsed_doc.model_dump(mode="json")
                            elif isinstance(parsed_doc, dict):
                                doc_dict = parsed_doc
                            parsed_ok = True
                            logger.debug(
                                "Structured Output parsed successfully via beta.parse: %d patterns, %d sequence steps",
                                len(doc_dict.get("patterns", [])) if doc_dict else 0,
                                len(doc_dict.get("sequence", [])) if doc_dict else 0,
                            )
                        elif choice.message.content:
                            doc_dict = self._parse_json_content(choice.message.content)
                            parsed_ok = True
                    except (AIProviderAPIError, AIProviderStructuredOutputError):
                        raise
                    except Exception as err:
                        is_trans, _, _ = _is_transient_http_error(err)
                        if is_trans:
                            # Re-raise transient errors immediately to trigger backoff rather than immediate secondary failure
                            raise err
                        first_err = err
                        parsed_ok = False
                        logger.debug("Primary Structured Output parse failed: %s; falling back to json_object", err)

                if not parsed_ok:
                    try:
                        # Secondary path: Standard JSON object completion
                        logger.debug("Requesting JSON object completion via chat.completions.create fallback...")
                        response = client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            response_format={"type": "json_object"},
                            temperature=0.7,
                        )
                        response_id = getattr(response, "id", None)
                        usage_obj = getattr(response, "usage", None)
                        if usage_obj is not None:
                            u_dict = {
                                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                                "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                                "total_tokens": getattr(usage_obj, "total_tokens", 0),
                            }
                            self.last_usage = u_dict
                            self.usage_history.append(u_dict)

                        choice = response.choices[0]
                        raw_content = choice.message.content or "{}"
                        logger.debug(
                            "LLM API Fallback Response received [id=%s]: size=%d chars",
                            response_id,
                            len(raw_content),
                        )
                        doc_dict = self._parse_json_content(raw_content)
                        logger.debug(
                            "Fallback JSON parsed successfully: %d patterns, %d sequence steps",
                            len(doc_dict.get("patterns", [])) if doc_dict else 0,
                            len(doc_dict.get("sequence", [])) if doc_dict else 0,
                        )
                    except Exception as fallback_err:
                        is_trans, _, _ = _is_transient_http_error(fallback_err)
                        if is_trans:
                            raise fallback_err
                        if first_err is not None:
                            raise first_err from fallback_err
                        raise fallback_err

                # Succeeded: break out of the transient retry loop
                break

            except (AIProviderStructuredOutputError,):
                raise
            except Exception as err:
                is_trans, code, desc = _is_transient_http_error(err)
                if is_trans and transient_attempt < self.max_transient_retries:
                    base_delay = min(
                        self.max_backoff,
                        self.initial_backoff * (self.backoff_factor ** (transient_attempt - 1)),
                    )
                    delay = extract_retry_delay(
                        err,
                        default_backoff=base_delay,
                        max_delay=self.max_server_wait,
                    )
                    clean_msg = self._sanitize_error_message(str(err))
                    source = "server retryDelay" if delay != base_delay else "exponential backoff"
                    logger.warning(
                        "LLM API transient error [%s / code %s]: %s. "
                        "Waiting %.1fs (%s) before retry (attempt %d/%d)...",
                        desc,
                        code,
                        clean_msg,
                        delay,
                        source,
                        transient_attempt,
                        self.max_transient_retries,
                    )
                    time.sleep(delay)
                    continue

                err_msg = self._sanitize_error_message(str(err))
                raise AIProviderAPIError(f"API request failed: {err_msg}") from err

        if not isinstance(doc_dict, dict):
            raise AIProviderStructuredOutputError("Provider failed to produce a valid composition dictionary.")

        # Attach provenance
        if "provenance" not in doc_dict or not doc_dict["provenance"]:
            doc_dict["provenance"] = {
                "source": "ai",
                "provider": "openai",
                "model": self.model,
                "request_id": response_id,
            }

        return doc_dict

    def _parse_json_content(self, raw_content: str) -> Dict[str, Any]:
        """Defensive markdown-fence stripping and JSON parsing fallback."""
        logger.debug("Parsing JSON content string (raw length: %d chars)...", len(raw_content))
        cleaned = raw_content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise AIProviderStructuredOutputError(f"Expected JSON object, got {type(parsed).__name__}")
            return parsed
        except json.JSONDecodeError as err:
            logger.debug("Failed to decode JSON: %s (snippet: %s)", err, raw_content[:200])
            raise AIProviderStructuredOutputError(
                f"Failed to parse JSON response from OpenAI: {err}\nResponse snippet:\n{raw_content[:400]}"
            ) from err

    def generate_composition_dsl(
        self,
        request: CompositionRequest,
        feedback: Optional[str] = None,
        previous_dsl: Optional[str] = None,
    ) -> str:
        """Generate raw Music DSL text from OpenAI provider."""
        client = self._get_client()

        system_prompt = build_dsl_system_prompt()
        user_prompt = build_dsl_user_prompt(request)

        if feedback:
            repair_content = (
                f"{feedback}\n\n"
                f"Previous Music DSL to repair:\n"
                f"{previous_dsl or ''}\n\n"
                f"Remember: Preserve all valid parts of the existing composition. "
                f"Modify ONLY what is necessary to resolve the reported errors. "
                f"Return ONLY the complete corrected Music DSL plain text without markdown fences."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": previous_dsl or ""},
                {"role": "user", "content": repair_content},
            ]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

        for transient_attempt in range(1, self.max_transient_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                )
                usage_obj = getattr(response, "usage", None)
                if usage_obj is not None:
                    u_dict = {
                        "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                        "total_tokens": getattr(usage_obj, "total_tokens", 0),
                    }
                    self.last_usage = u_dict
                    self.usage_history.append(u_dict)

                choice = response.choices[0]
                raw_content = choice.message.content or ""
                cleaned = raw_content.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    if len(lines) >= 2 and lines[-1].strip().startswith("```"):
                        cleaned = "\n".join(lines[1:-1]).strip()
                return cleaned
            except Exception as err:
                is_trans, code, desc = _is_transient_http_error(err)
                if is_trans and transient_attempt < self.max_transient_retries:
                    base_delay = 5.0 * (2 ** (transient_attempt - 1))
                    delay = extract_retry_delay(err, default_backoff=base_delay)
                    time.sleep(delay)
                    continue
                err_msg = self._sanitize_error_message(str(err))
                raise AIProviderAPIError(f"API request failed: {err_msg}") from err

        raise AIProviderAPIError("Failed to obtain DSL completion.")

