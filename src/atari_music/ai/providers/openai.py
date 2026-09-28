import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from atari_music.ai.prompts import build_system_prompt, build_user_prompt
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


class OpenAICompositionProvider(AICompositionProvider):
    """Generates Atari music composition JSON via OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
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
        if self.api_key:
            register_secret(self.api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def __repr__(self) -> str:
        masked = f"...{self.api_key[-4:]}" if self.api_key and len(self.api_key) >= 4 else "None"
        clean_base = _sanitize_endpoint(self.base_url)
        return f"OpenAICompositionProvider(model={self.model!r}, base_url={clean_base!r}, api_key={masked!r})"

    def generate_composition(
        self,
        request: CompositionRequest,
        feedback: Optional[str] = None,
        previous_composition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
        client = openai.OpenAI(**client_kwargs)

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
                    if first_err is not None:
                        raise first_err from fallback_err
                    raise fallback_err

        except (AIProviderAPIError, AIProviderStructuredOutputError):
            raise
        except Exception as err:
            err_msg = str(err)
            if self.api_key and self.api_key in err_msg:
                err_msg = err_msg.replace(self.api_key, "******")
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

