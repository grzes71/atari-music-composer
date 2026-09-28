"""Configuration Management with Hierarchical Priority Overrides.

Hierarchy of priorities:
1) CLI argument (highest - explicit override)
2) System environment variable
3) .env file value (via python-dotenv)
4) Code default (lowest)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from dotenv import dotenv_values


class ConfigError(Exception):
    """Base exception for configuration errors."""
    pass


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails (e.g., missing API key)."""
    pass


# Default placeholder value to recognize unconfigured keys
PLACEHOLDER_KEY = "your_api_key_here"


@dataclass
class Config:
    """Application configuration bundle with provenance tracking."""

    ai_provider: str = "deepseek"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-flash"
    log_level: str = "INFO"
    env_file: Optional[Path] = None

    # Track which source supplied each value (CLI argument, System environment, .env file, Code default)
    sources: Dict[str, str] = field(default_factory=dict)

    def __init__(
        self,
        ai_provider: Optional[str] = None,
        ai_api_key: Optional[str] = None,
        ai_base_url: Optional[str] = None,
        ai_model: Optional[str] = None,
        log_level: Optional[str] = None,
        env_file: Optional[Path] = None,
        sources: Optional[Dict[str, str]] = None,
        # Backward compatibility kwargs:
        deepseek_api_key: Optional[str] = None,
        deepseek_base_url: Optional[str] = None,
        deepseek_model: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.ai_provider = ai_provider if ai_provider is not None else "deepseek"
        self.ai_api_key = ai_api_key if ai_api_key is not None else (deepseek_api_key or "")
        self.ai_base_url = (
            ai_base_url
            if ai_base_url is not None
            else (deepseek_base_url or "https://api.deepseek.com")
        )
        self.ai_model = (
            ai_model
            if ai_model is not None
            else (deepseek_model or "deepseek-flash")
        )
        self.log_level = (log_level if log_level is not None else "INFO").upper()
        self.env_file = env_file
        self.sources = sources if sources is not None else {}

    # Backward compatibility properties
    @property
    def deepseek_api_key(self) -> str:
        return self.ai_api_key

    @deepseek_api_key.setter
    def deepseek_api_key(self, value: str) -> None:
        self.ai_api_key = value

    @property
    def deepseek_base_url(self) -> str:
        return self.ai_base_url

    @deepseek_base_url.setter
    def deepseek_base_url(self, value: str) -> None:
        self.ai_base_url = value

    @property
    def deepseek_model(self) -> str:
        return self.ai_model

    @deepseek_model.setter
    def deepseek_model(self, value: str) -> None:
        self.ai_model = value

    def validate(self) -> None:
        """Validate configuration values.

        Raises
        ------
        ConfigValidationError
            If AI_API_KEY is missing, empty, or set to placeholder.
        """
        key = (self.ai_api_key or "").strip()
        if not key or key == PLACEHOLDER_KEY:
            raise ConfigValidationError(
                "AI_API_KEY is not configured!\n\n"
                "Please provide a valid AI API key using one of the following methods:\n"
                "  1) Command-line argument:    python check_config.py --api-key <YOUR_KEY>\n"
                "  2) Environment variable:     export AI_API_KEY=<YOUR_KEY>\n"
                "  3) In your .env file:        AI_API_KEY=<YOUR_KEY>\n\n"
                "Legacy keys DEEPSEEK_API_KEY and OPENAI_API_KEY are also supported for backward compatibility."
            )

        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_log_levels:
            raise ConfigValidationError(
                f"Invalid LOG_LEVEL '{self.log_level}'. Allowed values: {sorted(valid_log_levels)}"
            )

    def masked_api_key(self, visible_chars: int = 4) -> str:
        """Return API key with middle characters masked for safe logging/display."""
        key = self.ai_api_key or ""
        if not key:
            return "(not set)"
        if key == PLACEHOLDER_KEY:
            return f"(placeholder: {PLACEHOLDER_KEY})"
        if len(key) <= visible_chars * 2:
            return "******"
        return f"{key[:visible_chars]}...{key[-visible_chars:]}"

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as a dictionary."""
        return {
            "ai_provider": self.ai_provider,
            "ai_api_key": self.ai_api_key,
            "ai_base_url": self.ai_base_url,
            "ai_model": self.ai_model,
            "log_level": self.log_level,
            "env_file": str(self.env_file) if self.env_file else None,
            "sources": self.sources,
            "deepseek_api_key": self.ai_api_key,
            "deepseek_base_url": self.ai_base_url,
            "deepseek_model": self.ai_model,
        }

    @classmethod
    def from_args(
        cls,
        args: Optional[Union[Sequence[str], argparse.Namespace]] = None,
        env_path: Union[str, Path] = ".env",
        validate: bool = False,
    ) -> Config:
        """Create a Config instance resolved according to the 4-level priority chain.

        Priority order (highest to lowest):
        1) Command-line arguments
        2) System environment variables
        3) .env file values
        4) Code defaults

        Parameters
        ----------
        args : Optional[Union[Sequence[str], argparse.Namespace]]
            CLI argument list (e.g. sys.argv[1:]) or parsed Namespace. If None, parses sys.argv[1:].
        env_path : Union[str, Path]
            Path to .env file (default: ".env").
        validate : bool
            If True, runs validate() and raises ConfigValidationError on error.
        """
        # Parse CLI arguments if needed
        if isinstance(args, argparse.Namespace):
            parsed_args = args
        else:
            parser = create_arg_parser()
            parsed_args = parser.parse_args(args=args)

        # Allow CLI --env-file override if provided
        cli_env_file = getattr(parsed_args, "env_file", None)
        actual_env_path = Path(cli_env_file or env_path)

        # Load values from .env file (without modifying os.environ)
        env_file_values: Dict[str, Optional[str]] = {}
        resolved_env_file: Optional[Path] = None
        if actual_env_path.exists() and actual_env_path.is_file():
            env_file_values = dotenv_values(dotenv_path=actual_env_path)
            resolved_env_file = actual_env_path
        else:
            warnings.warn(
                f"Configuration file '{actual_env_path}' not found. "
                "Falling back to system environment variables and code defaults.",
                UserWarning,
                stacklevel=2,
            )

        sources: Dict[str, str] = {}

        def resolve_setting(
            cli_val: Optional[Any],
            canonical_name: str,
            fallback_names: Sequence[str],
            code_default: Any,
        ) -> Any:
            """Resolve setting following: CLI arg -> System Env -> .env file -> Code Default."""
            # 1) CLI argument (highest priority)
            if cli_val is not None and str(cli_val).strip() != "":
                sources[canonical_name] = "1) CLI argument"
                for fb in fallback_names:
                    sources[fb] = "1) CLI argument"
                return cli_val

            # 2) System environment variable (never overwritten by .env)
            sys_val = os.environ.get(canonical_name)
            if sys_val is not None and sys_val != "":
                sources[canonical_name] = "2) System environment"
                for fb in fallback_names:
                    sources[fb] = "2) System environment"
                return sys_val

            for fb in fallback_names:
                fb_val = os.environ.get(fb)
                if fb_val is not None and fb_val != "":
                    sources[canonical_name] = "2) System environment"
                    for fbb in fallback_names:
                        sources[fbb] = "2) System environment"
                    return fb_val

            # 3) Value from .env file
            file_val = env_file_values.get(canonical_name)
            if file_val is not None and file_val != "":
                sources[canonical_name] = "3) .env file"
                for fb in fallback_names:
                    sources[fb] = "3) .env file"
                return file_val

            for fb in fallback_names:
                fb_file_val = env_file_values.get(fb)
                if fb_file_val is not None and fb_file_val != "":
                    sources[canonical_name] = "3) .env file"
                    for fbb in fallback_names:
                        sources[fbb] = "3) .env file"
                    return fb_file_val

            # 4) Code default (lowest priority)
            sources[canonical_name] = "4) Code default"
            for fb in fallback_names:
                sources[fb] = "4) Code default"
            return code_default

        ai_provider = str(
            resolve_setting(
                getattr(parsed_args, "provider", None),
                "AI_PROVIDER",
                ["DEEPSEEK_PROVIDER"],
                "deepseek",
            )
        )
        ai_api_key = str(
            resolve_setting(
                getattr(parsed_args, "api_key", None),
                "AI_API_KEY",
                ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"],
                "",
            )
        )
        ai_base_url = str(
            resolve_setting(
                getattr(parsed_args, "base_url", None),
                "AI_BASE_URL",
                ["DEEPSEEK_BASE_URL", "OPENAI_BASE_URL"],
                "https://api.deepseek.com",
            )
        )
        ai_model = str(
            resolve_setting(
                getattr(parsed_args, "model", None),
                "AI_MODEL",
                ["DEEPSEEK_MODEL", "OPENAI_MODEL"],
                "deepseek-flash",
            )
        )
        log_level = str(
            resolve_setting(
                getattr(parsed_args, "log_level", None),
                "LOG_LEVEL",
                [],
                "INFO",
            )
        ).upper()

        config = cls(
            ai_provider=ai_provider,
            ai_api_key=ai_api_key,
            ai_base_url=ai_base_url,
            ai_model=ai_model,
            log_level=log_level,
            env_file=resolved_env_file,
            sources=sources,
        )

        if validate:
            config.validate()

        return config


def create_arg_parser() -> argparse.ArgumentParser:
    """Create and return an ArgumentParser for configuration overrides."""
    parser = argparse.ArgumentParser(
        description="Atari Music AI Application Configuration",
        argument_default=None,
    )
    parser.add_argument(
        "--provider",
        dest="provider",
        type=str,
        default=None,
        help="AI provider name (overrides AI_PROVIDER, default: deepseek)",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        default=None,
        help="AI API key (overrides AI_API_KEY / DEEPSEEK_API_KEY)",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        type=str,
        default=None,
        help="AI API base URL (overrides AI_BASE_URL / DEEPSEEK_BASE_URL, default: https://api.deepseek.com)",
    )
    parser.add_argument(
        "--model",
        dest="model",
        type=str,
        default=None,
        help="AI model name (overrides AI_MODEL / DEEPSEEK_MODEL, e.g. deepseek-flash)",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Application logging level (overrides LOG_LEVEL, default: INFO)",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file",
        type=str,
        default=None,
        help="Path to .env file to load (default: .env)",
    )
    return parser
