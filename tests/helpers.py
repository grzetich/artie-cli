"""Shared helpers for the artie test suite."""

import json
from typing import Any

from artie.parsers.openapi import parse
from artie.parsers.types import ParsedDocs


def parsed(spec: dict[str, Any]) -> ParsedDocs:
    """Parse an OpenAPI spec dict into a ParsedDocs (via the JSON path)."""
    return parse(json.dumps(spec), "openapi-json")


def base_spec(**overrides: Any) -> dict[str, Any]:
    """A minimal valid OpenAPI 3 document; override any top-level key."""
    spec: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }
    spec.update(overrides)
    return spec
