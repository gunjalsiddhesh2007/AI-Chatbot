"""Flask entry point for the AI ChatBot."""

import hmac
import re
import secrets

from flask import Flask, jsonify, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from utils.ai_service import AIServiceError, generate_response
from utils.config import flask_settings
from utils.database import (
    ConversationNotFound,
    DatabaseError,
    check_database,
    create_conversation,
    create_conversation_with_first_message,
    delete_conversation,
    get_context_messages,
    get_conversation,
    initialize_database,
    list_conversations,
    save_message,
)


def _json_response(data=None, error=None, status=200, **legacy_fields):
    payload = {"success": error is None, "data": data, "error": error}
    # Keep the original Phase 1 response field available to existing clients.
    payload.update(legacy_fields)
    return jsonify(payload), status


def _conversation_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Conversation ID is invalid.")
    if isinstance(value, str) and not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        raise ValueError("Conversation ID is invalid.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("Conversation ID is invalid.") from None
    if parsed < 1 or parsed > 9223372036854775807:
        raise ValueError("Conversation ID is invalid.")
    return parsed


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.update(flask_settings())
    if config_overrides:
        app.config.update(config_overrides)

    database_target = app.config["DATABASE_URL"] or app.config["DATABASE_PATH"]
    initialize_database(database_target)
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri=app.config["RATELIMIT_STORAGE_URI"],
    )

    @app.before_request
    def protect_api_writes():
        if request.method in {"POST", "DELETE"} and request.path.startswith("/api/"):
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return _json_response(error="This request could not be verified. Refresh the page and try again.", status=403)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.get("/")
    def index():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return render_template("index.html", csrf_token=session["csrf_token"])

    @app.get("/health")
    def health():
        try:
            check_database(database_target)
            return _json_response({"status": "ok"})
        except DatabaseError:
            return _json_response({"status": "unavailable"}, error="Service temporarily unavailable.", status=503)

    @app.get("/api/conversations")
    def conversations():
        search = request.args.get("q", "").strip()[:120]
        try:
            items = list_conversations(database_target, search)
            return _json_response({"conversations": items})
        except DatabaseError:
            app.logger.exception("Could not list conversations")
            return _json_response(error="Chat history is temporarily unavailable.", status=503)

    @app.post("/api/conversations")
    @limiter.limit(app.config["RATE_LIMIT"])
    def new_conversation():
        try:
            conversation = create_conversation(database_target)
            return _json_response({"conversation": conversation}, status=201)
        except DatabaseError:
            app.logger.exception("Could not create a conversation")
            return _json_response(error="A new conversation could not be created.", status=503)

    @app.get("/api/conversations/<conversation_id>")
    def load_conversation(conversation_id):
        try:
            parsed_id = _conversation_id(conversation_id)
        except ValueError:
            return _json_response(error="Conversation not found.", status=404)
        try:
            conversation = get_conversation(parsed_id, database_target)
            if conversation is None:
                return _json_response(error="Conversation not found.", status=404)
            return _json_response({"conversation": conversation})
        except DatabaseError:
            app.logger.exception("Could not load a conversation")
            return _json_response(error="Chat history is temporarily unavailable.", status=503)

    @app.delete("/api/conversations/<conversation_id>")
    @limiter.limit(app.config["RATE_LIMIT"])
    def remove_conversation(conversation_id):
        try:
            parsed_id = _conversation_id(conversation_id)
        except ValueError:
            return _json_response(error="Conversation not found.", status=404)
        try:
            deleted = delete_conversation(parsed_id, database_target)
            if not deleted:
                return _json_response(error="Conversation not found.", status=404)
            return _json_response({"conversation_id": parsed_id})
        except DatabaseError:
            app.logger.exception("Could not delete a conversation")
            return _json_response(error="The conversation could not be deleted.", status=503)

    @app.post("/api/chat")
    @limiter.limit(app.config["RATE_LIMIT"])
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_response(error="Please send a valid JSON request.", status=400)
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return _json_response(error="Please enter a message.", status=400)
        message = message.strip()
        if len(message) > 4000:
            return _json_response(error="Messages must be 4,000 characters or fewer.", status=400)

        try:
            provided_id = payload.get("conversation_id")
            if provided_id is None:
                conversation, user_message_id = create_conversation_with_first_message(
                    message, database_target
                )
                parsed_id = conversation["id"]
            else:
                parsed_id = _conversation_id(provided_id)
                if get_conversation(parsed_id, database_target) is None:
                    return _json_response(error="Conversation not found.", status=404)
                user_message = save_message(parsed_id, "user", message, database_target)
                user_message_id = user_message["id"]

            context = get_context_messages(
                parsed_id,
                before_message_id=user_message_id,
                window=app.config["CONTEXT_WINDOW"],
                max_chars=app.config["CONTEXT_MAX_CHARS"],
                path=database_target,
            )
        except ValueError:
            return _json_response(error="Conversation ID is invalid.", status=400)
        except ConversationNotFound:
            return _json_response(error="Conversation not found.", status=404)
        except DatabaseError:
            app.logger.exception("Could not save or retrieve chat history")
            return _json_response(error="Chat history is temporarily unavailable.", status=503)

        try:
            answer = generate_response(message, context)
        except AIServiceError as exc:
            return _json_response(
                {"conversation_id": parsed_id},
                error=str(exc),
                status=503,
                conversation_id=parsed_id,
            )
        except Exception:
            app.logger.exception("Unexpected chat request failure")
            return _json_response(
                {"conversation_id": parsed_id},
                error="Something went wrong. Please try again.",
                status=500,
                conversation_id=parsed_id,
            )

        try:
            save_message(parsed_id, "assistant", answer, database_target)
            conversation = get_conversation(parsed_id, database_target)
            result = {
                "conversation_id": parsed_id,
                "response": answer,
                "conversation": conversation,
            }
            return _json_response(result, response=answer, conversation_id=parsed_id)
        except DatabaseError:
            app.logger.exception("Could not save the AI response")
            return _json_response(
                {"conversation_id": parsed_id},
                error="The reply could not be saved. Please try again.",
                status=503,
                conversation_id=parsed_id,
            )

    @app.errorhandler(413)
    def request_too_large(_error):
        return _json_response(error="That request is too large.", status=413)

    @app.errorhandler(429)
    def rate_limit_exceeded(_error):
        return _json_response(error="You have reached the chat limit. Please try again later.", status=429)

    @app.errorhandler(500)
    def internal_error(_error):
        app.logger.exception("Unhandled application error")
        return _json_response(error="Something went wrong. Please try again.", status=500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
