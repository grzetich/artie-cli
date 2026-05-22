"""Tests for baseline (saved JSON report) loading and delta computation."""

import json

import pytest

from artie.baseline import Baseline, BaselineError, load_baseline

REPORT = {
    "source": "examples/sample-openapi.yaml",
    "format": "openapi-yaml",
    "tool": "artie-cli",
    "scoring_version": "1.0",
    "checks": [
        {"name": "Format Efficiency", "score": 10},
        {"name": "Endpoint Completeness", "score": 6},
        {"name": "Sample Generation", "score": None},
    ],
}


def write_report(directory, data):
    path = directory / "previous.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadBaseline:
    def test_loads_scores(self, tmp_path):
        baseline = load_baseline(write_report(tmp_path, REPORT))
        assert baseline.scores["Format Efficiency"] == 10
        assert baseline.scores["Endpoint Completeness"] == 6
        assert baseline.scores["Sample Generation"] is None

    def test_carries_metadata(self, tmp_path):
        baseline = load_baseline(write_report(tmp_path, REPORT))
        assert baseline.scoring_version == "1.0"
        assert baseline.source == "examples/sample-openapi.yaml"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(BaselineError, match="not found"):
            load_baseline(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(BaselineError, match="not valid JSON"):
            load_baseline(path)

    def test_not_a_report_raises(self, tmp_path):
        path = tmp_path / "other.json"
        path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        with pytest.raises(BaselineError, match="not an artie JSON report"):
            load_baseline(path)


class TestDeltas:
    def test_score_for(self):
        baseline = Baseline(scores={"Format Efficiency": 8})
        assert baseline.score_for("Format Efficiency") == 8
        assert baseline.score_for("Absent Check") is None

    def test_delta_positive(self):
        baseline = Baseline(scores={"Format Efficiency": 6})
        assert baseline.delta_for("Format Efficiency", 9) == 3

    def test_delta_negative(self):
        baseline = Baseline(scores={"Format Efficiency": 9})
        assert baseline.delta_for("Format Efficiency", 6) == -3

    def test_delta_none_when_prior_missing(self):
        assert Baseline().delta_for("New Check", 7) is None

    def test_delta_none_when_current_unscored(self):
        baseline = Baseline(scores={"Sample Generation": 5})
        assert baseline.delta_for("Sample Generation", None) is None
