"""Minimal Anthropic Messages API client using stdlib urllib.

We avoid pulling in the full anthropic SDK because we make exactly one kind
of call (a single Messages request, no streaming, no batching) and adding
httpx + pydantic + the SDK itself doubles our cold-start time under uvx.
"""

import json
import os
import random
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TIMEOUT = 60

# Transient errors we should retry. 429 = rate limited, 503 = service
# unavailable, 529 = Anthropic-specific overloaded response.
RETRY_STATUS_CODES = {429, 503, 529}
MAX_RETRIES = 3


@dataclass
class GenerationResult:
    """A successful generation response."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


class GenerationError(Exception):
    """Raised when the generation call fails."""


class MissingAPIKeyError(GenerationError):
    """Raised when ANTHROPIC_API_KEY is not available."""


def has_api_key() -> bool:
    """Return True if ANTHROPIC_API_KEY is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> GenerationResult:
    """Call the Anthropic Messages API and return the assistant's text response.

    Reads the API key from ANTHROPIC_API_KEY. Raises MissingAPIKeyError if
    the key is unavailable, GenerationError for any other failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY is not set. Export it to enable the "
            "Sample Generation check."
        )

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    payload = json.dumps(body).encode("utf-8")

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        request = Request(
            API_URL,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
            },
        )

        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            last_exc = exc
            if exc.code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                wait_seconds = _retry_delay(exc, attempt)
                time.sleep(wait_seconds)
                continue
            detail = ""
            if exc.fp is not None:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
            if exc.code in RETRY_STATUS_CODES:
                raise GenerationError(
                    f"Anthropic API is temporarily overloaded (HTTP {exc.code}) "
                    f"after {MAX_RETRIES + 1} attempts. Wait a few minutes and "
                    f"try again, or omit --with-generation to skip this check."
                ) from exc
            if exc.code == 401:
                raise GenerationError(
                    "Anthropic API authentication failed (HTTP 401). Check that "
                    "ANTHROPIC_API_KEY is set correctly."
                ) from exc
            if exc.code == 400:
                raise GenerationError(
                    f"Anthropic API rejected the request (HTTP 400). "
                    f"Detail: {detail[:300]}"
                ) from exc
            raise GenerationError(
                f"Anthropic API HTTP {exc.code}: {exc.reason}. {detail[:300]}"
            ) from exc
        except URLError as exc:
            raise GenerationError(
                f"Could not reach Anthropic API: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise GenerationError(
                f"Anthropic API timed out after {timeout}s"
            ) from exc

        # Successful response.
        with response:
            try:
                data = json.loads(response.read())
            except json.JSONDecodeError as exc:
                raise GenerationError(
                    f"Could not decode API response: {exc}"
                ) from exc
        break
    else:
        # Loop exhausted without break (shouldn't happen given the raises above).
        raise GenerationError(
            f"Anthropic API failed after {MAX_RETRIES + 1} attempts: {last_exc}"
        )

    text = _extract_text(data)
    usage = data.get("usage") or {}
    return GenerationResult(
        text=text,
        model=data.get("model", model),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        stop_reason=data.get("stop_reason"),
    )


def _extract_text(data: dict) -> str:
    """Pull all text content blocks out of a Messages API response."""
    content = data.get("content") or []
    if not isinstance(content, list):
        return ""
    chunks = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            chunks.append(block.get("text", ""))
    return "".join(chunks)


def _retry_delay(exc: HTTPError, attempt: int) -> float:
    """Compute how long to wait before retrying a transient error.

    Honors the Retry-After header when present, otherwise uses exponential
    backoff with a small random jitter to avoid thundering-herd retries
    when multiple artie runs are firing at the same time.
    """
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except (TypeError, ValueError):
            pass
    base = 2 ** (attempt + 1)  # 2s, 4s, 8s for attempts 0, 1, 2
    jitter = random.uniform(0, 1)
    return base + jitter
