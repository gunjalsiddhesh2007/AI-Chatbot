import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import utils.database as database
from utils.database import (
    ConversationNotFound,
    create_conversation,
    create_conversation_with_first_message,
    delete_conversation,
    get_context_messages,
    get_conversation,
    initialize_database,
    list_conversations,
    save_message,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.path = str(Path(self.temp_dir.name) / "chat.db")
        initialize_database(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_save_messages_sets_title_and_updates_order(self):
        first, user_id = create_conversation_with_first_message("Explain Python programming", self.path)
        save_message(first["id"], "assistant", "Python is a programming language.", self.path)
        save_message(first["id"], "user", "Who created it?", self.path)
        save_message(first["id"], "assistant", "Guido van Rossum created Python.", self.path)

        conversation = get_conversation(first["id"], self.path)
        self.assertEqual(conversation["title"], "Explain Python programming")
        self.assertEqual([message["role"] for message in conversation["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual(conversation["messages"][0]["id"], user_id)
        self.assertGreater(conversation["updated_at"], first["created_at"])

    def test_context_is_ordered_limited_and_isolated_to_requested_conversation(self):
        first, first_message = create_conversation_with_first_message("What is Python?", self.path)
        save_message(first["id"], "assistant", "Python is a programming language.", self.path)
        second_message = save_message(first["id"], "user", "Who created it?", self.path)
        save_message(first["id"], "assistant", "Guido van Rossum.", self.path)
        other = create_conversation(self.path)
        save_message(other["id"], "user", "Unrelated private context", self.path)

        context = get_context_messages(first["id"], before_message_id=second_message["id"], window=10, max_chars=2000, path=self.path)
        self.assertEqual(context, [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ])
        self.assertNotIn("Unrelated", str(context))
        windowed = get_context_messages(first["id"], before_message_id=second_message["id"], window=1, max_chars=2000, path=self.path)
        self.assertEqual(len(windowed), 1)
        self.assertEqual(windowed[0]["role"], "assistant")
        self.assertLess(first_message, second_message["id"])

    def test_title_search_escapes_wildcards(self):
        matching, _ = create_conversation_with_first_message("100% complete", self.path)
        create_conversation_with_first_message("100 percent complete", self.path)
        self.assertEqual([item["id"] for item in list_conversations(self.path, "%")], [matching["id"]])

    def test_deleting_conversation_cascades_only_its_messages(self):
        deleted, _ = create_conversation_with_first_message("Delete me", self.path)
        kept, _ = create_conversation_with_first_message("Keep me", self.path)
        save_message(deleted["id"], "assistant", "This will be deleted.", self.path)
        self.assertTrue(delete_conversation(deleted["id"], self.path))
        self.assertIsNone(get_conversation(deleted["id"], self.path))
        remaining = get_conversation(kept["id"], self.path)
        self.assertEqual([message["content"] for message in remaining["messages"]], ["Keep me"])
        self.assertFalse(delete_conversation(deleted["id"], self.path))

        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (deleted["id"],)).fetchone()[0], 0)
        finally:
            connection.close()

    def test_missing_conversation_cannot_receive_messages_or_context(self):
        with self.assertRaises(ConversationNotFound):
            save_message(99999, "user", "No conversation", self.path)
        with self.assertRaises(ConversationNotFound):
            get_context_messages(99999, before_message_id=99999, path=self.path)

    def test_postgres_url_selects_psycopg_and_translates_parameters(self):
        fake_connection = Mock()
        fake_driver = types.ModuleType("psycopg")
        fake_driver.__path__ = []
        fake_driver.connect = Mock(return_value=fake_connection)

        class FakeDriverError(Exception):
            pass

        fake_driver.Error = FakeDriverError
        fake_rows = types.ModuleType("psycopg.rows")
        fake_rows.dict_row = object()
        url = "postgres://user:secret@db.example.test:5432/chat"

        with patch.dict(sys.modules, {"psycopg": fake_driver, "psycopg.rows": fake_rows}):
            connection = database._connect(url)
            connection.execute("SELECT id FROM conversations WHERE id = ?", (7,))

        self.assertTrue(connection.is_postgres)
        fake_driver.connect.assert_called_once_with(
            "postgresql://user:secret@db.example.test:5432/chat",
            row_factory=fake_rows.dict_row,
            connect_timeout=10,
        )
        fake_connection.execute.assert_called_once_with("SELECT id FROM conversations WHERE id = %s", (7,))

    def test_postgres_initialization_executes_schema_and_commits(self):
        fake_connection = Mock()
        fake_driver = types.ModuleType("psycopg")
        fake_driver.__path__ = []
        fake_driver.connect = Mock(return_value=fake_connection)

        class FakeDriverError(Exception):
            pass

        fake_driver.Error = FakeDriverError
        fake_rows = types.ModuleType("psycopg.rows")
        fake_rows.dict_row = object()

        with patch.dict(sys.modules, {"psycopg": fake_driver, "psycopg.rows": fake_rows}):
            initialize_database("postgresql://user:password@db.example.test/chat")

        self.assertEqual(fake_connection.execute.call_count, len(database.POSTGRES_SCHEMA))
        self.assertIn("ON DELETE CASCADE", " ".join(call.args[0] for call in fake_connection.execute.call_args_list))
        fake_connection.commit.assert_called_once_with()
        fake_connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
