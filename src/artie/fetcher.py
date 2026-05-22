"""Fetch documentation from HTTP/HTTPS URLs using stdlib only.

Returns the raw content plus a hint about the format based on Content-Type
and URL path. Format detection in `parsers/__init__.py` makes the final call
using both the hint and the content itself.
"""

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "artie-cli/0.3 (+https://artie.fm)"
DEFAULT_TIMEOUT = 20
MAX_BYTES = 10 * 1024 * 1024  # 10MB cap so we don't load multi-gig docs


@dataclass
class FetchResult:
    """A successfully fetched document."""

    url: str
    final_url: str
    content: str
    content_type: str
    format_hint: str | None
    status_code: int


class FetchError(Exception):
    """Raised when fetching fails for any reason."""


def is_url(value: str) -> bool:
    """Return True if the value looks like an HTTP/HTTPS URL."""
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    """Fetch a URL and return its content along with format hints.

    Raises FetchError on any failure (network, HTTP status, decoding).
    """
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            # Ask for structured formats first, fall back to anything.
            "Accept": (
                "application/yaml, application/x-yaml, application/json, "
                "text/markdown, text/html;q=0.5, */*;q=0.3"
            ),
        },
    )

    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except URLError as exc:
        raise FetchError(f"Could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"Timeout after {timeout}s fetching {url}") from exc

    with response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise FetchError(
                f"Response exceeds {MAX_BYTES // (1024 * 1024)}MB cap; "
                "fetch a smaller file or specific endpoint."
            )
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
        status = response.status

    # Decode using the declared charset, falling back to utf-8 with replacement.
    charset = _extract_charset(content_type) or "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")

    format_hint = _format_hint_from(content_type, final_url)

    return FetchResult(
        url=url,
        final_url=final_url,
        content=text,
        content_type=content_type,
        format_hint=format_hint,
        status_code=status,
    )


def _extract_charset(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip().lower()
        if part.startswith("charset="):
            return part.split("=", 1)[1].strip()
    return None


def _format_hint_from(content_type: str, url: str) -> str | None:
    """Map Content-Type and URL suffix to one of the format detector's labels."""
    ct = content_type.lower()
    path = urlparse(url).path.lower()

    if "yaml" in ct or path.endswith((".yaml", ".yml")):
        return "yaml"
    if "json" in ct or path.endswith(".json"):
        return "json"
    if "markdown" in ct or path.endswith((".md", ".markdown")):
        return "markdown"
    if "html" in ct or path.endswith((".html", ".htm")):
        return "html"
    return None
