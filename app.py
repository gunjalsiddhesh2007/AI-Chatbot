import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from utils.ai_service import AIServiceError, generate_response

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.config["RATELIMIT_DEFAULT"] = os.getenv("RATE_LIMIT", "10 per hour")

    limiter = Limiter(get_remote_address, app=app, default_limits=[],
                      storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/chat")
    @limiter.limit(os.getenv("RATE_LIMIT", "10 per hour"))
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(success=False, error="Please send a valid JSON request."), 400
        message = payload.get("message")
        history = payload.get("history", [])
        if not isinstance(message, str) or not message.strip():
            return jsonify(success=False, error="Please enter a message."), 400
        if len(message) > 4000:
            return jsonify(success=False, error="Messages must be 4,000 characters or fewer."), 400
        if not isinstance(history, list) or len(history) > 20:
            return jsonify(success=False, error="Conversation context is invalid. Please clear the chat."), 400
        clean_history = []
        for item in history:
            if not isinstance(item, dict) or item.get("role") not in ("user", "assistant") or not isinstance(item.get("content"), str):
                return jsonify(success=False, error="Conversation context is invalid. Please clear the chat."), 400
            if len(item["content"]) > 4000:
                return jsonify(success=False, error="Conversation context is too large. Please clear the chat."), 400
            clean_history.append({"role": item["role"], "content": item["content"]})
        try:
            answer = generate_response(message.strip(), clean_history)
            return jsonify(success=True, response=answer)
        except AIServiceError as exc:
            return jsonify(success=False, error=str(exc)), 503
        except Exception:
            app.logger.exception("Unexpected chat request failure")
            return jsonify(success=False, error="Something went wrong. Please try again."), 500

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(success=False, error="That request is too large."), 413

    @app.errorhandler(429)
    def rate_limit_exceeded(_error):
        return jsonify(success=False, error="You have reached the chat limit. Please try again later."), 429

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
