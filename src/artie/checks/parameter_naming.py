"""Parameter Naming check.

Scores naming convention consistency. Mixed conventions force agents to guess
at the right casing for new endpoints. The score rewards consistency, not any
particular convention: a fully camelCase API scores as well as a fully
snake_case one.

Consistency is measured **per location**, not across the whole document.
Pooling every name together penalized APIs that follow HTTP convention
correctly: `Content-Type` in a header alongside `fileName` in a body is not a
mixed convention, it is two conventions each used where it belongs. Scoring
the pool marked that as inconsistent and cost well-formed APIs several points.

So:

- Header parameters are judged against HTTP header convention. HTTP headers
  are case-insensitive and hyphen-delimited, so `Content-Type`, `x-api-key`,
  and `Authorization` are all correct. Only a header that is not
  hyphen-delimited at all (`content_type`) is non-conventional.
- Path, query, and cookie parameters, and body/schema properties, are each
  scored on their own internal consistency.
- The overall score is the average of the per-location scores, weighted by
  how many names each location contributes.
"""

from __future__ import annotations

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

# An HTTP header name: one or more alphanumeric segments joined by hyphens.
# Deliberately case-blind, because the HTTP spec is. This admits
# `Content-Type`, `x-api-key`, `X-API-Key`, and `Authorization` alike.
HEADER_PATTERN = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")

# Locations scored on internal consistency. Headers are handled separately.
_CONSISTENCY_LOCATIONS = ("path", "query", "cookie", "body")

_LOCATION_LABELS = {
    "path": "path parameters",
    "query": "query parameters",
    "cookie": "cookie parameters",
    "header": "header parameters",
    "body": "body and schema properties",
}


class ParameterNamingCheck(BaseCheck):
    name = "Parameter Naming"
    description = (
        "Consistent naming convention within each parameter location and "
        "across schema properties."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Parameter Naming requires a parsed OpenAPI document."
            )

        by_location = _collect_names(parsed)
        if not any(by_location.values()):
            return self.not_evaluable("No parameters or schema properties found.")

        findings: list[str] = []
        recommendations: list[str] = []
        location_scores: dict[str, float] = {}
        location_weights: dict[str, int] = {}
        location_meta: dict[str, dict[str, Any]] = {}

        # Headers first: conventional-or-not, no majority vote.
        headers = by_location.get("header", [])
        if headers:
            conforming = [name for name in headers if HEADER_PATTERN.match(name)]
            ratio = len(conforming) / len(headers)
            location_scores["header"] = ratio
            location_weights["header"] = len(headers)
            offenders = [name for name in headers if not HEADER_PATTERN.match(name)]
            location_meta["header"] = {
                "names": len(headers),
                "conforming": len(conforming),
                "non_conforming": offenders[:10],
            }
            findings.append(
                f"Header parameters: {len(conforming)} of {len(headers)} follow "
                f"HTTP header convention (hyphen-delimited, case-insensitive)"
            )
            if offenders:
                recommendations.append(
                    "Rename headers that are not hyphen-delimited "
                    f"({', '.join(offenders[:5])}). HTTP headers are "
                    "case-insensitive and hyphenated by convention; underscores "
                    "are dropped by some proxies and servers."
                )

        for location in _CONSISTENCY_LOCATIONS:
            names = by_location.get(location, [])
            if not names:
                continue
            result = _score_consistency(names)
            if result is None:
                # Every name here is ambiguous (single-word lowercase), so no
                # convention can be inferred. Excluded rather than scored as 0.
                findings.append(
                    f"{_LOCATION_LABELS[location].capitalize()}: "
                    f"{len(names)} names, all single-word lowercase; "
                    f"no convention to infer"
                )
                continue
            location_scores[location] = result.consistency
            location_weights[location] = result.scored_names
            location_meta[location] = {
                "primary_convention": result.primary,
                "consistency": round(result.consistency, 3),
                "convention_counts": dict(result.counts),
                "unmatched_names": result.unmatched,
                "ambiguous_single_word_names": result.ambiguous,
            }
            breakdown = ", ".join(
                f"{convention}: {count}"
                for convention, count in result.counts.most_common()
            )
            findings.append(
                f"{_LOCATION_LABELS[location].capitalize()}: "
                f"{result.primary} ({result.primary_count} of "
                f"{result.scored_names}) — {breakdown}"
            )
            if len(result.counts) > 1:
                others = [c for c in result.counts if c != result.primary]
                recommendations.append(
                    f"Standardize {_LOCATION_LABELS[location]} on "
                    f"{result.primary}. Mixing {', '.join(others)} within one "
                    f"location forces agents to guess casing on new endpoints."
                )
            if result.unmatched:
                recommendations.append(
                    f"Rename the {result.unmatched} "
                    f"{_LOCATION_LABELS[location]} that match no standard "
                    f"convention. Non-standard names (mixed casing, leading "
                    f"numbers, punctuation) are unpredictable for agents."
                )

        if not location_scores:
            return self.not_evaluable(
                "No names matched a recognized convention; nothing to score."
            )

        total_weight = sum(location_weights.values())
        consistency = (
            sum(
                location_scores[loc] * location_weights[loc]
                for loc in location_scores
            )
            / total_weight
        )
        score = round(consistency * self.max_score)
        severity = self.severity_for(score)

        if len(location_scores) > 1:
            findings.insert(
                0,
                "Scored per location; conventions that differ between headers "
                "and body are not penalized as inconsistency.",
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
                "consistency": round(consistency, 3),
                "locations_scored": sorted(location_scores),
                "per_location": location_meta,
                "total_names_scored": total_weight,
            },
        )


class _ConsistencyResult:
    """Per-location consistency, kept as a small object for readability."""

    def __init__(
        self,
        primary: str,
        primary_count: int,
        scored_names: int,
        counts: Counter[str],
        unmatched: int,
        ambiguous: int,
    ) -> None:
        self.primary = primary
        self.primary_count = primary_count
        self.scored_names = scored_names
        self.counts = counts
        self.unmatched = unmatched
        self.ambiguous = ambiguous
        self.consistency = primary_count / scored_names if scored_names else 0.0


def _score_consistency(names: list[str]) -> _ConsistencyResult | None:
    """Majority-convention consistency for one location.

    Returns None when no convention can be inferred, which happens when every
    name is a single lowercase word (compatible with snake_case, camelCase,
    and kebab-case alike, so evidence for none of them).
    """
    counts: Counter[str] = Counter()
    unmatched = 0
    ambiguous = 0
    for name in names:
        matched = _classify(name)
        if matched is None:
            unmatched += 1
        elif matched == "lowercase":
            ambiguous += 1
        else:
            counts[matched] += 1

    if not counts:
        if unmatched == 0:
            return None
        # Names exist but none is conventional: real inconsistency, score 0.
        return _ConsistencyResult("none", 0, unmatched, counts, unmatched, ambiguous)

    primary, primary_count = counts.most_common(1)[0]
    scored_names = sum(counts.values()) + unmatched
    return _ConsistencyResult(
        primary, primary_count, scored_names, counts, unmatched, ambiguous
    )


def _classify(name: str) -> str | None:
    """Return the convention this name matches, or None if it matches none."""
    # Order matters: snake_case before lowercase, PascalCase before camelCase
    # would catch single-word PascalCase as lowercase otherwise.
    for convention in (
        "snake_case",
        "kebab-case",
        "camelCase",
        "PascalCase",
        "lowercase",
    ):
        if PATTERNS[convention].match(name):
            return convention
    return None


def _collect_names(parsed: ParsedDocs) -> dict[str, list[str]]:
    """Gather every name in the document, bucketed by where it appears."""
    by_location: dict[str, list[str]] = {
        "path": [],
        "query": [],
        "header": [],
        "cookie": [],
        "body": [],
    }

    for endpoint in parsed.endpoints:
        for param in endpoint.parameters:
            if not isinstance(param, dict):
                continue
            location = param.get("in")
            bucket = location if location in by_location else "query"
            name = param.get("name")
            if isinstance(name, str):
                by_location[bucket].append(name)
            # Properties nested inside a parameter schema are part of that
            # parameter's payload, so they inherit its location.
            schema = param.get("schema")
            if isinstance(schema, dict):
                by_location[bucket].extend(_collect_property_names(schema))

        by_location["body"].extend(_body_names(endpoint))

    schemas = (
        parsed.components.get("schemas")
        if isinstance(parsed.components, dict)
        else None
    )
    if isinstance(schemas, dict):
        for schema in schemas.values():
            by_location["body"].extend(_collect_property_names(schema))

    return by_location


def _body_names(endpoint: Endpoint) -> list[str]:
    """Property names from request and response bodies on one operation."""
    names: list[str] = []

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
