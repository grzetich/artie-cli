"""Detect documentation format from file content and extension."""

from pathlib import Path

from artie.parsers.openapi import parse
from artie.parsers.types import Endpoint, ParsedDocs

__all__ = [
    "detect_format",
    "display_format",
    "parse",
    "Endpoint",
    "ParsedDocs",
]

# Reported instead of the raw format when a page is really a spec wearing a
# markdown wrapper. Calling those pages "markdown" understates them: every
# structured check ran against a genuine OpenAPI document.
OPENAPI_PASSTHROUGH_LABEL = "OpenAPI passthrough"


def display_format(format_type: str, parsed: object | None = None) -> str:
    """Human-facing name for a detected format.

    Differs from `detect_format` only for spec-in-markdown pages. The raw
    format string stays the routing key everywhere internally — scores, the
    content-type mismatch warning, and the JSON `format` field all still use
    it — while this is what we put in front of a reader.
    """
    if (
        format_type == "markdown"
        and parsed is not None
        and getattr(parsed, "extracted_from", None) == "markdown"
        and getattr(parsed, "is_openapi", False)
    ):
        return OPENAPI_PASSTHROUGH_LABEL
    return format_type


def detect_format(
    content: str, path: Path | None = None, hint: str | None = None
) -> str:
    """Detect the documentation format.

    Returns one of: openapi-yaml, openapi-json, yaml, json, markdown, html, unknown.

    If `hint` is provided (typically from an HTTP Content-Type header), it
    overrides extension-based detection but still defers to OpenAPI markers
    in the content.
    """
    suffix = path.suffix.lower() if path else ""
    stripped = content.lstrip()

    # JSON detection
    if hint == "json" or suffix == ".json" or stripped.startswith("{"):
        if _looks_like_openapi(stripped):
            return "openapi-json"
        return "json"

    # HTML detection
    if (
        hint == "html"
        or suffix in (".html", ".htm")
        or stripped.lower().startswith(("<!doctype", "<html"))
    ):
        return "html"

    # Markdown detection
    if hint == "markdown" or suffix in (".md", ".markdown"):
        return "markdown"

    # YAML detection (after JSON to avoid swallowing JSON files)
    if hint == "yaml" or suffix in (".yaml", ".yml") or _looks_like_yaml(stripped):
        if _looks_like_openapi(stripped):
            return "openapi-yaml"
        return "yaml"

    # Heuristic markdown fallback for unmarked text content
    if "# " in stripped[:500] or "## " in stripped[:500]:
        return "markdown"

    return "unknown"


def _looks_like_openapi(content: str) -> bool:
    """Cheap check for OpenAPI markers without full parsing."""
    head = content[:2000].lower()
    return (
        "openapi:" in head
        or '"openapi"' in head
        or "swagger:" in head
        or '"swagger"' in head
    )


def _looks_like_yaml(content: str) -> bool:
    """Loose YAML detection based on key-value patterns at line starts."""
    lines = content.split("\n", 20)
    yaml_like_lines = sum(
        1
        for line in lines
        if line and not line.startswith(("#", " ", "-")) and ": " in line
    )
    return yaml_like_lines >= 2
