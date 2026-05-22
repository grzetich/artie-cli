"""Auth Clarity check.

Scores documentation based on how clearly authentication is defined and
applied. Agents need to know what credentials to send, where to send them,
and on which operations.

Three subscores:

1. Schemes defined: at least one security scheme exists in
   components.securitySchemes.
2. Schemes described: every scheme has a non-trivial description (or, for
   schemes where the type is self-documenting like `http bearer`, the type
   itself counts).
3. Application coverage: either a top-level `security` requirement is set,
   or every operation declares one. Operations that explicitly opt out with
   `security: []` count as documented (they're public on purpose).
"""

from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import Endpoint, ParsedDocs


SELF_DOCUMENTING_TYPES = {"http", "apiKey", "openIdConnect"}


class AuthClarityCheck(BaseCheck):
    name = "Auth Clarity"
    description = "Security schemes defined, described, and applied to operations."

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable(
                "Auth Clarity requires a parsed OpenAPI document."
            )

        schemes = _security_schemes(parsed.components)
        endpoints = parsed.endpoints

        if not schemes and not _global_security(parsed.raw) and not _any_operation_has_security(endpoints):
            # No security mentioned anywhere. This is either a fully public
            # API (legitimate) or undocumented auth (not legitimate). We can't
            # tell from the spec alone, so flag it but do not score zero.
            return CheckResult(
                name=self.name,
                description=self.description,
                score=0,
                max_score=self.max_score,
                severity=self.severity_for(0),
                findings=[
                    "No security schemes defined and no operations declare security",
                    "API appears to be fully unauthenticated, or auth is undocumented",
                ],
                recommendations=[
                    "If this API requires authentication, declare a scheme under "
                    "components.securitySchemes and reference it from operations "
                    "(or globally). If it is genuinely public, add a top-level "
                    "comment to make that explicit."
                ],
                metadata={"schemes": 0, "global_security": False},
            )

        scheme_count = len(schemes)
        described_schemes = sum(1 for s in schemes.values() if _is_described(s))
        global_security = _global_security(parsed.raw)

        operation_coverage = _operation_coverage(endpoints, global_security)

        scheme_defined_ratio = 1.0 if scheme_count > 0 else 0.0
        described_ratio = (
            described_schemes / scheme_count if scheme_count > 0 else 0.0
        )
        application_ratio = operation_coverage

        composite = (scheme_defined_ratio + described_ratio + application_ratio) / 3
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        scheme_names = ", ".join(schemes.keys()) if schemes else "none"
        findings = [
            f"{scheme_count} security scheme{'s' if scheme_count != 1 else ''} "
            f"defined: {scheme_names}",
            f"{described_schemes} of {scheme_count} schemes have a description "
            f"or self-documenting type"
            if scheme_count
            else "No security schemes defined",
            "Top-level security requirement present" if global_security
            else "No top-level security requirement",
            f"{int(application_ratio * 100)}% of operations have an explicit "
            "or inherited security requirement",
        ]

        recommendations: list[str] = []
        undescribed = [name for name, s in schemes.items() if not _is_described(s)]
        if undescribed:
            recommendations.append(
                "Add a description to each security scheme explaining how to "
                "obtain credentials and what they authorize. Missing on: "
                + ", ".join(undescribed)
            )
        if scheme_count and application_ratio < 1.0:
            recommendations.append(
                "Set a top-level security requirement so every operation "
                "inherits it by default, or declare security on every operation. "
                "Operations that are genuinely public should opt out explicitly "
                "with security: []."
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
                "schemes": scheme_count,
                "schemes_described": described_schemes,
                "global_security": global_security,
                "operation_coverage": application_ratio,
            },
        )


def _security_schemes(components: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(components, dict):
        return {}
    schemes = components.get("securitySchemes")
    if not isinstance(schemes, dict):
        return {}
    return {k: v for k, v in schemes.items() if isinstance(v, dict)}


def _global_security(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict):
        return False
    security = raw.get("security")
    return isinstance(security, list) and len(security) > 0


def _any_operation_has_security(endpoints: list[Endpoint]) -> bool:
    return any("security" in e.operation for e in endpoints)


def _operation_coverage(endpoints: list[Endpoint], global_security: bool) -> float:
    """Fraction of operations whose security posture is documented.

    An operation is covered if it explicitly sets `security` (including the
    empty list to opt out), or if a top-level security requirement applies.
    """
    if not endpoints:
        return 0.0
    covered = 0
    for endpoint in endpoints:
        if "security" in endpoint.operation:
            covered += 1
        elif global_security:
            covered += 1
    return covered / len(endpoints)


def _is_described(scheme: dict[str, Any]) -> bool:
    """A scheme is described if it has a non-trivial description, or if its
    type is self-documenting (http bearer, apiKey, openIdConnect)."""
    description = (scheme.get("description") or "").strip()
    if len(description) >= 10:
        return True
    scheme_type = scheme.get("type")
    return scheme_type in SELF_DOCUMENTING_TYPES
