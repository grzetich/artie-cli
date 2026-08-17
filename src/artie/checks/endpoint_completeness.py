"""Endpoint Completeness check.

Scores documentation based on how completely each endpoint is described.
Three signals contribute equally:

1. Endpoints with a description or summary (agents need to know what an
   endpoint does, not just its shape).
2. Endpoints with an operationId (the canonical name agents use for tool
   calling and code generation).
3. Path parameters with descriptions (agents must know what {bookId}
   actually identifies before constructing requests).

The document's `servers` block is inspected and reported alongside these, but
does not contribute to the score. A missing or schemeless base URL is a
document-level defect rather than a per-endpoint one, and averaging it into
the per-endpoint ratios would make one number mean two things.
"""

from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.openapi import path_parameters
from artie.parsers.types import Endpoint, ParsedDocs


class EndpointCompletenessCheck(BaseCheck):
    name = "Endpoint Completeness"
    description = (
        "Endpoints with descriptions, operationIds, and documented "
        "path parameters."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Endpoint Completeness requires a parsed OpenAPI document."
            )

        endpoints = parsed.endpoints
        if not endpoints:
            return self.not_evaluable("No endpoints found in paths section.")

        described = [e for e in endpoints if _has_description(e)]
        with_op_id = [e for e in endpoints if e.operation_id]
        path_param_total, path_param_described = _count_path_params(endpoints)

        # Three subscores out of 1.0, averaged, scaled to max_score.
        desc_ratio = len(described) / len(endpoints)
        op_id_ratio = len(with_op_id) / len(endpoints)
        if path_param_total == 0:
            # No path params is not a failure mode; collapse to two-component avg.
            subscores = [desc_ratio, op_id_ratio]
        else:
            path_ratio = path_param_described / path_param_total
            subscores = [desc_ratio, op_id_ratio, path_ratio]

        composite = sum(subscores) / len(subscores)
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        findings = [
            f"{len(described)} of {len(endpoints)} endpoints have a description or summary",
            f"{len(with_op_id)} of {len(endpoints)} endpoints have an operationId",
        ]
        if path_param_total > 0:
            findings.append(
                f"{path_param_described} of {path_param_total} path parameters "
                f"have descriptions"
            )

        server_findings, server_recommendations = _server_findings(parsed.raw)
        findings.extend(server_findings)

        recommendations: list[str] = list(server_recommendations)
        if len(described) < len(endpoints):
            missing = [e.display for e in endpoints if not _has_description(e)][:5]
            recommendations.append(
                "Add a summary or description to every operation. Examples "
                f"missing one: {', '.join(missing)}"
                + ("..." if len(missing) == 5 else "")
            )
        if len(with_op_id) < len(endpoints):
            missing = [e.display for e in endpoints if not e.operation_id][:5]
            recommendations.append(
                "Add an operationId to every operation. operationIds become "
                "function names in generated SDKs and tool definitions. Missing "
                f"on: {', '.join(missing)}"
                + ("..." if len(missing) == 5 else "")
            )
        if path_param_total > 0 and path_param_described < path_param_total:
            recommendations.append(
                "Document every path parameter with a description. Without "
                "descriptions, agents guess at what an ID identifies."
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
                "endpoints_with_descriptions": len(described),
                "endpoints_with_operation_ids": len(with_op_id),
                "path_parameters_total": path_param_total,
                "path_parameters_described": path_param_described,
                "servers": len((parsed.raw or {}).get("servers") or []),
            },
        )


def _server_findings(raw: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Inspect the document's `servers` block. Returns (findings, recommendations).

    Reported rather than scored: a broken base URL is a different failure from
    an under-described operation, and folding it into the per-endpoint average
    would make the score mean two things at once.

    OpenAPI allows a relative server URL (`/v1`), so "no scheme" is only a
    problem when the value looks like a host that lost its scheme
    (`api.example.com/v1`) — that string is not resolvable by any client.
    """
    findings: list[str] = []
    recommendations: list[str] = []

    servers = (raw or {}).get("servers")
    if not isinstance(servers, list) or not servers:
        findings.append(
            "✗ No servers block; the document never states a base URL"
        )
        recommendations.append(
            "Add a `servers` entry with the absolute base URL. Without one an "
            "agent has no origin to send requests to and must guess it from "
            "prose or from a hostname it saw in an example."
        )
        return findings, recommendations

    schemeless: list[str] = []
    templated: list[str] = []
    valid = 0

    for entry in servers:
        url = entry.get("url") if isinstance(entry, dict) else None
        if not isinstance(url, str) or not url.strip():
            schemeless.append(repr(url))
            continue
        url = url.strip()
        if "://" in url:
            valid += 1
            continue
        if url.startswith("{"):
            # A fully templated origin like {region}.example.com. Legal, but
            # unresolvable until the variable is substituted.
            templated.append(url)
            continue
        if url.startswith("/"):
            # Relative to the document's own origin: legal and resolvable.
            valid += 1
            continue
        schemeless.append(url)

    findings.append(
        f"{valid} of {len(servers)} server URLs are absolute or resolvable"
    )
    if schemeless:
        findings.append(
            f"✗ Server URL missing a scheme: {', '.join(schemeless[:3])}"
        )
        recommendations.append(
            "Prefix every server URL with its scheme (https://). A bare host "
            "like `api.example.com/v1` is not a URL any HTTP client will "
            "accept, so generated code fails on its first call."
        )
    if templated:
        findings.append(
            f"⚠ Server URL is fully templated: {', '.join(templated[:3])}"
        )
        recommendations.append(
            "Give templated server variables a `default` so the URL resolves "
            "without out-of-band knowledge."
        )

    return findings, recommendations


def _has_description(endpoint: Endpoint) -> bool:
    """Either description or summary counts; agents read both."""
    return bool((endpoint.description or "").strip() or (endpoint.summary or "").strip())


def _count_path_params(endpoints: list[Endpoint]) -> tuple[int, int]:
    """Count path parameters across all endpoints, and how many are described.

    A path parameter is described when an operation declares it under
    `parameters` with `in: path` and a non-empty description. We dedupe per
    endpoint so the same {id} appearing in two operations counts twice
    (it can have different documentation on each).
    """
    total = 0
    described = 0
    for endpoint in endpoints:
        names_in_path = path_parameters(endpoint.path)
        if not names_in_path:
            continue
        # Build a lookup of declared path parameters on this operation.
        declared = {
            p.get("name"): p
            for p in endpoint.parameters
            if isinstance(p, dict) and p.get("in") == "path"
        }
        for name in names_in_path:
            total += 1
            param = declared.get(name)
            if param and (param.get("description") or "").strip():
                described += 1
    return total, described
