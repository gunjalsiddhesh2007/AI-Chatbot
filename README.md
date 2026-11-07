# AI ChatBot

A small Flask chatbot with Gemini responses, server-side SQLite conversation history, and a responsive vanilla JavaScript interface. The Google Gen AI Python SDK sends recent messages from the selected conversation to Gemini. The browser never sends its own message history as model context.

## Run locally

1. Use Python 3.10 or newer.
2. Create and activate a virtual environment: `python -m venv .venv`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`, add `GEMINI_API_KEY`, and set a long random `FLASK_SECRET_KEY`.
5. Start the app with `python app.py`, then open `http://127.0.0.1:5000`.

`GEMINI_MODEL` defaults to `gemini-3.8-flash`; set a model available to your API key if needed. Gemini is the primary provider. To keep existing Phase 1 deployments working while they migrate, the app uses `GROQ_API_KEY` (then `GROQ_API_KEY_2`) only when `GEMINI_API_KEY` is absent. Provider keys are read only by the backend and are never stored in SQLite.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Gemini API key (recommended provider) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model name |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Maximum length of a Gemini response |
| `FLASK_SECRET_KEY` | Random per process | Signs Flask sessions; configure a stable random value in deployment |
| `DATABASE_PATH` | `chatbot.db` | SQLite database file |
| `RATE_LIMIT` | `10 per hour` | Per-IP limit for chat and conversation writes |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter storage; use shared Redis for multiple instances |
| `CONTEXT_WINDOW` | `20` | Maximum previous messages included in model context |
| `CONTEXT_MAX_CHARS` | `24000` | Approximate input-size guard for previous messages |
| `GROQ_API_KEY` | — | Optional legacy fallback keys |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Legacy fallback model |

Copy `.env.example` for local development. `.env` and SQLite database files are ignored by Git. Do not commit credentials.

## Conversation storage and privacy

SQLite records conversations and messages in order, enables foreign keys, cascades deletes, and uses parameterized SQL. A conversation title is taken from its first user message. Search, loading, and deletion operate on stored conversation records.

This is a single-user prototype: conversation history is shared by every visitor to the service. Numeric conversation IDs are checked against SQLite but are not authentication or user isolation. Do not expose the service to multiple users with private-history expectations until authentication and per-user ownership checks are implemented.

The web UI uses a session CSRF token for write requests, secure cookie settings on Render, and sanitizes AI Markdown with DOMPurify before inserting rendered HTML. Marked.js, DOMPurify, and Highlight.js are loaded from pinned jsDelivr versions.

## Render deployment

1. Create a Render Web Service connected to the project.
2. Build command: `pip install -r requirements.txt`.
3. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT` (also in `Procfile`).
4. Add `GEMINI_API_KEY` and a strong stable `FLASK_SECRET_KEY` in the service environment. Set `GEMINI_MODEL`, `RATE_LIMIT`, `CONTEXT_WINDOW`, or `RATELIMIT_STORAGE_URI` as required.
5. For durable SQLite storage, attach a Render Persistent Disk and set `DATABASE_PATH` to a file under its mount path, for example `/var/data/chatbot.db` when the disk is mounted at `/var/data`.

SQLite files on Render's ordinary ephemeral filesystem can be lost during redeploys, restarts, or instance replacement. The app initializes the database automatically, but it does not make ephemeral storage durable. A single SQLite file also suits one service instance; use a shared database and shared rate-limit store before scaling to multiple instances.

`GET /health` checks that the configured database can be opened. Gunicorn starts the WSGI object exported as `app` by `app.py`.

## API

All JSON responses use `success`, `data`, and `error` fields. Browser write requests require the CSRF token returned in the page's `csrf-token` meta tag as the `X-CSRF-Token` header.

- `GET /` — chatbot page and session CSRF token.
- `POST /api/chat` — `{ "conversation_id": 12, "message": "Who created it?" }`. Omit or set `conversation_id` to `null` to create a conversation when the first message is sent. Previous context is loaded from SQLite.
- `GET /api/conversations` — recent conversations; optional `?q=python` title search.
- `POST /api/conversations` — create an empty conversation.
- `GET /api/conversations/<id>` — conversation and messages.
- `DELETE /api/conversations/<id>` — delete a conversation and its messages.
- `GET /health` — application and database status.

The chat request body is limited to 16 KB, message text to 4,000 characters, and chat/write routes use the configured per-IP rate limit. Database errors return safe messages; internal traces and credentials are kept out of API responses.

## Tests

Run the test suite with `python -m unittest discover -s tests -v`. The tests use temporary SQLite files and mocked Gemini responses, so they do not need an API key.
