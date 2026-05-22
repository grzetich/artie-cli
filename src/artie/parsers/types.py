"""Shared data structures for parsed documentation."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Endpoint:
    """A single API operation extracted from an OpenAPI document."""

    path: str
    method: str
    operation: dict[str, Any]

    @property
    def display(self) -> str:
        return f"{self.method.upper()} {self.path}"

    @property
    def summary(self) -> str | None:
        return self.operation.get("summary")

    @property
    def description(self) -> str | None:
        return self.operation.get("description")

    @property
    def operation_id(self) -> str | None:
        return self.operation.get("operationId")

    @property
    def parameters(self) -> list[dict[str, Any]]:
        return self.operation.get("parameters", []) or []


@dataclass
class ParsedDocs:
    """Structured view of parsed documentation, when parsing is possible."""

    raw: dict[str, Any] | None
    format: str
    endpoints: list[Endpoint] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None
    extracted_from: str | None = None  # "markdown" if spec was inside a code fence

    @property
    def parsed(self) -> bool:
        return self.raw is not None and self.parse_error is None

    @property
    def is_openapi(self) -> bool:
        return self.parsed and bool(self.raw and self.raw.get("openapi"))
