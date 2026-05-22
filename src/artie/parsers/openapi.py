"""Parse OpenAPI documents from YAML or JSON content."""

import json
import re
from typing import Any

import yaml

from artie.parsers.types import Endpoint, ParsedDocs

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

# Match fenced code blocks. The fence language is captured separately so we
# can prefer yaml/json blocks when scanning markdown for an embedded spec.
_FENCE_PATTERN = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_+-]*)[^\n]*\n(?P<body>.*?)```",
    re.DOTALL,
)


def parse(content: str, format_type: str) -> ParsedDocs:
    """Parse documentation content into a structured view.

    Returns a ParsedDocs with raw=None and a parse_error message if parsing
    failed or the format isn't structured (e.g. HTML alone with no spec).

    For markdown, we additionally scan for an embedded OpenAPI spec inside
    code fences. Modern docs sites (Mintlify, Fern, ReadMe, Stainless) often
    embed the spec alongside prose and SDK examples, and that embedded spec
    is what we want to score the structured checks against.
    """
    if format_type in ("openapi-yaml", "yaml"):
        return _parse_yaml(content, format_type)
    if format_type in ("openapi-json", "json"):
        return _parse_json(content, format_type)
    if format_type == "markdown":
        return _parse_markdown(content, format_type)

    return ParsedDocs(
        raw=None,
        format=format_type,
        parse_error=f"No structured parser for format: {format_type}",
    )


def _parse_yaml(content: str, format_type: str) -> ParsedDocs:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return ParsedDocs(raw=None, format=format_type, parse_error=str(exc))
    return _build_parsed_docs(data, format_type)


def _parse_json(content: str, format_type: str) -> ParsedDocs:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return ParsedDocs(raw=None, format=format_type, parse_error=str(exc))
    return _build_parsed_docs(data, format_type)


def _parse_markdown(content: str, format_type: str) -> ParsedDocs:
    """Scan markdown for an embedded OpenAPI spec and parse it if found."""
    embedded = _extract_embedded_openapi(content)
    if not embedded:
        return ParsedDocs(
            raw=None,
            format=format_type,
            parse_error="No embedded OpenAPI spec found in markdown.",
        )
    embedded_body, embedded_lang = embedded
    if embedded_lang == "json":
        result = _parse_json(embedded_body, format_type)
    else:
        result = _parse_yaml(embedded_body, format_type)
    result.extracted_from = "markdown"
    return result


def _extract_embedded_openapi(content: str) -> tuple[str, str] | None:
    """Find an OpenAPI spec embedded in a markdown code fence.

    Returns (body, lang) where lang is 'yaml' or 'json'. The first fenced
    block whose body parses as an OpenAPI document (has an `openapi:` or
    `swagger:` top-level key) wins. We don't require the fence language to
    be set, since some docs sites omit it.
    """
    for match in _FENCE_PATTERN.finditer(content):
        body = match.group("body")
        stripped = body.lstrip()
        # YAML-style OpenAPI marker
        if stripped.startswith(("openapi:", "swagger:")):
            return (body, "yaml")
        # JSON-style OpenAPI marker
        if stripped.startswith("{"):
            head = stripped[:1000].lower()
            if '"openapi"' in head or '"swagger"' in head:
                return (body, "json")
    return None


def _build_parsed_docs(data: Any, format_type: str) -> ParsedDocs:
    if not isinstance(data, dict):
        return ParsedDocs(
            raw=None,
            format=format_type,
            parse_error="Top-level document is not a mapping.",
        )
    endpoints = _extract_endpoints(data)
    components = data.get("components") or {}
    return ParsedDocs(
        raw=data,
        format=format_type,
        endpoints=endpoints,
        components=components if isinstance(components, dict) else {},
    )


def _extract_endpoints(data: dict[str, Any]) -> list[Endpoint]:
    """Walk paths and pull out one Endpoint per (path, method) pair."""
    paths = data.get("paths") or {}
    if not isinstance(paths, dict):
        return []

    endpoints: list[Endpoint] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for key, value in path_item.items():
            if key.lower() in HTTP_METHODS and isinstance(value, dict):
                endpoints.append(
                    Endpoint(path=path, method=key.lower(), operation=value)
                )
    return endpoints


def path_parameters(path: str) -> list[str]:
    """Extract parameter names from an OpenAPI path template like /books/{bookId}."""
    params: list[str] = []
    in_brace = False
    current = ""
    for char in path:
        if char == "{":
            in_brace = True
            current = ""
        elif char == "}":
            if in_brace and current:
                params.append(current)
            in_brace = False
            current = ""
        elif in_brace:
            current += char
    return params
