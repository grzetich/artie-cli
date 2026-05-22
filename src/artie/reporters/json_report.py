"""Render analysis reports as JSON for CI and tooling integration."""

import json
from datetime import datetime, timezone
from typing import Any

from artie import SCORING_VERSION
from artie.baseline import Baseline
from artie.checks.base import CheckResult


def to_dict(
    source: str,
    format_type: str,
    results: list[CheckResult],
    baseline: Baseline | None = None,
) -> dict[str, Any]:
    """Build a serializable dict from an analysis run.

    `scoring_version` identifies the rubric the scores were produced under;
    see docs/scoring.md. When `baseline` is provided, each check also carries
    its prior score and the signed delta.
    """
    report: dict[str, Any] = {
        "source": source,
        "format": format_type,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "tool": "artie-cli",
        "scoring_version": SCORING_VERSION,
        "checks": [_check_to_dict(r, baseline) for r in results],
    }
    if baseline is not None:
        report["baseline"] = {
            "source": baseline.source,
            "scoring_version": baseline.scoring_version,
            "path": str(baseline.path) if baseline.path else None,
        }
    return report


def _check_to_dict(r: CheckResult, baseline: Baseline | None) -> dict[str, Any]:
    check: dict[str, Any] = {
        "name": r.name,
        "description": r.description,
        "score": r.score,
        "max_score": r.max_score,
        "severity": r.severity.value,
        "evaluable": r.is_evaluable,
        "informational": r.informational,
        "findings": r.findings,
        "recommendations": r.recommendations,
        "metadata": r.metadata,
    }
    if baseline is not None:
        check["baseline_score"] = baseline.score_for(r.name)
        check["delta"] = baseline.delta_for(r.name, r.score)
    return check


def render(
    source: str,
    format_type: str,
    results: list[CheckResult],
    baseline: Baseline | None = None,
) -> str:
    return json.dumps(to_dict(source, format_type, results, baseline), indent=2)
