"""LLM client: any OpenAI-compatible provider, plus Gemini's native SDK.

Ported from the v1 `core/agents.py`, reshaped so every call reports the model
and token usage — the run report needs both.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from ankigen.config import ensure_free, settings

logger = logging.getLogger(__name__)

_gemini_client = None
# Keyed by (base_url, api_key) so switching providers mid-process is safe.
_openai_clients: dict[tuple[str, str], object] = {}
# Models observed to reject response_format; skip JSON mode for them thereafter.
_no_json_mode: set[str] = set()


class TransientProviderError(RuntimeError):
    """A provider hiccup worth retrying (overloaded, rate limited, 5xx)."""


_RETRYABLE = ("429", "rate limit", "overload", "temporarily", "timeout",
              "502", "503", "504", "resource_exhausted")


def _is_retryable(message: str) -> bool:
    msg = message.lower()
    return any(token in msg for token in _RETRYABLE)


def _provider_error(response) -> str | None:
    """Aggregators can report failures *inside* a 200 response.

    OpenRouter returns {"error": {...}} with no `choices`, which the OpenAI SDK
    surfaces as choices=None. Without this check that became a TypeError deep in
    the parsing code instead of a retry.
    """
    if getattr(response, "choices", None):
        return None                      # a usable reply; nothing to report

    err = getattr(response, "error", None)
    extra = getattr(response, "model_extra", None)
    if err is None and isinstance(extra, dict):
        err = extra.get("error")
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    return "provider returned no choices"


@dataclass
class LLMResult:
    data: dict
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _get_gemini_client():
    global _gemini_client
    if not settings.google_api_key:
        return None
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.google_api_key)
    return _gemini_client


def _get_openai_client(base_url: str, api_key: str):
    cache_key = (base_url, api_key)
    if cache_key not in _openai_clients:
        from openai import OpenAI
        # Local servers ignore the key, but the SDK requires a non-empty string.
        _openai_clients[cache_key] = OpenAI(base_url=base_url, api_key=api_key or "none")
    return _openai_clients[cache_key]


def check_connection() -> str | None:
    """Error message if the configured provider is unreachable, else None."""
    cfg = settings.resolve_llm()
    provider = cfg["provider"]

    if provider == "gemini":
        return None if _get_gemini_client() else "No GOOGLE_API_KEY configured."

    if cfg["needs_key"] and not cfg["api_key"]:
        return f"No API key for '{provider}'. Set LLM_API_KEY in .env."

    base = (cfg["base_url"] or "").rstrip("/")
    try:
        import requests
        if provider == "ollama":
            resp = requests.get(f"{base.removesuffix('/v1')}/api/tags", timeout=5)
        else:
            headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
            resp = requests.get(f"{base}/models", headers=headers, timeout=10)
        resp.raise_for_status()
        return None
    except Exception as e:
        return f"Cannot connect to {provider} at {base}: {e}"


def extract_json(text: str) -> str:
    """Pull a JSON object out of a reply that may be fenced or wrapped in prose."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    if t.startswith("{"):
        return t
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return t[start:end + 1]
    return t


def _looks_like_json_mode_rejection(err: Exception) -> bool:
    msg = str(err).lower()
    return any(tok in msg for tok in ("response_format", "json_object", "json mode", "json_schema"))


def _usage(response) -> tuple[int, int]:
    u = getattr(response, "usage", None)
    return (getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


def _chat_json(client, model: str, prompt: str) -> tuple[str, int, int]:
    """Request JSON, degrading to text extraction where JSON mode is unsupported."""
    messages = [{"role": "user", "content": prompt}]
    if model not in _no_json_mode:
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, response_format={"type": "json_object"},
            )
            if (problem := _provider_error(response)):
                raise TransientProviderError(problem)
            return (response.choices[0].message.content or "", *_usage(response))
        except TransientProviderError:
            raise
        except Exception as e:
            if not _looks_like_json_mode_rejection(e):
                raise
            logger.info("%s rejects JSON mode; parsing JSON out of plain text.", model)
            _no_json_mode.add(model)

    response = client.chat.completions.create(model=model, messages=messages)
    if (problem := _provider_error(response)):
        raise TransientProviderError(problem)
    return (extract_json(response.choices[0].message.content or ""), *_usage(response))


def call_json(prompt: str, max_retries: int = 5, cfg: dict | None = None) -> LLMResult:
    """One JSON completion, with retries on rate limits and malformed JSON.

    Patient on purpose. Free tiers put everyone on the same popular models, so
    503 "experiencing high demand" is routine rather than exceptional — the
    newest Gemini flash answered none of seven requests one morning while the
    previous one answered in 1.5s. A daily batch has nobody waiting on it, so
    backing off for a minute beats losing the day's cards.
    """
    cfg = cfg or settings.resolve_llm()
    ensure_free(cfg["provider"], cfg["model"], settings.allow_paid_models)
    for attempt in range(max_retries):
        try:
            if cfg["provider"] == "gemini":
                from google.genai import types
                client = _get_gemini_client()
                if not client:
                    raise RuntimeError("No GOOGLE_API_KEY configured")
                response = client.models.generate_content(
                    model=cfg["model"], contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                meta = getattr(response, "usage_metadata", None)
                return LLMResult(
                    json.loads(response.text), cfg["model"],
                    getattr(meta, "prompt_token_count", 0) or 0,
                    getattr(meta, "candidates_token_count", 0) or 0,
                )
            client = _get_openai_client(cfg["base_url"], cfg["api_key"])
            text, p_tok, c_tok = _chat_json(client, cfg["model"], prompt)
            return LLMResult(json.loads(text), cfg["model"], p_tok, c_tok)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                raise
        except Exception as e:
            msg = str(e)
            if _is_retryable(msg) and attempt < max_retries - 1:
                match = re.search(r"(?:retryDelay|try again in)\D*?(\d+(?:\.\d+)?)s", msg)
                # The provider's own hint wins; otherwise back off exponentially
                # rather than linearly, since an overloaded model stays that way
                # for longer than the 5s and 10s a linear ramp waited.
                wait = float(match.group(1)) + 2 if match else min(60, 5 * 2 ** attempt)
                logger.info("Provider busy (%s); waiting %.0fs (attempt %d/%d)",
                            msg[:70], wait, attempt + 1, max_retries)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")
