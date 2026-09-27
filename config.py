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

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    log_level: str = "INFO"

    # Track which source supplied each value (CLI argument, System environment, .env file, Code default)
    sources: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate configuration values.
        
        Raises
        ------
        ConfigValidationError
            If DEEPSEEK_API_KEY is missing, empty, or set to placeholder.
        """
        key = (self.deepseek_api_key or "").strip()
        if not key or key == PLACEHOLDER_KEY:
            raise ConfigValidationError(
                "DEEPSEEK_API_KEY is not configured!\n\n"
                "Please provide a valid DeepSeek API key using one of the following methods:\n"
                "  1) Command-line argument:    python check_config.py --api-key <YOUR_KEY>\n"
                "  2) Environment variable:     export DEEPSEEK_API_KEY=<YOUR_KEY>\n"
                "  3) In your .env file:        DEEPSEEK_API_KEY=<YOUR_KEY>\n\n"
                "Get your DeepSeek API key at: https://platform.deepseek.com"
            )

        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_log_levels:
            raise ConfigValidationError(
                f"Invalid LOG_LEVEL '{self.log_level}'. Allowed values: {sorted(valid_log_levels)}"
            )

    def masked_api_key(self, visible_chars: int = 4) -> str:
        """Return API key with middle characters masked for safe logging/display."""
        key = self.deepseek_api_key or ""
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
            "deepseek_api_key": self.deepseek_api_key,
            "deepseek_base_url": self.deepseek_base_url,
            "deepseek_model": self.deepseek_model,
            "log_level": self.log_level,
            "sources": self.sources,
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
        actual_env_path = Path(getattr(parsed_args, "env_file", None) or env_path)

        # Load values from .env file (without modifying os.environ)
        env_file_values: Dict[str, Optional[str]] = {}
        if actual_env_path.exists() and actual_env_path.is_file():
            env_file_values = dotenv_values(dotenv_path=actual_env_path)
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
            env_var_name: str,
            code_default: Any,
        ) -> Any:
            """Resolve setting following: CLI arg -> System Env -> .env file -> Code Default."""
            # 1) CLI argument (highest priority)
            if cli_val is not None:
                sources[env_var_name] = "1) CLI argument"
                return cli_val

            # 2) System environment variable
            sys_val = os.environ.get(env_var_name)
            if sys_val is not None and sys_val != "":
                sources[env_var_name] = "2) System environment"
                return sys_val

            # 3) Value from .env file
            file_val = env_file_values.get(env_var_name)
            if file_val is not None and file_val != "":
                sources[env_var_name] = "3) .env file"
                return file_val

            # 4) Code default (lowest priority)
            sources[env_var_name] = "4) Code default"
            return code_default

        config = cls(
            deepseek_api_key=str(
                resolve_setting(
                    getattr(parsed_args, "api_key", None),
                    "DEEPSEEK_API_KEY",
                    "",
                )
            ),
            deepseek_base_url=str(
                resolve_setting(
                    getattr(parsed_args, "base_url", None),
                    "DEEPSEEK_BASE_URL",
                    "https://api.deepseek.com",
                )
            ),
            deepseek_model=str(
                resolve_setting(
                    getattr(parsed_args, "model", None),
                    "DEEPSEEK_MODEL",
                    "deepseek-flash",
                )
            ),
            log_level=str(
                resolve_setting(
                    getattr(parsed_args, "log_level", None),
                    "LOG_LEVEL",
                    "INFO",
                )
            ).upper(),
            sources=sources,
        )

        if validate:
            config.validate()

        return config


def create_arg_parser() -> argparse.ArgumentParser:
    """Create and return an ArgumentParser for configuration overrides."""
    parser = argparse.ArgumentParser(
        description="Atari Music / DeepSeek Application Configuration",
        argument_default=None,
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        default=None,
        help="DeepSeek API key (overrides DEEPSEEK_API_KEY from env / .env)",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        type=str,
        default=None,
        help="DeepSeek API base URL (overrides DEEPSEEK_BASE_URL, default: https://api.deepseek.com)",
    )
    parser.add_argument(
        "--model",
        dest="model",
        type=str,
        default=None,
        help="DeepSeek model name (overrides DEEPSEEK_MODEL, e.g. deepseek-flash, deepseek-v4-pro)",
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
