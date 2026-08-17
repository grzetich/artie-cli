"""Schema Complexity check.

Scores documentation based on how deeply nested the API's schemas are.
Deep nesting hurts AI consumption two ways:

1. Token cost: deeply nested schemas cost more to include in context.
2. Reasoning cost: models do worse at constructing correctly-nested payloads
   as depth increases.

The check walks every schema it can find, calculates its maximum nesting
depth, and scores against thresholds. components.schemas is preferred; when
a document has none — common on docs platforms that render one page per
endpoint and inline the whole shape — it falls back to the request, response,
and parameter schemas declared inline on operations, rather than reporting
not-evaluable on a document whose schemas are sitting right there.

Refs are followed once (we descend through ref targets in the same
components.schemas map) but cycles are prevented by tracking the set of
already-visited ref names.
"""

from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import ParsedDocs


# Depth thresholds chosen against the TNJ corpus: most well-shaped APIs
# have max depths in the 3-5 range; depths beyond 8 correlate with
# significantly worse generated code.
DEPTH_BUCKETS = [
    (3, 10),   # depth <= 3 -> 10/10
    (5, 8),    # depth <= 5 -> 8/10
    (7, 5),    # depth <= 7 -> 5/10
    (9, 3),    # depth <= 9 -> 3/10
    (999, 1),  # deeper than 9 -> 1/10
]


class SchemaComplexityCheck(BaseCheck):
    name = "Schema Complexity"
    description = (
        "Maximum and average nesting depth across component schemas, or "
        "inline operation schemas when no components section exists."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Schema Complexity requires a parsed OpenAPI document."
            )

        components = parsed.components if isinstance(parsed.components, dict) else {}
        schemas = components.get("schemas")
        if isinstance(schemas, dict) and schemas:
            source = "components.schemas"
            targets = schemas
        else:
            # Platforms that render one page per endpoint (ReadMe, and any
            # docs site that inlines its spec per-page) frequently ship no
            # components section at all. Refusing to score those was reporting
            # N/A on documents whose schemas were sitting right there inline.
            targets = _inline_schemas(parsed)
            source = "inline request and response schemas"
            if not targets:
                return self.not_evaluable(
                    "No component schemas and no inline request or response "
                    "schemas found."
                )

        depths: dict[str, int] = {}
        for name, schema in targets.items():
            if isinstance(schema, dict):
                depths[name] = _max_depth(schema, schemas if isinstance(schemas, dict) else {}, visited=set())

        if not depths:
            return self.not_evaluable(f"No schemas in {source} could be evaluated.")

        max_depth = max(depths.values())
        avg_depth = sum(depths.values()) / len(depths)
        score = _score_for_depth(max_depth)
        severity = self.severity_for(score)

        deepest = sorted(depths.items(), key=lambda kv: kv[1], reverse=True)
        deepest_names = [
            f"{name} (depth {depth})"
            for name, depth in deepest
            if depth == max_depth
        ][:5]

        findings = [
            f"{len(depths)} schemas analyzed from {source}",
            f"Maximum nesting depth: {max_depth} ({', '.join(deepest_names)})",
            f"Average nesting depth: {avg_depth:.1f}",
        ]

        recommendations: list[str] = []
        if max_depth > 5:
            recommendations.append(
                "Flatten the deepest schemas. Extract nested objects into "
                "named components and reference them, so each schema is "
                "smaller and more focused. Agents construct correct payloads "
                "more reliably against shallow, named schemas than deep "
                "anonymous trees."
            )
        if max_depth > 8:
            recommendations.append(
                "Depths above 8 correlate with significantly worse generated "
                "code in the TNJ corpus. Consider whether some of this "
                "structure is incidental and could be simplified at the API "
                "boundary, not just in the docs."
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
                "schemas_analyzed": len(depths),
                "schema_source": source,
                "max_depth": max_depth,
                "avg_depth": round(avg_depth, 2),
                "depth_per_schema": depths,
            },
        )


def _inline_schemas(parsed: ParsedDocs) -> dict[str, Any]:
    """Collect schemas declared inline on operations, keyed by where they live.

    Used when the document has no components.schemas — common on docs
    platforms that render one page per endpoint and inline the whole shape.
    Keys read like `POST /uploads requestBody` so the deepest-schema finding
    still points somewhere actionable.
    """
    found: dict[str, Any] = {}

    for endpoint in parsed.endpoints:
        request_body = endpoint.operation.get("requestBody")
        if isinstance(request_body, dict):
            for media, schema in _content_schemas(request_body.get("content")):
                found[f"{endpoint.display} requestBody ({media})"] = schema

        responses = endpoint.operation.get("responses") or {}
        if isinstance(responses, dict):
            for status, response in responses.items():
                if not isinstance(response, dict):
                    continue
                for media, schema in _content_schemas(response.get("content")):
                    found[f"{endpoint.display} {status} response ({media})"] = schema

        for param in endpoint.parameters:
            if not isinstance(param, dict):
                continue
            schema = param.get("schema")
            name = param.get("name")
            # Only object/array parameter schemas are worth measuring; a scalar
            # `type: string` parameter has depth 0 and would drag the average
            # down without describing any real nesting.
            if isinstance(schema, dict) and isinstance(name, str):
                if schema.get("properties") or schema.get("items"):
                    found[f"{endpoint.display} parameter {name}"] = schema

    return found


def _content_schemas(content: Any) -> list[tuple[str, Any]]:
    """Every (media type, schema) pair in a content map."""
    if not isinstance(content, dict):
        return []
    pairs: list[tuple[str, Any]] = []
    for media_type, body in content.items():
        if isinstance(body, dict) and isinstance(body.get("schema"), dict):
            pairs.append((str(media_type), body["schema"]))
    return pairs


def _score_for_depth(depth: int) -> int:
    for threshold, score in DEPTH_BUCKETS:
        if depth <= threshold:
            return score
    return 1


def _max_depth(
    schema: Any,
    all_schemas: dict[str, Any],
    visited: set[str],
    current_depth: int = 0,
) -> int:
    """Compute the maximum nesting depth of this schema.

    Visited tracks ref names already followed on the current path so cycles
    don't recurse forever. Depth increments at each `properties` level and
    when descending into `items`.
    """
    if not isinstance(schema, dict) or current_depth > 100:
        return current_depth

    ref = schema.get("$ref")
    if isinstance(ref, str):
        ref_name = _ref_name(ref)
        if ref_name and ref_name not in visited and ref_name in all_schemas:
            target = all_schemas[ref_name]
            return _max_depth(
                target,
                all_schemas,
                visited | {ref_name},
                current_depth,
            )
        return current_depth

    deepest = current_depth

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop_schema in properties.values():
            sub_depth = _max_depth(
                prop_schema, all_schemas, visited, current_depth + 1
            )
            deepest = max(deepest, sub_depth)

    items = schema.get("items")
    if isinstance(items, dict):
        sub_depth = _max_depth(items, all_schemas, visited, current_depth + 1)
        deepest = max(deepest, sub_depth)

    for combinator in ("allOf", "oneOf", "anyOf"):
        combined = schema.get(combinator)
        if isinstance(combined, list):
            for sub in combined:
                sub_depth = _max_depth(sub, all_schemas, visited, current_depth)
                deepest = max(deepest, sub_depth)

    return deepest


def _ref_name(ref: str) -> str | None:
    """Extract the schema name from a `#/components/schemas/Foo` ref."""
    prefix = "#/components/schemas/"
    if ref.startswith(prefix):
        return ref[len(prefix):]
    return None
