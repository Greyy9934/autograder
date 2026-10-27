"""AI provider configuration and construction."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.ai.base import AIProviderError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_ai_provider():
    """Create the configured AI provider, or return None if disabled."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "replace_with_your_key":
        return None

    provider_name = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider_name != "gemini":
        raise AIProviderError(
            f"Unsupported AI provider: {provider_name}",
            category="configuration_error",
        )

    from app.ai.gemini_provider import GeminiProvider

    return GeminiProvider(
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL") or None,
    )
