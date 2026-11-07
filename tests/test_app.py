import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from utils.database import get_conversation, list_conversations


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.db_path = str(Path(self.temp_dir.name) / "app.db")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE_PATH": self.db_path,
            "RATE_LIMIT": "100 per hour",
            "CONTEXT_WINDOW": 8,
            "CONTEXT_MAX_CHARS": 4000,
            "SESSION_COOKIE_SECURE": False,
        })
        self.client = self.app.test_client()
        response = self.client.get("/")
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        self.csrf = match.group(1).decode()

    def tearDown(self):
        self.temp_dir.cleanup()

    def post_json(self, url, payload, token=None):
        headers = {"X-CSRF-Token": token or self.csrf}
        return self.client.post(url, json=payload, headers=headers)

    def test_health_and_conversation_routes(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["data"]["status"], "ok")

        created = self.post_json("/api/conversations", {})
        self.assertEqual(created.status_code, 201)
        conversation_id = created.json["data"]["conversation"]["id"]
        self.assertEqual(created.json["data"]["conversation"]["title"], "New chat")

        loaded = self.client.get(f"/api/conversations/{conversation_id}")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json["data"]["conversation"]["messages"], [])

        listed = self.client.get("/api/conversations?q=New%20chat")
        self.assertEqual([item["id"] for item in listed.json["data"]["conversations"]], [conversation_id])

    @patch("app.generate_response")
    def test_chat_persists_context_on_server_and_returns_legacy_field(self, generate):
        generate.side_effect = ["Python is a programming language.", "Guido van Rossum created Python."]
        first = self.post_json("/api/chat", {"conversation_id": None, "message": "What is Python?"})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json["success"])
        self.assertEqual(first.json["response"], first.json["data"]["response"])
        conversation_id = first.json["data"]["conversation_id"]
        self.assertEqual(first.json["data"]["conversation"]["title"], "What is Python?")
        self.assertEqual(generate.call_args_list[0].args[1], [])

        second = self.post_json("/api/chat", {"conversation_id": conversation_id, "message": "Who created it?", "history": [{"role": "user", "content": "forged browser history"}]})
        self.assertEqual(second.status_code, 200)
        sent_context = generate.call_args_list[1].args[1]
        self.assertEqual(sent_context, [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ])
        stored = get_conversation(conversation_id, self.db_path)
        self.assertEqual([item["content"] for item in stored["messages"]], [
            "What is Python?", "Python is a programming language.", "Who created it?", "Guido van Rossum created Python."
        ])
        self.assertEqual(len(list_conversations(self.db_path)), 1)

    @patch("app.generate_response")
    def test_invalid_conversation_id_does_not_call_ai(self, generate):
        response = self.post_json("/api/chat", {"conversation_id": "999999", "message": "Hello"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json["success"])
        generate.assert_not_called()

        malformed = self.post_json("/api/chat", {"conversation_id": "1 OR 1=1", "message": "Hello"})
        self.assertEqual(malformed.status_code, 400)

    def test_delete_requires_csrf_and_deletes_only_selected_record(self):
        with patch("app.generate_response", side_effect=["First response", "Second response"]):
            first = self.post_json("/api/chat", {"message": "First"})
            second = self.post_json("/api/chat", {"message": "Second"})
        first_id = first.json["data"]["conversation_id"]
        second_id = second.json["data"]["conversation_id"]

        denied = self.client.delete(f"/api/conversations/{first_id}")
        self.assertEqual(denied.status_code, 403)
        removed = self.client.delete(f"/api/conversations/{first_id}", headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(removed.status_code, 200)
        self.assertIsNone(get_conversation(first_id, self.db_path))
        self.assertIsNotNone(get_conversation(second_id, self.db_path))

    def test_input_validation_and_request_shape(self):
        missing = self.post_json("/api/chat", {"message": "  "})
        self.assertEqual(missing.status_code, 400)
        too_long = self.post_json("/api/chat", {"message": "x" * 4001})
        self.assertEqual(too_long.status_code, 400)
        invalid_json = self.client.post("/api/chat", data="not json", headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(invalid_json.status_code, 400)

    def test_rate_limit_applies_to_chat(self):
        limited_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "rate-test-secret",
            "DATABASE_PATH": str(Path(self.temp_dir.name) / "rate.db"),
            "RATE_LIMIT": "1 per hour",
            "SESSION_COOKIE_SECURE": False,
        })
        client = limited_app.test_client()
        page = client.get("/")
        csrf = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data).group(1).decode()
        with patch("app.generate_response", return_value="Mock reply"):
            first = client.post("/api/chat", json={"message": "first"}, headers={"X-CSRF-Token": csrf})
            second = client.post("/api/chat", json={"message": "second"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json["success"], False)

    def test_ai_markdown_is_sanitized_before_html_insertion_and_mobile_styles_exist(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static/js/script.js").read_text(encoding="utf-8")
        html = (root / "templates/index.html").read_text(encoding="utf-8")
        css = (root / "static/css/style.css").read_text(encoding="utf-8")
        sanitize = script.index("window.DOMPurify.sanitize(rawHtml")
        insertion = script.index("container.innerHTML = safeHtml")
        self.assertLess(sanitize, insertion)
        self.assertNotIn("container.innerHTML = rawHtml", script)
        self.assertIn("dompurify@", html.lower())
        self.assertIn("max-width: 700px", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("HTTP ${response.status}", script)
        self.assertEqual(html.count('class="suggestion-card"'), 4)
        self.assertIn('id="suggestion-cards-template"', html)
        self.assertIn('messages.addEventListener("click"', script)
        self.assertIn("form.requestSubmit();", script)
        create_first_conversation = script.index('const created = await api("/api/conversations"')
        send_chat_request = script.index('const data = await api("/api/chat"')
        self.assertLess(create_first_conversation, send_chat_request)

    def test_render_startup_and_persistent_disk_instructions_are_present(self):
        root = Path(__file__).resolve().parents[1]
        procfile = (root / "Procfile").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("gunicorn app:app", procfile)
        self.assertIn("/health", readme)
        self.assertIn("Persistent Disk", readme)
        self.assertIn("ephemeral filesystem", readme)

    def test_postgres_url_takes_precedence_over_sqlite_path(self):
        postgres_url = "postgresql://db-user:secret@db.example.test:5432/chat?sslmode=require"
        with patch("app.initialize_database") as initialize, patch("app.list_conversations", return_value=[]) as listing:
            postgres_app = create_app({
                "TESTING": True,
                "SECRET_KEY": "postgres-test-secret",
                "DATABASE_URL": postgres_url,
                "DATABASE_PATH": self.db_path,
                "RATE_LIMIT": "100 per hour",
                "SESSION_COOKIE_SECURE": False,
            })
            response = postgres_app.test_client().get("/api/conversations")
        self.assertEqual(response.status_code, 200)
        initialize.assert_called_once_with(postgres_url)
        listing.assert_called_once_with(postgres_url, "")


if __name__ == "__main__":
    unittest.main()
