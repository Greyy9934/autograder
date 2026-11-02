import pytest
import os
import unittest
from unittest.mock import patch

from app.ai.config import create_ai_provider
from app.ai.budget import BudgetedProvider


class AIConfigTests(unittest.TestCase):
    def test_missing_key_disables_ai(self):
        with (
            patch("app.ai.config.load_dotenv"),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertIsNone(create_ai_provider())

    def test_placeholder_key_disables_ai(self):
        with (
            patch("app.ai.config.load_dotenv"),
            patch.dict(
                os.environ,
                {"GEMINI_API_KEY": "replace_with_your_key"},
                clear=True,
            ),
        ):
            self.assertIsNone(create_ai_provider())

    def test_configured_gemini_provider_is_created(self):
        with (
            patch("app.ai.config.load_dotenv"),
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODEL": "test-model",
                    "AI_PROVIDER": "gemini",
                },
                clear=True,
            ),
        ):
            provider = create_ai_provider()
            self.assertIsInstance(provider, BudgetedProvider)
            self.assertEqual(type(provider.provider).__name__, "GeminiProvider")
            self.assertEqual(provider.provider.model, "test-model")
            self.assertEqual(provider.provider.api_key, "test-key")
            self.assertEqual(provider.provider.max_retries, 0)
            self.assertEqual(provider.credits_per_call, 1)


if __name__ == "__main__":
    unittest.main()


def test_configured_deepseek_provider_is_created():
    from unittest.mock import Mock

    with (
        patch("app.ai.config.load_dotenv"),
        patch(
            "app.ai.config.create_request_budget",
            return_value=Mock(),
        ),
        patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "deepseek-test-key",
            },
            clear=True,
        ),
    ):
        provider = create_ai_provider()

    from app.ai.budget import BudgetedProvider
    from app.ai.deepseek_provider import DeepSeekProvider

    assert isinstance(provider, BudgetedProvider)
    assert isinstance(provider.provider, DeepSeekProvider)
    assert provider.provider.api_key == "deepseek-test-key"
    assert provider.provider.model == "deepseek-flash"
    assert provider.provider.max_tokens == 8192
    assert provider.provider.max_retries == 0
    assert provider.credits_per_call == 1


def test_missing_deepseek_key_disables_ai():
    with (
        patch("app.ai.config.load_dotenv"),
        patch.dict(
            os.environ,
            {"AI_PROVIDER": "deepseek"},
            clear=True,
        ),
    ):
        assert create_ai_provider() is None


def test_unknown_provider_is_rejected_even_without_key():
    with (
        patch("app.ai.config.load_dotenv"),
        patch.dict(
            os.environ,
            {"AI_PROVIDER": "unknown"},
            clear=True,
        ),
    ):
        from app.ai.base import AIProviderError

        with pytest.raises(AIProviderError) as caught:
            create_ai_provider()

    assert caught.value.category == "configuration_error"


def test_explicit_mock_mode_returns_offline_provider_without_api_key():
    with (
        patch("app.ai.config.load_dotenv"),
        patch.dict(os.environ, {"AUTOGRADER_MOCK_MODE": "1"}, clear=True),
    ):
        provider = create_ai_provider()

    from app.ai.mock_workflow_provider import MockWorkflowProvider
    assert isinstance(provider, MockWorkflowProvider)
    assert provider.mock_mode is True


def test_mock_mode_is_rejected_in_production():
    from app.ai.base import AIProviderError

    with (
        patch("app.ai.config.load_dotenv"),
        patch.dict(
            os.environ,
            {"AUTOGRADER_MOCK_MODE": "true", "APP_ENV": "production"},
            clear=True,
        ),
    ):
        with pytest.raises(AIProviderError, match="disabled in production"):
            create_ai_provider()
