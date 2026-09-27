"""AI Composition Providers package."""

from __future__ import annotations

import os
from typing import Optional

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
) -> AICompositionProvider:
    """Factory returning the appropriate AICompositionProvider instance.
    
    Seamlessly integrates with the project's Config (.env and CLI priority chain)
    to auto-configure DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, and DEEPSEEK_MODEL.
    """
    name = (provider_name or "").strip().lower()

    if name in ("mock", "offline", "test"):
        return MockAICompositionProvider()

    # Load configuration from project Config (which reads .env and respects CLI/env vars)
    default_key = None
    default_url = None
    default_model = None

    try:
        from config import Config
        cfg = Config.from_args(args=[], validate=False)
        default_key = cfg.deepseek_api_key
        default_url = cfg.deepseek_base_url
        default_model = cfg.deepseek_model
    except Exception:
        pass

    if not default_key:
        from pathlib import Path
        from dotenv import dotenv_values
        root_dir = Path(__file__).resolve().parent.parent.parent.parent
        env_candidates = [Path(".env"), root_dir / ".env"]
        for cand in env_candidates:
            if cand.exists() and cand.is_file():
                env_vals = dotenv_values(dotenv_path=cand)
                default_key = env_vals.get("DEEPSEEK_API_KEY") or env_vals.get("OPENAI_API_KEY")
                default_url = env_vals.get("DEEPSEEK_BASE_URL") or env_vals.get("OPENAI_BASE_URL")
                default_model = env_vals.get("DEEPSEEK_MODEL") or env_vals.get("OPENAI_MODEL")
                break

    default_key = default_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    default_url = default_url or os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    default_model = default_model or os.environ.get("DEEPSEEK_MODEL") or os.environ.get("OPENAI_MODEL")

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

