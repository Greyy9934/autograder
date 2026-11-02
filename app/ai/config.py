"""AI provider configuration and construction."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.ai.base import AIProviderError
from app.ai.budget import BudgetedProvider, create_request_budget
from app.ai.guardrails import GuardedProvider


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def mock_mode_enabled() -> bool:
    """Return whether explicit offline mock mode is enabled."""
    return os.getenv("AUTOGRADER_MOCK_MODE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def create_ai_provider():
    """Create the explicitly selected offline mock or configured AI provider."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    mock_enabled = mock_mode_enabled()
    if mock_enabled:
        if os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}:
            raise AIProviderError(
                "Offline mock mode is disabled in production.",
                category="configuration_error",
            )
        from app.ai.mock_workflow_provider import MockWorkflowProvider
        return MockWorkflowProvider()

    provider_name = os.getenv("AI_PROVIDER", "gemini").strip().lower()

    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "replace_with_your_key":
            return None

        from app.ai.gemini_provider import GeminiProvider

        provider = GeminiProvider(
            api_key=api_key,
            model=os.getenv("GEMINI_MODEL") or None,
            # One budget credit must correspond to at most one HTTP request.
            max_retries=0,
        )

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key or api_key == "replace_with_your_key":
            return None

        from app.ai.deepseek_provider import DeepSeekProvider

        provider = DeepSeekProvider(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            max_retries=0,
        )

    else:
        raise AIProviderError(
            f"Unsupported AI provider: {provider_name}",
            category="configuration_error",
        )

    return BudgetedProvider(
        provider,
        create_request_budget(),
        credits_per_call=1,
    )
