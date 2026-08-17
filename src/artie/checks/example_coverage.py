"""Example Coverage check.

Scores documentation based on whether each endpoint provides request and
response examples that an agent could actually copy. Examples are the
strongest single signal that lets agents generate working code, because they
show the shape the API actually returns rather than just the schema it claims
to return.

An example only counts if it holds up:

1. It parses. An `example` key holding truncated or malformed JSON is worse
   than no example, because an agent will copy it verbatim.
2. It agrees with its schema. An example that omits required properties or
   contradicts the declared type teaches the agent the wrong shape.

Two subscores:

1. Response examples: every operation should show what a successful response
   looks like, somewhere in the operation (either at the media type level
   `example`/`examples`, or in the schema `example` field).
2. Request examples: every operation that accepts a request body should show
   a sample request body in the same way.

Examples that are present but broken are reported separately from examples
that are missing, because they are different authoring problems.
"""

from dataclasses import dataclass, field
from typing import Any

from artie.checks._schema_utils import parse_example, validate_example
from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import Endpoint, ParsedDocs


@dataclass
class ExampleAssessment:
    """What we found when we looked at one operation's examples."""

    present: bool = False
    valid: bool = False
    unverified: int = 0
    problems: list[str] = field(default_factory=list)


class ExampleCoverageCheck(BaseCheck):
    name = "Example Coverage"
    description = (
        "Endpoints with request and response examples that parse and match "
        "their schema."
    )

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

        components = parsed.components if isinstance(parsed.components, dict) else {}

        response_valid = 0
        response_broken = 0
        request_bodies = 0
        request_valid = 0
        request_broken = 0

        missing_response_examples: list[str] = []
        missing_request_examples: list[str] = []
        broken_examples: list[str] = []

        for endpoint in endpoints:
            assessment = _assess_response_example(endpoint, components)
            if assessment.valid:
                response_valid += 1
            elif assessment.present:
                response_broken += 1
                broken_examples.append(
                    f"{endpoint.display} response: {assessment.problems[0]}"
                )
            else:
                missing_response_examples.append(endpoint.display)

            request_body = endpoint.operation.get("requestBody")
            if isinstance(request_body, dict):
                request_bodies += 1
                assessment = _assess_content_examples(
                    request_body.get("content"), components
                )
                if assessment.valid:
                    request_valid += 1
                elif assessment.present:
                    request_broken += 1
                    broken_examples.append(
                        f"{endpoint.display} request: {assessment.problems[0]}"
                    )
                else:
                    missing_request_examples.append(endpoint.display)

        response_ratio = response_valid / len(endpoints)
        if request_bodies == 0:
            subscores = [response_ratio]
        else:
            subscores = [response_ratio, request_valid / request_bodies]

        composite = sum(subscores) / len(subscores)
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        findings = [
            f"{response_valid} of {len(endpoints)} endpoints have a usable "
            f"response example"
        ]
        if response_broken:
            findings.append(
                f"{response_broken} response example"
                f"{'s' if response_broken != 1 else ''} present but unusable "
                f"(malformed, or contradicts the schema)"
            )
        if request_bodies:
            findings.append(
                f"{request_valid} of {request_bodies} endpoints with a request "
                f"body have a usable request example"
            )
            if request_broken:
                findings.append(
                    f"{request_broken} request example"
                    f"{'s' if request_broken != 1 else ''} present but unusable"
                )
        else:
            findings.append(
                "No endpoints accept a request body, so request examples are "
                "not applicable."
            )
        for detail in broken_examples[:5]:
            findings.append(f"  ✗ {detail}")
        if len(broken_examples) > 5:
            findings.append(f"  ...and {len(broken_examples) - 5} more")

        recommendations: list[str] = []
        if broken_examples:
            recommendations.append(
                "Fix the examples that are present but broken before adding "
                "new ones. A malformed or schema-contradicting example is "
                "worse than no example: agents copy it verbatim, so it "
                "actively produces wrong code."
            )
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
                "endpoints_with_response_examples": response_valid,
                "endpoints_with_broken_response_examples": response_broken,
                "endpoints_with_request_body": request_bodies,
                "endpoints_with_request_examples": request_valid,
                "endpoints_with_broken_request_examples": request_broken,
                "broken_examples": broken_examples,
            },
        )


def _assess_response_example(
    endpoint: Endpoint, components: dict[str, Any]
) -> ExampleAssessment:
    """Assess examples on the 2xx responses of this operation."""
    responses = endpoint.operation.get("responses") or {}
    if not isinstance(responses, dict):
        return ExampleAssessment()

    combined = ExampleAssessment()
    for status, response in responses.items():
        if not isinstance(response, dict) or not _is_success_status(status):
            continue
        assessment = _assess_content_examples(response.get("content"), components)
        combined.present = combined.present or assessment.present
        combined.valid = combined.valid or assessment.valid
        combined.unverified += assessment.unverified
        combined.problems.extend(assessment.problems)
    return combined


def _assess_content_examples(
    content: Any, components: dict[str, Any]
) -> ExampleAssessment:
    """Assess every example in a content map against its media type schema.

    One usable example anywhere in the map is enough to count the operation as
    covered — agents need one correct shape, not every media type annotated.
    """
    result = ExampleAssessment()
    if not isinstance(content, dict):
        return result

    for media_type in content.values():
        if not isinstance(media_type, dict):
            continue
        schema = media_type.get("schema")
        for raw, verifiable in _candidate_examples(media_type):
            result.present = True
            if not verifiable:
                # An `externalValue` URL we deliberately don't fetch. Crediting
                # it is the honest call: we have no evidence it's broken, and
                # penalizing a legitimate authoring pattern would be wrong.
                result.valid = True
                result.unverified += 1
                continue
            ok, value, error = parse_example(raw)
            if not ok:
                result.problems.append(error or "example could not be parsed")
                continue
            violations = validate_example(value, schema, components)
            if violations:
                result.problems.extend(violations)
                continue
            result.valid = True

    return result


def _candidate_examples(media_type: dict[str, Any]) -> list[tuple[Any, bool]]:
    """Every example value attached to one media type object.

    Covers the three places OpenAPI allows one: `example`, the `value` of each
    entry under `examples`, and `schema.example`. Each is returned with a flag
    saying whether we can actually verify it — `externalValue` points at a URL
    we don't fetch, so it is present but unverifiable.
    """
    candidates: list[tuple[Any, bool]] = []

    if media_type.get("example") is not None:
        candidates.append((media_type["example"], True))

    examples = media_type.get("examples")
    if isinstance(examples, dict):
        for entry in examples.values():
            if isinstance(entry, dict):
                if entry.get("value") is not None:
                    candidates.append((entry["value"], True))
                elif entry.get("externalValue"):
                    candidates.append((entry["externalValue"], False))
            elif entry is not None:
                candidates.append((entry, True))

    schema = media_type.get("schema")
    if isinstance(schema, dict) and schema.get("example") is not None:
        candidates.append((schema["example"], True))

    return candidates


def _is_success_status(status: Any) -> bool:
    """2xx codes count as success. `default` is ambiguous; skip it for this check."""
    return str(status).startswith("2")
