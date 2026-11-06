import os

from dotenv import load_dotenv

load_dotenv()


class AIServiceError(Exception):
    """Safe, user-facing error from the AI provider integration."""


def generate_response(message, history=None):
    api_keys = []
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_2"):
        key = os.getenv(name, "").strip()
        if key and key not in ("your_groq_api_key", "your_backup_groq_api_key") and key not in api_keys:
            api_keys.append(key)
    if not api_keys:
        raise AIServiceError("Groq is not configured yet. Add an API key to the server environment.")

    try:
        from groq import Groq
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
        messages = []
        for turn in (history or [])[-20:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        last_error = None
        for api_key in api_keys:
            try:
                client = Groq(api_key=api_key)
                response = client.chat.completions.create(model=model, messages=messages)
                answer = (response.choices[0].message.content or "").strip()
                if answer:
                    return answer
                last_error = AIServiceError("Groq returned an empty response.")
            except Exception as exc:
                last_error = exc

        status = getattr(last_error, "status_code", None) or getattr(last_error, "code", None)
        error_text = str(last_error).lower()
        if status in (401, 403) or "api key" in error_text or "unauthorized" in error_text:
            raise AIServiceError("Groq could not authenticate with either configured API key. Check the keys in your server environment.") from None
        if status == 429:
            raise AIServiceError("Groq is receiving too many requests on both configured API keys. Please try again shortly.") from None
        raise AIServiceError("Groq is temporarily unavailable on both configured API keys. Please try again shortly.") from None
    except AIServiceError:
        raise
    except Exception:
        raise AIServiceError("Groq is temporarily unavailable. Please try again shortly.") from None
