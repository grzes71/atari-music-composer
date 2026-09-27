"""Centralized logging configuration for Atari Music Composer.

Provides:
- Standard log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL.
- Central setup_logging() function configurable via code, environment variable, or CLI.
- Safe redaction of sensitive credentials (API keys, Authorization headers, Bearer tokens).
- Stream direction to stderr by default to preserve stdout for machine-readable outputs and pipes.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import sys
from typing import Any, Collection, Dict, List, Optional, Set, TextIO, Union

# Standard supported log level names
LOG_LEVEL_NAMES: List[str] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LOG_LEVEL_MAP: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}

DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%H:%M:%S"

# Global set of sensitive string values to automatically redact
_REGISTERED_SECRETS: Set[str] = set()

# Regex to detect common API key and token patterns
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{8,}", re.IGNORECASE),
    re.compile(r"('api_key':\s*['\"])[^'\"]+(['\"])", re.IGNORECASE),
    re.compile(r'("api_key":\s*["\'])[^"\']+(["\'])', re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
]


def mask_secret(secret: Optional[str], visible_chars: int = 4) -> str:
    """Return a masked representation of a secret string."""
    if not secret:
        return "(not set)"
    clean = str(secret).strip()
    if clean in ("your_api_key_here", "dummy_key", ""):
        return f"(placeholder: {clean})"
    if len(clean) <= visible_chars * 2:
        return "******"
    return f"{clean[:visible_chars]}...{clean[-visible_chars:]}"


def register_secret(secret: Optional[str]) -> None:
    """Register a secret value to be automatically masked in all log outputs."""
    if secret:
        clean = str(secret).strip()
        if len(clean) >= 6 and clean not in ("your_api_key_here", "dummy_key"):
            _REGISTERED_SECRETS.add(clean)


def clear_registered_secrets() -> None:
    """Clear all registered secrets (useful in tests)."""
    _REGISTERED_SECRETS.clear()


def redact_text(text: str) -> str:
    """Redact known secrets and common sensitive patterns from text."""
    if not text:
        return text

    redacted = text
    # 1. Mask explicitly registered secrets
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        if secret in redacted:
            redacted = redacted.replace(secret, mask_secret(secret))

    # 2. Mask via heuristic patterns
    def _mask_sk_match(m: re.Match) -> str:
        val = m.group(0)
        return mask_secret(val)

    redacted = re.sub(r"sk-[a-zA-Z0-9_\-]{8,}", _mask_sk_match, redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        r"(Bearer\s+)[a-zA-Z0-9_\-\.]{8,}",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"(Authorization:\s*Bearer\s+)[a-zA-Z0-9_\-\.]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def sanitize_for_logging(data: Any, secrets: Optional[Collection[str]] = None) -> Any:
    """Recursively sanitize data structures (dicts, lists, strings) for safe logging.
    
    Masks values for keys related to secrets, tokens, passwords, authorization.
    """
    sensitive_keys = {
        "api_key",
        "apikey",
        "authorization",
        "secret",
        "password",
        "token",
        "access_token",
        "bearer",
    }

    if secrets:
        for s in secrets:
            register_secret(s)

    if isinstance(data, dict):
        clean_dict: Dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower().replace("-", "_")
            if any(sens in k_lower for sens in sensitive_keys):
                if isinstance(v, str):
                    clean_dict[k] = mask_secret(v)
                else:
                    clean_dict[k] = "[REDACTED]"
            else:
                clean_dict[k] = sanitize_for_logging(v, secrets)
        return clean_dict
    elif isinstance(data, list):
        return [sanitize_for_logging(item, secrets) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_for_logging(item, secrets) for item in data)
    elif isinstance(data, str):
        return redact_text(data)
    else:
        return data


class RedactingFormatter(logging.Formatter):
    """Logging Formatter that guarantees secrets and tokens are redacted."""

    def format(self, record: logging.LogRecord) -> str:
        # Create a shallow copy or format the message safely
        orig_msg = record.msg
        orig_args = record.args

        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = sanitize_for_logging(record.args)
                elif isinstance(record.args, (list, tuple)):
                    record.args = tuple(
                        redact_text(str(a)) if isinstance(a, str) else sanitize_for_logging(a)
                        for a in record.args
                    )
            formatted = super().format(record)
            return redact_text(formatted)
        finally:
            record.msg = orig_msg
            record.args = orig_args


def normalize_log_level(level: Optional[Union[str, int]] = None, default: str = DEFAULT_LOG_LEVEL) -> int:
    """Resolve and validate a log level string or int to a standard logging int.
    
    Parameters
    ----------
    level : Optional[Union[str, int]]
        Desired level name (e.g. 'DEBUG', 'info') or int (e.g. logging.DEBUG).
    default : str, default='WARNING'
        Default level name if level is None.
        
    Returns
    -------
    int
        logging level integer.
        
    Raises
    ------
    ValueError
        If level string is unknown.
    """
    if level is None:
        env_val = os.environ.get("LOG_LEVEL")
        if env_val:
            candidate = env_val.strip().upper()
        else:
            candidate = default.strip().upper()
    elif isinstance(level, int):
        return level
    else:
        candidate = str(level).strip().upper()

    if candidate not in LOG_LEVEL_MAP:
        raise ValueError(
            f"Invalid LOG_LEVEL '{level}'. Supported levels: {LOG_LEVEL_NAMES}"
        )
    return LOG_LEVEL_MAP[candidate]


def setup_logging(
    level: Optional[Union[str, int]] = None,
    stream: Optional[TextIO] = None,
    log_format: Optional[str] = None,
    date_format: Optional[str] = None,
    force: bool = True,
) -> logging.Logger:
    """Centrally configure Python standard logging for the project.
    
    Parameters
    ----------
    level : Optional[Union[str, int]]
        Log level name ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL') or integer.
        If None, resolves from LOG_LEVEL environment variable, defaulting to 'WARNING'.
    stream : Optional[TextIO]
        Output stream for logs. Defaults to sys.stderr so stdout remains clean.
    log_format : Optional[str]
        Logging format string.
    date_format : Optional[str]
        Date format string.
    force : bool
        If True, reconfigures existing handlers and adjusts levels dynamically.
        
    Returns
    -------
    logging.Logger
        Root logger instance.
    """
    int_level = normalize_log_level(level)
    target_stream = stream if stream is not None else sys.stderr

    formatter = RedactingFormatter(
        fmt=log_format or DEFAULT_LOG_FORMAT,
        datefmt=date_format or DEFAULT_DATE_FORMAT,
    )

    root_logger = logging.getLogger()
    atari_logger = logging.getLogger("atari_music")

    if force:
        # Reconfigure root and package handlers
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)

        handler = logging.StreamHandler(target_stream)
        handler.setLevel(int_level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        # If no handlers exist, add one
        if not root_logger.handlers:
            handler = logging.StreamHandler(target_stream)
            handler.setLevel(int_level)
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)
        else:
            for h in root_logger.handlers:
                h.setLevel(int_level)
                h.setFormatter(formatter)

    root_logger.setLevel(int_level)
    atari_logger.setLevel(int_level)

    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Retrieve a standard logger for a module, prefixed under project hierarchy."""
    if not name:
        return logging.getLogger("atari_music")
    if name.startswith("atari_music"):
        return logging.getLogger(name)
    return logging.getLogger(f"atari_music.{name}")
