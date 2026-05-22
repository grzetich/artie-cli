"""Example Coverage check.

Scores documentation based on whether each endpoint provides request and
response examples. Examples are the strongest single signal that lets agents
generate working code, because they show the shape the API actually returns
rather than just the schema it claims to return.

Two subscores:

1. Response examples: every operation should show what a successful response
   looks like, somewhere in the operation (either at the media type level
   `example`/`examples`, or in the schema `example` field).
2. Request examples: every operation that accepts a request body should show
   a sample request body in the same way.
"""

from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import Endpoint, ParsedDocs


class ExampleCoverageCheck(BaseCheck):
    name = "Example Coverage"
    description = "Endpoints with request and response body examples."

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Example Coverage requires a parsed OpenAPI document."
            )

        endpoints = parsed.endpoints
        if not endpoints:
            return self.not_evaluable("No endpoints found in paths section.")

        endpoints_with_response_example = 0
        endpoints_with_request_body = 0
        endpoints_with_request_example = 0

        missing_response_examples: list[str] = []
        missing_request_examples: list[str] = []

        for endpoint in endpoints:
            if _has_response_example(endpoint):
                endpoints_with_response_example += 1
            else:
                missing_response_examples.append(endpoint.display)

            request_body = endpoint.operation.get("requestBody")
            if isinstance(request_body, dict):
                endpoints_with_request_body += 1
                if _has_request_example(request_body):
                    endpoints_with_request_example += 1
                else:
                    missing_request_examples.append(endpoint.display)

        response_ratio = endpoints_with_response_example / len(endpoints)
        if endpoints_with_request_body == 0:
            subscores = [response_ratio]
        else:
            request_ratio = endpoints_with_request_example / endpoints_with_request_body
            subscores = [response_ratio, request_ratio]

        composite = sum(subscores) / len(subscores)
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        findings = [
            f"{endpoints_with_response_example} of {len(endpoints)} endpoints "
            f"have a response example"
        ]
        if endpoints_with_request_body:
            findings.append(
                f"{endpoints_with_request_example} of {endpoints_with_request_body} "
                f"endpoints with a request body have a request example"
            )
        else:
            findings.append("No endpoints accept a request body, so request examples are not applicable.")

        recommendations: list[str] = []
        if missing_response_examples:
            sample = ", ".join(missing_response_examples[:5])
            recommendations.append(
                "Add a response example to every operation. TNJ data shows "
                "examples are the strongest single predictor of correct "
                f"generated code. Missing on: {sample}"
                + ("..." if len(missing_response_examples) > 5 else "")
            )
        if missing_request_examples:
            sample = ", ".join(missing_request_examples[:5])
            recommendations.append(
                "Add a request example to every operation that accepts a body. "
                f"Missing on: {sample}"
                + ("..." if len(missing_request_examples) > 5 else "")
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
                "endpoints_with_response_examples": endpoints_with_response_example,
                "endpoints_with_request_body": endpoints_with_request_body,
                "endpoints_with_request_examples": endpoints_with_request_example,
            },
        )


def _has_response_example(endpoint: Endpoint) -> bool:
    """True if any 2xx response on this operation carries an example."""
    responses = endpoint.operation.get("responses") or {}
    if not isinstance(responses, dict):
        return False
    for status, response in responses.items():
        if not isinstance(response, dict):
            continue
        if not _is_success_status(status):
            continue
        if _content_has_example(response.get("content")):
            return True
    return False


def _has_request_example(request_body: dict[str, Any]) -> bool:
    """True if the requestBody contains an example at any media type."""
    return _content_has_example(request_body.get("content"))


def _content_has_example(content: Any) -> bool:
    """Walk a content map looking for `example`, `examples`, or schema.example."""
    if not isinstance(content, dict):
        return False
    for media_type in content.values():
        if not isinstance(media_type, dict):
            continue
        if media_type.get("example") is not None:
            return True
        if media_type.get("examples"):
            return True
        schema = media_type.get("schema")
        if isinstance(schema, dict) and schema.get("example") is not None:
            return True
    return False


def _is_success_status(status: str) -> bool:
    """2xx codes count as success. `default` is ambiguous; skip it for this check."""
    status_str = str(status)
    return status_str.startswith("2")
