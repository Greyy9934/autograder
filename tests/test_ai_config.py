import os
import unittest
from unittest.mock import patch

from app.ai.config import create_ai_provider


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
            self.assertEqual(type(provider).__name__, "GeminiProvider")
            self.assertEqual(provider.model, "test-model")
            self.assertEqual(provider.api_key, "test-key")


if __name__ == "__main__":
    unittest.main()
