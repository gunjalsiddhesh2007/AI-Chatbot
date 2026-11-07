# AI ChatBot

A small Flask chatbot with Gemini responses, persistent conversation history, and a responsive vanilla JavaScript interface. It uses SQLite automatically for local development. When `DATABASE_URL` is set, it uses PostgreSQL instead, including Supabase Postgres. The Google Gen AI Python SDK sends recent messages from the selected conversation to Gemini; the browser never supplies its own model context.

## Run locally

1. Use Python 3.10 or newer.
2. Create and activate a virtual environment: `python -m venv .venv`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env` if you do not already have a `.env`; add `GEMINI_API_KEY` and a long random `FLASK_SECRET_KEY`.
5. Leave `DATABASE_URL` blank to use the local SQLite file, or set it to a PostgreSQL connection URL.
6. Start the app with `python app.py`, then open `http://127.0.0.1:5000`.

`GEMINI_MODEL` defaults to `gemini-3.8-flash`; set a model available to your API key if needed. Gemini is tried first. If its key is missing or a Gemini request fails, the app tries `GROQ_API_KEY`, followed by `GROQ_API_KEY_2`. Provider API keys and database connection URLs are read only by the backend.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Gemini API key (recommended provider) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model name |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Maximum length of a Gemini response |
| `FLASK_SECRET_KEY` | Random per process | Signs Flask sessions; configure a stable random value in deployment |
| `DATABASE_URL` | Blank | Optional PostgreSQL URL; takes precedence over `DATABASE_PATH` |
| `DATABASE_PATH` | `chatbot.db` | SQLite file used when `DATABASE_URL` is blank |
| `RATE_LIMIT` | `10 per hour` | Per-IP limit for chat and conversation writes |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter storage; use shared Redis for multiple instances |
| `CONTEXT_WINDOW` | `20` | Maximum previous messages included in model context |
| `CONTEXT_MAX_CHARS` | `24000` | Approximate input-size guard for previous messages |
| `GROQ_API_KEY`, `GROQ_API_KEY_2` | — | Fallback keys tried in order if Gemini is unavailable |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq fallback model |

Copy `.env.example` for local development. `.env`, SQLite files, and PostgreSQL credentials are not committed. Do not put secrets in source files or commit a filled `.env`.

## Database setup and privacy

The app creates the selected database schema and indexes automatically on startup; no manual SQL setup is required. Both SQLite and PostgreSQL use parameterized queries, transactions, foreign keys, and cascading conversation deletion. When switching from SQLite to PostgreSQL, the app creates an empty PostgreSQL schema; it does not automatically migrate old SQLite conversations.

This is a single-user prototype: conversation history is shared by every visitor to the service. Numeric conversation IDs are checked against the database but are not authentication or user isolation. Add authentication and per-user ownership checks before exposing private conversations to multiple users.

## Render deployment

### Free Render service with Supabase Postgres

1. Create a Supabase project and open its **Connect** dialog. Copy a PostgreSQL connection string for a long-running backend (the session pooler URL is a practical option when a direct connection is not reachable from the service).
2. In Render, open the web service's **Environment** page and add `DATABASE_URL` with that full connection string. Treat it as a secret; it contains the database password. The app initializes its tables automatically at startup.
3. Add `GEMINI_API_KEY` and a strong, stable `FLASK_SECRET_KEY`. Optionally set `GEMINI_MODEL`, `RATE_LIMIT`, `CONTEXT_WINDOW`, and `CONTEXT_MAX_CHARS`.
4. Keep `DATABASE_PATH` unset on Render when using PostgreSQL; `DATABASE_URL` takes precedence if both are present.

Supabase's Free plan currently includes 500 MB of database storage. A free project can pause after a week of low activity; its data is retained while paused, but the database needs to be resumed. The free plan does not include automatic backups, so it is suitable for prototypes rather than data that must be guaranteed. Render's own Free Postgres expires after 30 days.

### Render with SQLite

To keep SQLite, attach a Render Persistent Disk to a paid web service, mount it at `/var/data`, and set `DATABASE_PATH=/var/data/chatbot.db`. Only files under the disk's mount path persist. SQLite on Render's ordinary ephemeral filesystem can be lost during redeploys, restarts, or instance replacement. A persistent disk supports one service instance; use managed PostgreSQL before scaling to multiple instances.

### Service commands

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT` (also in `Procfile`)
- Health check: `GET /health`

Render sets `RENDER=true`, so the app marks its session cookie secure automatically. For multiple app instances, configure `RATELIMIT_STORAGE_URI` with shared Redis so rate limits are consistent.

## API

All JSON responses use `success`, `data`, and `error` fields. Browser write requests require the CSRF token returned in the page's `csrf-token` meta tag as the `X-CSRF-Token` header.

- `GET /` — chatbot page and session CSRF token.
- `POST /api/chat` — `{ "conversation_id": 12, "message": "Who created it?" }`. Omit or set `conversation_id` to `null` to create a conversation when the first message is sent. Previous context is loaded from the selected database.
- `GET /api/conversations` — recent conversations; optional `?q=python` title search.
- `POST /api/conversations` — create an empty conversation.
- `GET /api/conversations/<id>` — conversation and messages.
- `DELETE /api/conversations/<id>` — delete a conversation and its messages.
- `GET /health` — application and database status.

The chat request body is limited to 16 KB, message text to 4,000 characters, and chat/write routes use the configured per-IP rate limit. Database errors return safe messages; internal traces, credentials, and connection details are kept out of API responses.

## Tests

Run the test suite with `python -m unittest discover -s tests -v`. Tests use temporary SQLite files and mocked Gemini responses, so they do not need API credentials. The PostgreSQL adapter can be configured by setting `DATABASE_URL` after installing the requirements.
