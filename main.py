"""Application entry point demonstrating configuration loading and AI client initialization.

Hierarchy of configuration sources:
  1) CLI argument (e.g. --provider, --model, --api-key, --base-url, --log-level, --env-file)
  2) System environment variable (AI_PROVIDER, AI_API_KEY, AI_BASE_URL, AI_MODEL, LOG_LEVEL)
  3) .env file (or custom --env-file)
  4) In-code defaults
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from config import Config, ConfigValidationError

# Configure standard streams for UTF-8 compatibility on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("atari_music.main")


class DeepSeekClientDemo:
    """Client demonstrating usage of AI API with dynamically configured credentials."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def print_client_summary(self) -> None:
        masked = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) > 8 else "******"
        logger.info("AI Client zainicjalizowany:")
        logger.info("  * Base URL : %s", self.base_url)
        logger.info("  * Model    : %s", self.model)
        logger.info("  * API Key  : %s", masked)


def run_app(config: Config) -> int:
    """Core application logic receiving the resolved configuration object."""
    logger.info("Uruchamianie aplikacji z konfiguracja:")
    logger.info("  * AI Provider : %s (zrodlo: %s)", config.ai_provider, config.sources.get("AI_PROVIDER"))
    logger.info("  * AI Base URL : %s (zrodlo: %s)", config.ai_base_url, config.sources.get("AI_BASE_URL"))
    logger.info("  * AI Model    : %s (zrodlo: %s)", config.ai_model, config.sources.get("AI_MODEL"))
    logger.info("  * Log Level   : %s (zrodlo: %s)", config.log_level, config.sources.get("LOG_LEVEL"))
    logger.info("  * AI API Key  : %s (zrodlo: %s)", config.masked_api_key(), config.sources.get("AI_API_KEY"))

    # c) Utworzenie i uzycie klienta AI z parametrami z obiektu Config
    client = DeepSeekClientDemo(
        api_key=config.ai_api_key,
        base_url=config.ai_base_url,
        model=config.ai_model,
    )
    client.print_client_summary()

    # Jezeli zainstalowana jest biblioteka openai, pokazujemy kompatybilnosc z oficjalnym SDK:
    try:
        import openai  # type: ignore

        sdk_client = openai.OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
        )
        logger.info("Oficjalne SDK openai zainicjalizowane z base_url=%s", sdk_client.base_url)
    except ImportError:
        logger.debug("Opcjonalna biblioteka 'openai' nie jest zainstalowana (mozna uzyc DeepSeekClientDemo lub HTTP).")

    # Sprawdzenie gotowosci do wywolan produkcyjnych
    try:
        config.validate()
        logger.info("Konfiguracja jest kompletna. Klient jest gotowy do wysylania zapytan do DeepSeek.")
    except ConfigValidationError as err:
        logger.warning("Tryb demo / offline: klucz API nie jest skonfigurowany do zapytan na zywo:")
        for line in str(err).splitlines():
            logger.warning("  %s", line)

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    # a) Stworzenie obiektu Config z obsluga priorytetow (CLI -> Env -> .env -> Domyslne)
    config = Config.from_args(args=argv, validate=False)

    # Konfiguracja systemu logowania zgodnie z wybranym poziomem
    from atari_music.logging_config import setup_logging
    setup_logging(config.log_level)

    # b) Przekazanie obiektu konfiguracji do logiki aplikacji
    return run_app(config)


if __name__ == "__main__":
    sys.exit(main())
