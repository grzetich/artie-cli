"""Error Documentation check.

Scores documentation based on how well error responses are documented.
Connects directly to the TNJ Chapter 5 finding that DON's 98.2 percent
try/except adoption rate is what disciplined error documentation enables:
agents that can see what errors look like write code that handles them.

Three subscores:

1. Endpoint coverage: what fraction of operations document at least one
   4xx or 5xx response (or `default`).
2. Description quality: of the error responses that exist, how many carry
   a description longer than a token or two.
3. Schema coverage: of the error responses that exist, how many provide a
   content schema (so agents know the shape of the error envelope).

A shared Error schema in components.schemas is recognized as a positive
signal and bumps the description-quality score.
"""

from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import Endpoint, ParsedDocs


MEANINGFUL_DESCRIPTION_CHARS = 15


class ErrorDocumentationCheck(BaseCheck):
    name = "Error Documentation"
    description = (
        "4xx and 5xx responses with meaningful descriptions and content schemas."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Error Documentation requires a parsed OpenAPI document."
            )

        endpoints = parsed.endpoints
        if not endpoints:
            return self.not_evaluable("No endpoints found in paths section.")

        endpoints_with_errors = 0
        total_error_responses = 0
        errors_with_description = 0
        errors_with_schema = 0
        missing_errors: list[str] = []

        for endpoint in endpoints:
            error_responses = _error_responses(endpoint)
            if error_responses:
                endpoints_with_errors += 1
            else:
                missing_errors.append(endpoint.display)
            for response in error_responses:
                total_error_responses += 1
                if _has_meaningful_description(response):
                    errors_with_description += 1
                if _has_content_schema(response):
                    errors_with_schema += 1

        has_shared_error_schema = _has_shared_error_schema(parsed.components)

        endpoint_ratio = endpoints_with_errors / len(endpoints)
        if total_error_responses == 0:
            description_ratio = 0.0
            schema_ratio = 0.0
        else:
            description_ratio = errors_with_description / total_error_responses
            schema_ratio = errors_with_schema / total_error_responses

        if has_shared_error_schema:
            # Shared envelope is a real positive signal worth a bump on schema coverage.
            schema_ratio = min(1.0, schema_ratio + 0.2)

        composite = (endpoint_ratio + description_ratio + schema_ratio) / 3
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        findings = [
            f"{endpoints_with_errors} of {len(endpoints)} endpoints "
            f"document at least one error response",
            f"{errors_with_description} of {total_error_responses} error responses "
            f"have a meaningful description",
            f"{errors_with_schema} of {total_error_responses} error responses "
            f"have a content schema",
        ]
        if has_shared_error_schema:
            findings.append("Shared Error schema found in components.schemas")
        else:
            findings.append("No shared Error schema defined in components.schemas")

        recommendations: list[str] = []
        if missing_errors:
            sample = ", ".join(missing_errors[:5])
            recommendations.append(
                f"Document error responses on every operation. Missing on: {sample}"
                + ("..." if len(missing_errors) > 5 else "")
            )
        if total_error_responses and errors_with_description < total_error_responses:
            recommendations.append(
                "Replace boilerplate descriptions like 'error' or 'bad request' "
                "with specific text explaining when the error occurs and what "
                "the caller should do."
            )
        if total_error_responses and errors_with_schema < total_error_responses:
            recommendations.append(
                "Reference a shared Error schema from every error response. "
                "Agents can only handle errors whose shape is documented."
            )
        if not has_shared_error_schema:
            recommendations.append(
                "Define a reusable Error schema in components.schemas with "
                "fields like code, message, and (optionally) details. "
                "TNJ Chapter 5 showed this pattern produces the highest "
                "try/except adoption rate in generated code."
            )

        return CheckResult(
            name=self.name,
            description=self.description,
            score=score,
            max_score=self.max_score,
            severity=severity,
            findings=findings,
            recommendations=recommendations,
            metadata={
                "endpoints": len(endpoints),
                "endpoints_with_errors": endpoints_with_errors,
                "total_error_responses": total_error_responses,
                "errors_with_description": errors_with_description,
                "errors_with_schema": errors_with_schema,
                "has_shared_error_schema": has_shared_error_schema,
            },
        )


def _error_responses(endpoint: Endpoint) -> list[dict[str, Any]]:
    """Return all 4xx, 5xx, and `default` response objects on this operation."""
    responses = endpoint.operation.get("responses") or {}
    if not isinstance(responses, dict):
        return []
    out: list[dict[str, Any]] = []
    for status, response in responses.items():
        if not isinstance(response, dict):
            continue
        status_str = str(status)
        if status_str.startswith(("4", "5")) or status_str == "default":
            out.append(response)
    return out


def _has_meaningful_description(response: dict[str, Any]) -> bool:
    description = (response.get("description") or "").strip()
    return len(description) >= MEANINGFUL_DESCRIPTION_CHARS


def _has_content_schema(response: dict[str, Any]) -> bool:
    content = response.get("content")
    if not isinstance(content, dict):
        return False
    for media_type in content.values():
        if isinstance(media_type, dict) and media_type.get("schema"):
            return True
    return False


def _has_shared_error_schema(components: dict[str, Any]) -> bool:
    """True if components.schemas contains an Error-ish schema by common naming."""
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        return False
    keys_lower = {k.lower() for k in schemas.keys() if isinstance(k, str)}
    candidates = {"error", "errorresponse", "errorbody", "apierror", "problem", "problemdetails"}
    return bool(keys_lower & candidates)
