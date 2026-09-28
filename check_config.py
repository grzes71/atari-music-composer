"""Script to verify and inspect active configuration and priority resolution.

Usage examples:
    python check_config.py
    python check_config.py --provider deepseek --model deepseek-v4-pro
    python check_config.py --env-file custom.env
    python check_config.py --model deepseek-chat --log-level DEBUG --api-key sk-1234567890abcdef1234
"""

from __future__ import annotations

import sys
from config import Config, ConfigValidationError

# Configure standard streams for UTF-8 compatibility on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    """Inspect and display resolved configuration settings and their winning source."""
    print("=" * 68)
    print("  Atari Music / AI Configuration Inspector")
    print("=" * 68)

    # 1. Resolve configuration with priority chain (CLI -> Env -> .env -> Default)
    # validate=False so we can inspect settings even when using placeholders
    config = Config.from_args(validate=False)

    print("\n[Rozpoznane parametry konfiguracji]")
    print(f"  * AI_PROVIDER : {config.ai_provider}")
    print(f"    |-- Zrodlo  : {config.sources.get('AI_PROVIDER', 'unknown')}")

    print(f"  * AI_API_KEY  : {config.masked_api_key()}")
    print(f"    |-- Zrodlo  : {config.sources.get('AI_API_KEY', 'unknown')}")

    print(f"  * AI_BASE_URL : {config.ai_base_url}")
    print(f"    |-- Zrodlo  : {config.sources.get('AI_BASE_URL', 'unknown')}")

    print(f"  * AI_MODEL    : {config.ai_model}")
    print(f"    |-- Zrodlo  : {config.sources.get('AI_MODEL', 'unknown')}")

    print(f"  * LOG_LEVEL   : {config.log_level}")
    print(f"    |-- Zrodlo  : {config.sources.get('LOG_LEVEL', 'unknown')}")

    if config.env_file:
        print(f"  * ENV_FILE    : {config.env_file}")

    print("\n[Status walidacji klucza API]")
    try:
        config.validate()
        print("  [OK] Konfiguracja gotowa do uzycia (AI_API_KEY jest poprawny).")
    except ConfigValidationError as err:
        print("  [UWAGA] Wykryto brak produkcyjnego klucza API:")
        for line in str(err).splitlines():
            print(f"    {line}")

    print("\n" + "=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
