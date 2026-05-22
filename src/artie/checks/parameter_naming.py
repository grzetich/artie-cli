"""Parameter Naming check.

Scores documentation based on naming convention consistency across parameters
and schema properties. Mixed conventions force agents to guess at the right
casing for new endpoints. The score rewards consistency, not any particular
convention: a fully camelCase API scores as well as a fully snake_case one.
"""

import re
from collections import Counter
from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import Endpoint, ParsedDocs

# Compiled patterns. snake_case must contain at least one underscore to
# distinguish from lowercase. PascalCase must start with uppercase.
PATTERNS: dict[str, re.Pattern[str]] = {
    "snake_case": re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$"),
    "camelCase": re.compile(r"^[a-z][a-z0-9]*([A-Z][a-z0-9]*)+$"),
    "PascalCase": re.compile(r"^[A-Z][a-z0-9]*([A-Z][a-z0-9]*)*$"),
    "kebab-case": re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$"),
    "lowercase": re.compile(r"^[a-z][a-z0-9]*$"),
}


class ParameterNamingCheck(BaseCheck):
    name = "Parameter Naming"
    description = (
        "Consistent naming convention across parameters and schema properties."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Parameter Naming requires a parsed OpenAPI document."
            )

        names: list[str] = []

        for endpoint in parsed.endpoints:
            for param in endpoint.parameters:
                if isinstance(param, dict) and isinstance(param.get("name"), str):
                    names.append(param["name"])
            names.extend(_names_from_endpoint_schemas(endpoint))

        schemas = parsed.components.get("schemas") if isinstance(parsed.components, dict) else None
        if isinstance(schemas, dict):
            for schema in schemas.values():
                names.extend(_collect_property_names(schema))

        if not names:
            return self.not_evaluable("No parameters or schema properties found.")

        convention_counts: Counter[str] = Counter()
        unmatched = 0
        ambiguous = 0
        for name in names:
            matched = _classify(name)
            if matched is None:
                unmatched += 1
            elif matched == "lowercase":
                # Single-word lowercase names are compatible with snake_case,
                # camelCase, and kebab-case. They are not evidence for any
                # particular convention, so we exclude them from scoring.
                ambiguous += 1
            else:
                convention_counts[matched] += 1

        if not convention_counts and unmatched == 0:
            return self.not_evaluable(
                "All names are single-word lowercase, so no convention can "
                "be inferred or scored."
            )

        if not convention_counts:
            return self.not_evaluable(
                "No names matched a recognized convention; nothing to score."
            )

        primary, primary_count = convention_counts.most_common(1)[0]
        # Total for scoring excludes ambiguous names; they shouldn't penalize.
        total = sum(convention_counts.values()) + unmatched
        consistency = primary_count / total

        score = round(consistency * self.max_score)
        severity = self.severity_for(score)

        breakdown = ", ".join(
            f"{convention}: {count}" for convention, count in convention_counts.most_common()
        )
        findings = [
            f"Primary convention: {primary} "
            f"({primary_count} of {total} convention-bearing names)",
            f"Breakdown: {breakdown}",
        ]
        if ambiguous:
            findings.append(
                f"{ambiguous} single-word lowercase names "
                f"(compatible with snake_case, camelCase, and kebab-case; "
                f"not scored)"
            )
        if unmatched:
            findings.append(
                f"{unmatched} names did not match any standard convention"
            )

        non_primary = [
            convention
            for convention in convention_counts
            if convention != primary
        ]
        recommendations: list[str] = []
        if non_primary:
            recommendations.append(
                f"Standardize on {primary}, which is the majority convention. "
                f"Mixed conventions ({', '.join(non_primary)}) force agents to "
                f"guess at naming on new endpoints."
            )
        if unmatched:
            recommendations.append(
                "Rename parameters and properties that don't match a standard "
                "convention. Non-standard names (mixed casing, leading numbers, "
                "punctuation) are unpredictable for agents."
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
                "primary_convention": primary,
                "consistency": round(consistency, 3),
                "total_convention_bearing_names": total,
                "convention_counts": dict(convention_counts),
                "unmatched_names": unmatched,
                "ambiguous_single_word_names": ambiguous,
            },
        )


def _classify(name: str) -> str | None:
    """Return the convention this name matches, or None if it matches none."""
    # Order matters: snake_case before lowercase, PascalCase before camelCase
    # would catch single-word PascalCase as lowercase otherwise.
    for convention in ("snake_case", "kebab-case", "camelCase", "PascalCase", "lowercase"):
        if PATTERNS[convention].match(name):
            return convention
    return None


def _names_from_endpoint_schemas(endpoint: Endpoint) -> list[str]:
    """Collect property names from inline schemas inside an operation.

    Walks parameter schemas, request body content schemas, and response body
    content schemas. Component-referenced schemas are walked separately via
    components.schemas, so $refs encountered here are not followed.
    """
    names: list[str] = []

    for param in endpoint.parameters:
        if isinstance(param, dict):
            schema = param.get("schema")
            if isinstance(schema, dict):
                names.extend(_collect_property_names(schema))

    request_body = endpoint.operation.get("requestBody")
    if isinstance(request_body, dict):
        names.extend(_names_from_content(request_body.get("content")))

    responses = endpoint.operation.get("responses") or {}
    if isinstance(responses, dict):
        for response in responses.values():
            if isinstance(response, dict):
                names.extend(_names_from_content(response.get("content")))

    return names


def _names_from_content(content: Any) -> list[str]:
    """Pull names from every media type schema in a content map."""
    if not isinstance(content, dict):
        return []
    names: list[str] = []
    for media_type in content.values():
        if isinstance(media_type, dict):
            schema = media_type.get("schema")
            if isinstance(schema, dict):
                names.extend(_collect_property_names(schema))
    return names


def _collect_property_names(schema: Any, depth: int = 0) -> list[str]:
    """Recursively walk a schema collecting all property names.

    Bounded depth so circular references can't blow the stack. We stop at
    `$ref` because we'd need to resolve refs to recurse, and the names at
    the referenced schema will be collected when we visit it directly.
    """
    if depth > 20 or not isinstance(schema, dict):
        return []
    names: list[str] = []

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop_name, prop_schema in properties.items():
            if isinstance(prop_name, str):
                names.append(prop_name)
            names.extend(_collect_property_names(prop_schema, depth + 1))

    items = schema.get("items")
    if isinstance(items, dict):
        names.extend(_collect_property_names(items, depth + 1))

    for combinator in ("allOf", "oneOf", "anyOf"):
        combined = schema.get(combinator)
        if isinstance(combined, list):
            for sub in combined:
                names.extend(_collect_property_names(sub, depth + 1))

    return names
