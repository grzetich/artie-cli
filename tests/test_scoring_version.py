"""Guard the scoring rubric version against drift.

artie.SCORING_VERSION is the runtime source of truth; pyproject.toml mirrors
it under [tool.artie] for packaging tools. This test fails if the two ever
disagree, and if JSON output stops emitting the version.
"""

import sys
from pathlib import Path

from artie import SCORING_VERSION
from artie.checks.format_efficiency import FormatEfficiencyCheck
from artie.reporters import json_report

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_pyproject_mirrors_runtime_version():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pyproject_version = data["tool"]["artie"]["scoring_version"]
    assert pyproject_version == SCORING_VERSION


def test_json_output_includes_scoring_version():
    result = FormatEfficiencyCheck().run("openapi: 3.0.0\n", "openapi-yaml")
    report = json_report.to_dict("src", "openapi-yaml", [result])
    assert report["scoring_version"] == SCORING_VERSION


def test_json_output_includes_baseline_deltas():
    from artie.baseline import Baseline

    result = FormatEfficiencyCheck().run("openapi: 3.0.0\n", "openapi-yaml")
    baseline = Baseline(scores={"Format Efficiency": 7})
    report = json_report.to_dict("src", "openapi-yaml", [result], baseline)
    check = report["checks"][0]
    assert check["baseline_score"] == 7
    assert check["delta"] == result.score - 7
    assert report["baseline"]["scoring_version"] is None


def test_informational_flag_serialized():
    # A scored check is not informational.
    result = FormatEfficiencyCheck().run("openapi: 3.0.0\n", "openapi-yaml")
    report = json_report.to_dict("src", "openapi-yaml", [result])
    assert report["checks"][0]["informational"] is False
