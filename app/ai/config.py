"""AI provider configuration and construction."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.ai.base import AIProviderError
from app.ai.budget import BudgetedProvider, create_request_budget


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_ai_provider():
    """Create the configured AI provider, or return None if disabled."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    provider_name = os.getenv("AI_PROVIDER", "gemini").strip().lower()

    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "replace_with_your_key":
            return None

        from app.ai.gemini_provider import GeminiProvider

        provider = GeminiProvider(
            api_key=api_key,
            model=os.getenv("GEMINI_MODEL") or None,
        )

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key or api_key == "replace_with_your_key":
            return None

        from app.ai.deepseek_provider import DeepSeekProvider

        provider = DeepSeekProvider(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            endpoint=os.getenv(
                "DEEPSEEK_API_ENDPOINT",
                "https://api.deepseek.com/chat/completions",
            ).strip(),
        )

    else:
        raise AIProviderError(
            f"Unsupported AI provider: {provider_name}",
            category="configuration_error",
        )

    return BudgetedProvider(
        provider,
        create_request_budget(),
        credits_per_call=3,
    )
