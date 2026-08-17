"""Shared fixtures and builders for the artie test suite."""

from typing import Any

import pytest

from artie.parsers.types import Endpoint, ParsedDocs


def make_endpoint(
    path: str = "/things",
    method: str = "get",
    **operation: Any,
) -> Endpoint:
    """Build an Endpoint from keyword operation fields."""
    return Endpoint(path=path, method=method, operation=dict(operation))


def make_docs(
    endpoints: list[Endpoint] | None = None,
    components: dict[str, Any] | None = None,
    raw: dict[str, Any] | None = None,
    format_type: str = "openapi-yaml",
) -> ParsedDocs:
    """Build a ParsedDocs that reports as a parsed OpenAPI document.

    `raw` defaults to a minimal spec so `is_openapi` is true; pass one
    explicitly when a test needs `servers` or other top-level keys.
    """
    return ParsedDocs(
        raw=raw if raw is not None else {"openapi": "3.0.0"},
        format=format_type,
        endpoints=endpoints or [],
        components=components or {},
    )


def json_body(schema: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A `content` map with one application/json media type."""
    media: dict[str, Any] = {"schema": schema}
    media.update(extra)
    return {"application/json": media}


@pytest.fixture
def endpoint_factory():
    return make_endpoint


@pytest.fixture
def docs_factory():
    return make_docs
