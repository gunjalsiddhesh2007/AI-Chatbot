"""Small, transaction-safe SQLite persistence layer for chat history."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class DatabaseError(Exception):
    """Safe database error without SQLite internals."""


class ConversationNotFound(DatabaseError):
    """Raised when an operation references a conversation that does not exist."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations(updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id
    ON messages(conversation_id, id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _database_path(path=None):
    return str(path or "chatbot.db")


def _ensure_parent(path):
    if path != ":memory:" and not path.startswith("file:"):
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _connect(path=None):
    db_path = _database_path(path)
    _ensure_parent(db_path)
    connection = sqlite3.connect(db_path, timeout=10, uri=db_path.startswith("file:"))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def _connection(path=None, transaction=False):
    connection = None
    try:
        connection = _connect(path)
        if transaction:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if transaction:
            connection.commit()
    except (sqlite3.Error, OSError):
        if connection is not None and transaction:
            connection.rollback()
        raise DatabaseError("The chat database is temporarily unavailable.") from None
    finally:
        if connection is not None:
            connection.close()


def initialize_database(path=None):
    """Create the schema and indexes if they do not already exist."""
    try:
        with _connection(path) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
    except (sqlite3.Error, OSError):
        raise DatabaseError("The chat database could not be initialized.") from None


def _display_conversation(row):
    return {
        "id": row["id"],
        "title": row["title"] or "New chat",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_from_row(row):
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def _make_title(content):
    title = " ".join(content.split())
    if len(title) > 64:
        title = title[:63].rstrip() + "…"
    return title


def create_conversation(path=None):
    now = _now()
    with _connection(path, transaction=True) as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            ("", now, now),
        )
        row = connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _display_conversation(row)


def create_conversation_with_first_message(content, path=None):
    """Atomically create a chat and store its first user message."""
    now = _now()
    title = _make_title(content)
    with _connection(path, transaction=True) as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        conversation_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, "user", content, now),
        )
        row = connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return _display_conversation(row), conversation_id


def save_message(conversation_id, role, content, path=None):
    if role not in ("user", "assistant"):
        raise ValueError("Unsupported message role.")
    now = _now()
    with _connection(path, transaction=True) as connection:
        exists = connection.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if exists is None:
            raise ConversationNotFound("Conversation not found.")
        cursor = connection.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        if role == "user" and not exists["title"]:
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND title = ''",
                (_make_title(content), now, conversation_id),
            )
        else:
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        row = connection.execute(
            "SELECT id, role, content, created_at FROM messages WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _message_from_row(row)


def list_conversations(path=None, search=""):
    with _connection(path) as connection:
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = connection.execute(
                """SELECT id, COALESCE(NULLIF(title, ''), 'New chat') AS title,
                          created_at, updated_at
                   FROM conversations WHERE COALESCE(NULLIF(title, ''), 'New chat') LIKE ? ESCAPE '\\'
                   ORDER BY updated_at DESC, id DESC""",
                (f"%{escaped}%",),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT id, COALESCE(NULLIF(title, ''), 'New chat') AS title,
                          created_at, updated_at
                   FROM conversations ORDER BY updated_at DESC, id DESC"""
            ).fetchall()
        return [_display_conversation(row) for row in rows]


def check_database(path=None):
    """Check schema availability without loading stored conversation data."""
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("conversations",),
        ).fetchone()
        if row is None:
            raise DatabaseError("The chat database is temporarily unavailable.")
        return True


def get_conversation(conversation_id, path=None):
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        messages = connection.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = ? ORDER BY id ASC""",
            (conversation_id,),
        ).fetchall()
        result = _display_conversation(row)
        result["messages"] = [_message_from_row(item) for item in messages]
        return result


def get_context_messages(conversation_id, before_message_id, window=20, max_chars=24000, path=None):
    """Return recent messages from one conversation, in chronological order."""
    with _connection(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if exists is None:
            raise ConversationNotFound("Conversation not found.")
        rows = connection.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = ? AND id < ?
               ORDER BY id DESC LIMIT ?""",
            (conversation_id, before_message_id, max(1, int(window))),
        ).fetchall()

    remaining = max(1, int(max_chars))
    selected = []
    for row in rows:
        if remaining <= 0:
            break
        content = row["content"]
        if len(content) > remaining:
            content = content[-remaining:]
        selected.append({"role": row["role"], "content": content})
        remaining -= len(content)
    selected.reverse()
    return selected


def delete_conversation(conversation_id, path=None):
    with _connection(path, transaction=True) as connection:
        cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount == 1
