"""Render analysis reports as JSON for CI and tooling integration."""

import json
from datetime import datetime, timezone
from typing import Any

from artie.checks.base import CheckResult


def to_dict(
    source: str, format_type: str, results: list[CheckResult]
) -> dict[str, Any]:
    """Build a serializable dict from an analysis run."""
    return {
        "source": source,
        "format": format_type,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "tool": "artie-cli",
        "checks": [
            {
                "name": r.name,
                "description": r.description,
                "score": r.score,
                "max_score": r.max_score,
                "severity": r.severity.value,
                "evaluable": r.is_evaluable,
                "findings": r.findings,
                "recommendations": r.recommendations,
                "metadata": r.metadata,
            }
            for r in results
        ],
    }


def render(source: str, format_type: str, results: list[CheckResult]) -> str:
    return json.dumps(to_dict(source, format_type, results), indent=2)
