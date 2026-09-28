"""AI Composition Providers package."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from atari_music.ai.providers.base import AICompositionProvider, CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.providers.openai import OpenAICompositionProvider

__all__ = [
    "AICompositionProvider",
    "CompositionRequest",
    "OpenAICompositionProvider",
    "MockAICompositionProvider",
    "get_ai_provider",
]


def get_ai_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    env_path: Optional[Union[str, Path]] = None,
) -> AICompositionProvider:
    """Factory returning the appropriate AICompositionProvider instance.

    Seamlessly integrates with the project's Config (.env and CLI priority chain)
    to auto-configure AI_PROVIDER, AI_API_KEY, AI_BASE_URL, and AI_MODEL.
    """
    # 1. Load configuration from project Config (which handles CLI > Env > .env > Default)
    default_provider = "deepseek"
    default_key = ""
    default_url = "https://api.deepseek.com"
    default_model = "deepseek-flash"

    try:
        from atari_music.config import Config
        cfg = Config.from_args(args=[], env_path=env_path or ".env", validate=False)
        default_provider = cfg.ai_provider
        default_key = cfg.ai_api_key
        default_url = cfg.ai_base_url
        default_model = cfg.ai_model
    except Exception:
        pass

    # Fallbacks in case config resolution was bypassed or unpopulated
    if not default_key:
        default_key = (
            os.environ.get("AI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
    if not default_url or default_url == "https://api.deepseek.com":
        env_url = (
            os.environ.get("AI_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if env_url:
            default_url = env_url
    if not default_model or default_model == "deepseek-flash":
        env_model = (
            os.environ.get("AI_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if env_model:
            default_model = env_model

    # Determine provider name:
    # CLI / explicit override > Config (AI_PROVIDER: env > env-file > default)
    raw_name = (
        provider_name
        if provider_name is not None
        else (os.environ.get("AI_PROVIDER") or default_provider)
    )
    name = (raw_name or "").strip().lower()

    if name in ("mock", "offline", "test"):
        return MockAICompositionProvider()

    effective_key = api_key or default_key
    effective_url = base_url or default_url
    effective_model = model or default_model or "deepseek-flash"

    # If provider is explicitly 'openai', 'deepseek', or key is available and provider is not mock
    if name in ("openai", "deepseek", "live") or (effective_key and name != "mock"):
        return OpenAICompositionProvider(
            api_key=effective_key,
            model=effective_model,
            base_url=effective_url,
        )

    return MockAICompositionProvider()
