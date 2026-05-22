"""Base class for all artie checks."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Severity levels for check results."""

    EXCELLENT = "excellent"
    GOOD = "good"
    NEEDS_WORK = "needs_work"
    POOR = "poor"
    NOT_EVALUABLE = "not_evaluable"


@dataclass
class CheckResult:
    """Result of running a single check against documentation."""

    name: str
    description: str
    score: int | None
    max_score: int
    severity: Severity
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # An informational check ran and produced findings, but deliberately
    # assigns no score. Sample Generation is the only one: it presents
    # generated code as a deliverable, not a 0-10 grade.
    informational: bool = False

    @property
    def is_evaluable(self) -> bool:
        """True when this check produced a numeric score worth gating on.

        Excludes both not-evaluable results (the check couldn't run) and
        informational results (the check ran but assigns no score).
        """
        return self.severity != Severity.NOT_EVALUABLE and not self.informational

    @property
    def score_display(self) -> str:
        if self.informational:
            return "—"
        if self.severity == Severity.NOT_EVALUABLE:
            return "N/A"
        return f"{self.score}/{self.max_score}"


class BaseCheck:
    """Base class for all documentation checks."""

    name: str = "unnamed check"
    description: str = ""
    max_score: int = 10

    def run(self, content: str, format_type: str, parsed: Any = None) -> CheckResult:
        """Run this check against documentation content.

        Args:
            content: Raw documentation text.
            format_type: Detected format (e.g. "openapi-yaml", "markdown").
            parsed: Optional pre-parsed representation of the content.

        Returns:
            CheckResult with score, severity, findings, and recommendations.
        """
        raise NotImplementedError

    def not_evaluable(self, reason: str) -> CheckResult:
        """Return a not-evaluable result when this check can't be assessed."""
        return CheckResult(
            name=self.name,
            description=self.description,
            score=None,
            max_score=self.max_score,
            severity=Severity.NOT_EVALUABLE,
            findings=[reason],
        )

    def severity_for(self, score: int) -> Severity:
        """Map a numeric score to a severity level."""
        ratio = score / self.max_score
        if ratio >= 0.9:
            return Severity.EXCELLENT
        if ratio >= 0.7:
            return Severity.GOOD
        if ratio >= 0.4:
            return Severity.NEEDS_WORK
        return Severity.POOR
