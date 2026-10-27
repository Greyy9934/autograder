import unittest

from app.ai.base import AIProviderError
from app.ai.mock_provider import MockAIProvider


class AIProviderTests(unittest.TestCase):
    def test_returns_configured_response(self):
        expected = {"candidates": [{"id": "A"}, {"id": "B"}]}
        provider = MockAIProvider(expected)
        result = provider.generate_json("reconstruct", {"source": "int main(){}"}, {})
        self.assertEqual(result, expected)

    def test_records_call_contract(self):
        provider = MockAIProvider({"status": "ok"})
        provider.generate_json("task", {"source": "code"}, {"type": "object"})
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["task"], "task")
        self.assertEqual(provider.calls[0]["payload"], {"source": "code"})
        self.assertEqual(provider.calls[0]["schema"], {"type": "object"})

    def test_result_is_defensively_copied(self):
        provider = MockAIProvider({"items": [1]})
        result = provider.generate_json("task", {}, {})
        result["items"].append(2)
        self.assertEqual(provider.generate_json("task", {}, {}), {"items": [1]})

    def test_input_changes_do_not_rewrite_recorded_call(self):
        payload = {"source": "original"}
        provider = MockAIProvider({"ok": True})
        provider.generate_json("task", payload, {})
        payload["source"] = "changed"
        self.assertEqual(provider.calls[0]["payload"], {"source": "original"})

    def test_non_object_response_is_rejected(self):
        provider = MockAIProvider({"valid": True})
        provider.response = ["not", "an", "object"]
        with self.assertRaises(AIProviderError):
            provider.generate_json("task", {}, {})


if __name__ == "__main__":
    unittest.main()
