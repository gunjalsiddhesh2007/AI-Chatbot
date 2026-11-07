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

    @patch("utils.ai_service._groq_response", return_value="Groq backup reply")
    @patch("utils.ai_service._gemini_response", side_effect=AIServiceError("Gemini is unavailable."))
    def test_groq_is_tried_when_configured_gemini_fails(self, gemini, groq):
        context = [{"role": "user", "content": "earlier question"}]
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gemini-key",
            "GROQ_API_KEY": "groq-key",
            "GROQ_API_KEY_2": "groq-backup-key",
        }):
            response = generate_response("latest question", context)
        self.assertEqual(response, "Groq backup reply")
        gemini.assert_called_once_with("gemini-key", "latest question", context)
        groq.assert_called_once_with("groq-key", "latest question", context)

    @patch("utils.ai_service._groq_response", side_effect=[RuntimeError("primary unavailable"), "backup reply"])
    @patch("utils.ai_service._gemini_response", side_effect=RuntimeError("Gemini unavailable"))
    def test_groq_backup_key_is_tried_if_primary_groq_key_fails(self, gemini, groq):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gemini-key",
            "GROQ_API_KEY": "groq-key",
            "GROQ_API_KEY_2": "groq-backup-key",
        }):
            response = generate_response("hello", [])
        self.assertEqual(response, "backup reply")
        self.assertEqual([call.args[0] for call in groq.call_args_list], ["groq-key", "groq-backup-key"])

    @patch("utils.ai_service._groq_response", side_effect=RuntimeError("private provider details"))
    @patch("utils.ai_service._gemini_response", side_effect=RuntimeError("private Gemini details"))
    def test_double_provider_failure_is_safe(self, gemini, groq):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "gemini-key",
            "GROQ_API_KEY": "groq-key",
        }):
            with self.assertRaises(AIServiceError) as error:
                generate_response("hello", [])
        self.assertIn("Groq fallback also failed", str(error.exception))
        self.assertNotIn("private", str(error.exception))

    def test_missing_keys_return_safe_configuration_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "", "GROQ_API_KEY_2": ""}):
            with self.assertRaises(AIServiceError) as error:
                generate_response("hello", [])
        self.assertIn("GEMINI_API_KEY", str(error.exception))
        self.assertNotIn("test", str(error.exception))


if __name__ == "__main__":
    unittest.main()
