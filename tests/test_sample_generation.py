"""Tests for Sample Generation result shape (no network calls).

Covers the demotion: the check is opt-in, unscored, informational, and emits
a contamination warning in differential mode.
"""

from artie.checks.base import CheckResult, Severity
from artie.checks.generation_quality import SampleGenerationCheck, _build_result
from artie.generator import GenerationResult


def _gen_result() -> GenerationResult:
    return GenerationResult(
        text="```python\nimport requests\n```",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        stop_reason="end_turn",
    )


def _eval(criteria_met: int, structural_score: int = 0) -> dict:
    return {
        "criteria": {"parses_as_python": True},
        "criteria_met": criteria_met,
        "commentary": ["✓ Parses as valid Python"],
        "recommendations": [],
        "line_count": 12,
        "gap_count": 0,
        "structural_score": structural_score,
    }


class TestDisabled:
    def test_disabled_by_default(self):
        # enabled defaults to False -> opt-in.
        check = SampleGenerationCheck()
        result = check.run("x" * 200, "openapi-yaml")
        assert not result.is_evaluable
        assert not result.informational
        assert result.score is None
        assert "with-generation" in result.findings[0]


class TestInformationalCheckResult:
    def test_informational_score_display(self):
        result = CheckResult(
            name="Sample Generation",
            description="",
            score=None,
            max_score=10,
            severity=Severity.NOT_EVALUABLE,
            informational=True,
        )
        assert result.score_display == "—"
        assert not result.is_evaluable

    def test_not_evaluable_shows_na(self):
        result = CheckResult(
            name="x",
            description="",
            score=None,
            max_score=10,
            severity=Severity.NOT_EVALUABLE,
        )
        assert result.score_display == "N/A"


class TestBuildResult:
    def test_informed_only_is_informational_and_unscored(self):
        result = _build_result(
            SampleGenerationCheck(),
            code="import requests",
            informed_result=_gen_result(),
            informed_eval=_eval(criteria_met=5),
            truncated=False,
        )
        assert result.informational is True
        assert result.score is None
        assert result.metadata["code"] == "import requests"
        assert result.metadata["criteria_met"] == 5
        # Commentary, not a grade.
        assert any("not a score" in f for f in result.findings)

    def test_contamination_warning_fires_on_strong_baseline(self):
        result = _build_result(
            SampleGenerationCheck(differential=True),
            code="import requests",
            informed_result=_gen_result(),
            informed_eval=_eval(criteria_met=5),
            truncated=False,
            baseline_result=_gen_result(),
            baseline_eval=_eval(criteria_met=5, structural_score=10),
            baseline_code="import requests",
            identifier="URL: x",
        )
        assert result.metadata["contamination_warning"] is True
        assert any("Contamination warning" in f for f in result.findings)

    def test_no_contamination_warning_on_weak_baseline(self):
        result = _build_result(
            SampleGenerationCheck(differential=True),
            code="import requests",
            informed_result=_gen_result(),
            informed_eval=_eval(criteria_met=5),
            truncated=False,
            baseline_result=_gen_result(),
            baseline_eval=_eval(criteria_met=1, structural_score=2),
            baseline_code="x = 1",
            identifier="URL: x",
        )
        assert result.metadata["contamination_warning"] is False
        assert not any("Contamination warning" in f for f in result.findings)
