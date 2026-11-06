# AI ChatBot

A small Flask chatbot with a responsive vanilla JavaScript interface and Groq's official Python SDK. Conversation context is kept only in the browser for the current page session; no chat history is saved on the server.

## Run locally

1. Install Python 3.10 or newer.
2. Create and activate a virtual environment: `python -m venv .venv`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`, add a primary Groq API key (`GROQ_API_KEY`) and an optional backup (`GROQ_API_KEY_2`) from [Groq Console](https://console.groq.com/keys), and set a long random `FLASK_SECRET_KEY`.
5. Start the development server: `python app.py`, then visit `http://127.0.0.1:5000`.

The app tries `GROQ_API_KEY` first. If generation fails or returns an empty response, it retries with `GROQ_API_KEY_2` when configured. The default model is `openai/gpt-oss-120b`; change `GROQ_MODEL` to a model enabled for your API keys. Keys are read only by the Python backend.

## Deploy to Render

1. Push this project to a Git repository and create a **Web Service** on Render connected to it.
2. Set the build command to `pip install -r requirements.txt` and the start command to `gunicorn app:app --bind 0.0.0.0:$PORT` (also provided in `Procfile`).
3. Add `GROQ_API_KEY`, optionally `GROQ_API_KEY_2`, and a strong `FLASK_SECRET_KEY` under the service's Environment settings. Optionally set `GROQ_MODEL` and `RATE_LIMIT` (default `10 per hour`).
4. Deploy. The start command binds Gunicorn to Render's assigned port.

For multiple instances, configure `RATELIMIT_STORAGE_URI` with a shared Redis URL so rate limits are consistent across instances. The default in-memory limiter is suitable for a single instance and resets on restart.

## Endpoints

- `GET /` — chatbot page.
- `POST /api/chat` — JSON `{ "message": "...", "history": [] }`.
- `GET /health` — JSON health status.

Chat requests are capped at 16 KB; message text at 4,000 characters; context at 20 turns. The per-IP chat limit defaults to 10 requests per hour.
