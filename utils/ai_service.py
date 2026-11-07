"""Provider integration. Gemini is primary; Groq remains as a legacy fallback."""

import os

from dotenv import load_dotenv

load_dotenv()

SYSTEM_INSTRUCTION = (
    "You are a helpful, clear, and conversational assistant. Use Markdown when it improves "
    "readability, including headings, lists, tables, and fenced code blocks. Keep simple "
    "answers brief and organize longer answers into clear sections. Explain technical terms "
    "in plain language and never claim certainty when you are unsure."
)


class AIServiceError(Exception):
    """Safe, user-facing error from an AI provider."""


def _configured_key(name):
    key = os.getenv(name, "").strip()
    if not key or key.lower().startswith("your_"):
        return ""
    return key


def _max_output_tokens():
    try:
        value = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048"))
    except (TypeError, ValueError):
        value = 2048
    return min(max(value, 1), 8192)


def _gemini_response(api_key, message, history):
    from google import genai
    from google.genai import types

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    contents = []
    for turn in history or []:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=turn["content"])])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    )

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                max_output_tokens=_max_output_tokens(),
            ),
        )
        answer = (response.text or "").strip()
        if not answer:
            raise AIServiceError("Gemini returned an empty response. Please try again.")
        return answer
    finally:
        client.close()


def _groq_response(api_key, message, history):
    from groq import Groq

    messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    messages.extend(
        {"role": turn["role"], "content": turn["content"]}
        for turn in (history or [])
    )
    messages.append({"role": "user", "content": message})
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b",
        messages=messages,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise AIServiceError("The AI provider returned an empty response. Please try again.")
    return answer


def _safe_provider_error(exc, provider):
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    text = str(exc).lower()
    if status in (401, 403) or "api key" in text or "unauthorized" in text:
        return AIServiceError(f"{provider} could not authenticate. Check the API key in the server environment.")
    if status == 429 or "rate limit" in text or "resource_exhausted" in text:
        return AIServiceError(f"{provider} is receiving too many requests. Please try again shortly.")
    return AIServiceError(f"{provider} is temporarily unavailable. Please try again shortly.")


def generate_response(message, history=None):
    """Generate a reply from persisted conversation context plus the latest message."""
    gemini_key = _configured_key("GEMINI_API_KEY")
    if gemini_key:
        try:
            return _gemini_response(gemini_key, message, history or [])
        except AIServiceError:
            raise
        except Exception as exc:
            raise _safe_provider_error(exc, "Gemini") from None

    # Keep Phase 1 deployments functional while they migrate from the existing Groq setup.
    groq_keys = []
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_2"):
        key = _configured_key(name)
        if key and key not in groq_keys:
            groq_keys.append(key)
    if not groq_keys:
        raise AIServiceError("Gemini is not configured yet. Add GEMINI_API_KEY to the server environment.")

    last_error = None
    for key in groq_keys:
        try:
            return _groq_response(key, message, history or [])
        except AIServiceError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
    if isinstance(last_error, AIServiceError):
        raise last_error
    raise _safe_provider_error(last_error, "The AI provider") from None
