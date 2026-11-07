import os
import unittest
from unittest.mock import Mock, patch

from utils.ai_service import AIServiceError, generate_response


class AIServiceTests(unittest.TestCase):
    @patch("utils.ai_service._gemini_response", return_value="**Hello**")
    def test_gemini_is_primary_and_markdown_is_preserved(self, generate):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key", "GROQ_API_KEY": "legacy-key"}):
            response = generate_response("new question", [{"role": "user", "content": "prior"}])
        self.assertEqual(response, "**Hello**")
        generate.assert_called_once_with("test-gemini-key", "new question", [{"role": "user", "content": "prior"}])

    def test_official_gemini_sdk_receives_ordered_history_and_latest_message(self):
        client = Mock()
        client.models.generate_content.return_value.text = "## Markdown answer"
        with patch("google.genai.Client", return_value=client) as make_client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key", "GROQ_API_KEY": ""}):
                response = generate_response("Who created it?", [
                    {"role": "user", "content": "What is Python?"},
                    {"role": "assistant", "content": "A programming language."},
                ])
        self.assertEqual(response, "## Markdown answer")
        make_client.assert_called_once_with(api_key="test-gemini-key")
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual([item.role for item in call["contents"]], ["user", "model", "user"])
        self.assertEqual([item.parts[0].text for item in call["contents"]], [
            "What is Python?", "A programming language.", "Who created it?"
        ])
        self.assertIn("Markdown", call["config"].system_instruction)
        client.close.assert_called_once_with()

    @patch("utils.ai_service._groq_response", return_value="Legacy reply")
    def test_existing_groq_configuration_remains_a_fallback(self, generate):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "legacy-key"}):
            response = generate_response("hello", [])
        self.assertEqual(response, "Legacy reply")
        generate.assert_called_once_with("legacy-key", "hello", [])

    def test_missing_keys_return_safe_configuration_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "", "GROQ_API_KEY_2": ""}):
            with self.assertRaises(AIServiceError) as error:
                generate_response("hello", [])
        self.assertIn("GEMINI_API_KEY", str(error.exception))
        self.assertNotIn("test", str(error.exception))


if __name__ == "__main__":
    unittest.main()
