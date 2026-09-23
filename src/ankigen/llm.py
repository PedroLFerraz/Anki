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

# A *daily* cap, as opposed to a per-minute one. Both arrive as 429s and both
# carry a "retry in 47s" hint, but waiting out a daily quota inside one run is
# hopeless: it cost a CI job 23 minutes of sleeping before the job timed out.
_DAILY_QUOTA = re.compile(r"per[-_ ]?day", re.IGNORECASE)


# Models whose daily allowance ran out during this run; asking again just
# spends the retry budget to be told the same thing.
_spent: set[str] = set()


class QuotaExhausted(RuntimeError):
    """The provider's allowance for the day is gone. Nothing to wait for."""


def _is_retryable(message: str) -> bool:
    msg = message.lower()
    return any(token in msg for token in _RETRYABLE)


def _is_daily_quota(message: str) -> bool:
    return bool(_DAILY_QUOTA.search(message))


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
        try:
            from google import genai
        except ImportError as e:      # pragma: no cover - env-specific
            raise RuntimeError(
                "LLM_PROVIDER=gemini needs the google-genai package, which is an "
                "optional dependency: pip install 'ankigen[gemini]' (or "
                "pip install google-genai)."
            ) from e
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


def preflight() -> None:
    """Check the configured providers could work, before any work is done.

    Makes no network call, so it costs nothing against a metered free tier. It
    exists because a missing optional dependency was only discovered after
    ingest and targeting had run, and then reported once per request.
    """
    for label, cfg in (("LLM_PROVIDER", settings.resolve_llm()),
                       ("the card checker (VERIFY_PROVIDER)", settings.resolve_verify())):
        provider, model = cfg["provider"], cfg["model"]
        if not model:
            raise RuntimeError(f"{label} is {provider} but no model is configured.")
        if provider == "gemini":
            if not settings.google_api_key:
                raise RuntimeError(f"{label} is gemini but GOOGLE_API_KEY is empty.")
            _get_gemini_client()                  # raises if google-genai is missing
        elif cfg.get("needs_key") and not cfg.get("api_key"):
            raise RuntimeError(f"{label} is {provider} but LLM_API_KEY is empty.")


def _call_one_model(prompt: str, cfg: dict, model: str, max_retries: int) -> LLMResult:
    """One model, retried. Raises QuotaExhausted when its day is done."""
    ensure_free(cfg["provider"], model, settings.allow_paid_models)
    for attempt in range(max_retries):
        try:
            if cfg["provider"] == "gemini":
                from google.genai import types
                client = _get_gemini_client()
                if not client:
                    raise RuntimeError("No GOOGLE_API_KEY configured")
                response = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                meta = getattr(response, "usage_metadata", None)
                return LLMResult(
                    json.loads(response.text), model,
                    getattr(meta, "prompt_token_count", 0) or 0,
                    getattr(meta, "candidates_token_count", 0) or 0,
                )
            client = _get_openai_client(cfg["base_url"], cfg["api_key"])
            text, p_tok, c_tok = _chat_json(client, model, prompt)
            return LLMResult(json.loads(text), model, p_tok, c_tok)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                raise
        except Exception as e:
            msg = str(e)
            if _is_daily_quota(msg):
                raise QuotaExhausted(msg) from e
            if _is_retryable(msg) and attempt < max_retries - 1:
                match = re.search(r"(?:retryDelay|try again in)\D*?(\d+(?:\.\d+)?)s", msg)
                # The provider's own hint wins; otherwise back off exponentially
                # rather than linearly, since an overloaded model stays that way
                # for longer than the 5s and 10s a linear ramp waited.
                wait = min(90.0, float(match.group(1)) + 2) if match else min(60, 5 * 2 ** attempt)
                logger.info("%s busy (%s); waiting %.0fs (attempt %d/%d)",
                            model, msg[:60], wait, attempt + 1, max_retries)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")


def call_json(prompt: str, max_retries: int = 5, cfg: dict | None = None) -> LLMResult:
    """One JSON completion, working down the configured chain of models.

    Two things make a chain worth having rather than a single model. Free tiers
    meter per model and give about twenty requests a day each, so the best
    model runs out mid-run; and the newest models are the busiest, answering
    503 for minutes at a time while the previous one replies instantly. Either
    way the answer is the same: move down the list and keep going.

    Retries are patient within a model — a daily batch has nobody waiting on it
    — but a model whose allowance is gone is skipped for the rest of the
    process rather than asked again once per request.
    """
    cfg = cfg or settings.resolve_llm()
    chain = [m for m in (cfg.get("models") or [cfg["model"]]) if m]
    usable = [m for m in chain if m not in _spent]
    if not usable:
        raise QuotaExhausted(
            f"every configured model is out of quota for today: {', '.join(chain)}"
        )

    last: Exception | None = None
    for model in usable:
        try:
            return _call_one_model(prompt, cfg, model, max_retries)
        except QuotaExhausted as e:
            logger.warning("%s is out of quota for today; falling back", model)
            _spent.add(model)
            last = e
        except Exception as e:
            if not _is_retryable(str(e)):
                raise                       # a real error: bad key, bad request
            logger.warning("%s did not answer (%s); falling back", model, str(e)[:60])
            last = e

    if isinstance(last, QuotaExhausted):
        raise QuotaExhausted(
            f"every configured model is out of quota for today: {', '.join(usable)}"
        ) from last
    raise last
