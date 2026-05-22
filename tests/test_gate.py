"""Tests for the pass/fail gate logic in the CLI."""

from rich.console import Console

from artie.checks.base import CheckResult, Severity
from artie.cli import _gate_failed
from artie.config import ArtieConfig

ERR = Console(stderr=True, quiet=True)


def result(name: str, score: int | None, informational: bool = False) -> CheckResult:
    severity = Severity.NOT_EVALUABLE if score is None else Severity.GOOD
    return CheckResult(
        name=name,
        description="",
        score=score,
        max_score=10,
        severity=severity,
        informational=informational,
    )


class TestGate:
    def test_no_thresholds_never_fails(self):
        results = [result("Format Efficiency", 1)]
        assert not _gate_failed(results, ArtieConfig(), None, ERR)

    def test_cli_fail_under_gates_all_checks(self):
        results = [result("Format Efficiency", 5), result("Auth Clarity", 9)]
        assert _gate_failed(results, ArtieConfig(), 7, ERR)

    def test_passing_run_does_not_fail(self):
        results = [result("Format Efficiency", 8), result("Auth Clarity", 9)]
        assert not _gate_failed(results, ArtieConfig(), 7, ERR)

    def test_per_check_threshold_applies(self):
        config = ArtieConfig(thresholds={"Format Efficiency": 9})
        results = [result("Format Efficiency", 8)]
        assert _gate_failed(results, config, None, ERR)

    def test_per_check_threshold_overrides_cli_fail_under(self):
        # CLI says 7 (would fail an 8), config says 5 for this check (passes).
        config = ArtieConfig(thresholds={"Format Efficiency": 5})
        results = [result("Format Efficiency", 8)]
        assert not _gate_failed(results, config, 7, ERR)

    def test_ignored_check_never_fails(self):
        config = ArtieConfig(ignore=["Format Efficiency"])
        results = [result("Format Efficiency", 0)]
        assert not _gate_failed(results, config, 7, ERR)

    def test_informational_check_skipped(self):
        results = [result("Sample Generation", None, informational=True)]
        assert not _gate_failed(results, ArtieConfig(), 7, ERR)

    def test_not_evaluable_check_skipped(self):
        results = [result("Schema Complexity", None)]
        assert not _gate_failed(results, ArtieConfig(), 7, ERR)

    def test_config_global_fail_under_used_when_no_cli_flag(self):
        config = ArtieConfig(fail_under=8)
        results = [result("Format Efficiency", 7)]
        assert _gate_failed(results, config, None, ERR)
