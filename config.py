"""Backward-compatible root shim for atari_music.config."""

from atari_music.config import (
    Config,
    ConfigError,
    ConfigValidationError,
    PLACEHOLDER_KEY,
    create_arg_parser,
)

__all__ = [
    "Config",
    "ConfigError",
    "ConfigValidationError",
    "PLACEHOLDER_KEY",
    "create_arg_parser",
]
