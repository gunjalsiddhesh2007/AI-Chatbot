"""Environment-backed application settings."""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _positive_int(name, default, maximum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    value = max(1, value)
    return min(value, maximum) if maximum else value


def flask_settings():
    secret = os.getenv("FLASK_SECRET_KEY", "").strip()
    if not secret or secret.startswith("replace_with_"):
        secret = secrets.token_hex(32)

    cookie_secure = os.getenv("COOKIE_SECURE")
    if cookie_secure is None:
        cookie_secure = os.getenv("RENDER", "").lower() == "true"
    else:
        cookie_secure = cookie_secure.lower() in {"1", "true", "yes", "on"}

    return {
        "SECRET_KEY": secret,
        "DATABASE_URL": os.getenv("DATABASE_URL", "").strip(),
        "DATABASE_PATH": os.getenv("DATABASE_PATH", "chatbot.db"),
        "MAX_CONTENT_LENGTH": 16 * 1024,
        "RATE_LIMIT": os.getenv("RATE_LIMIT", "10 per hour"),
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        "CONTEXT_WINDOW": _positive_int("CONTEXT_WINDOW", 20, maximum=100),
        "CONTEXT_MAX_CHARS": _positive_int("CONTEXT_MAX_CHARS", 24000, maximum=100000),
        "GEMINI_MODEL": os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": cookie_secure,
    }
