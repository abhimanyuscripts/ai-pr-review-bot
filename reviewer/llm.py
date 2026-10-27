"""LLM providers: Google Gemini (free tier friendly) and Anthropic Claude.

Both are called over plain HTTPS with the standard library, so the bot has no
third-party dependencies.
"""

from __future__ import annotations

from .http import HTTPError, request_json

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

# Tried in order; the next one is used if a model is unavailable or rate-limited.
DEFAULT_GEMINI_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"


class LLMError(Exception):
    pass


def _gemini_text(response: dict) -> str:
    candidates = (response or {}).get("candidates") or []
    if not candidates:
        reason = ((response or {}).get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise LLMError(f"Gemini returned no answer ({reason})")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(f"Gemini returned an empty answer ({candidates[0].get('finishReason', 'unknown')})")
    return text


def call_gemini(api_key: str, system: str, user: str, models: list[str] | None = None) -> tuple[str, str]:
    """Return (response_text, model_used). Falls back across models on 404/429/5xx."""
    errors = []
    for model in models or DEFAULT_GEMINI_MODELS:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            response = request_json(
                "POST",
                f"{GEMINI_API}/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                payload=payload,
                timeout=120,
                retries=1,
            )
            return _gemini_text(response), model
        except HTTPError as exc:
            if exc.status in (401, 403) or "api key" in exc.body.lower():
                raise LLMError(f"Gemini rejected the API key (HTTP {exc.status}); check GEMINI_API_KEY") from None
            errors.append(f"{model}: HTTP {exc.status}")
        except LLMError as exc:
            errors.append(f"{model}: {exc}")
    raise LLMError("All Gemini models failed: " + "; ".join(errors))


def call_claude(api_key: str, system: str, user: str, model: str | None = None) -> tuple[str, str]:
    """Return (response_text, model_used) from the Anthropic Messages API."""
    model = model or DEFAULT_CLAUDE_MODEL
    try:
        response = request_json(
            "POST",
            ANTHROPIC_API,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            payload={
                "model": model,
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=120,
            retries=1,
        )
    except HTTPError as exc:
        raise LLMError(f"Claude API error (HTTP {exc.status})") from None
    text = "".join(b.get("text", "") for b in (response or {}).get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise LLMError("Claude returned an empty answer")
    return text, model


def resolve_provider(requested: str | None, gemini_key: str | None, anthropic_key: str | None) -> str:
    """Pick 'anthropic', 'gemini' or 'none' from the requested provider and available keys."""
    requested = (requested or "auto").strip().lower()
    if requested in ("anthropic", "claude"):
        return "anthropic" if anthropic_key else "none"
    if requested == "gemini":
        return "gemini" if gemini_key else "none"
    if requested == "none":
        return "none"
    if anthropic_key:
        return "anthropic"
    if gemini_key:
        return "gemini"
    return "none"
