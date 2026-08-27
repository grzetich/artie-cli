"""Markdown reporter: filename derivation and rendered structure."""

from artie.checks.base import CheckResult, Severity
from artie.reporters.markdown_report import render, report_filename


def result(
    name="Format Efficiency",
    score=8,
    severity=Severity.GOOD,
    findings=None,
    recommendations=None,
    metadata=None,
):
    return CheckResult(
        name=name,
        description="A check description.",
        score=score,
        max_score=10,
        severity=severity,
        findings=findings if findings is not None else ["A finding"],
        recommendations=recommendations or [],
        metadata=metadata or {},
    )


class TestReportFilename:
    def test_url_uses_domain_and_path(self):
        assert (
            report_filename("https://api.example.com/v1/openapi.yaml")
            == "api-example-com-v1-openapi.md"
        )

    def test_url_without_path(self):
        assert report_filename("https://example.com/") == "example-com.md"

    def test_local_file_uses_its_own_name(self):
        assert report_filename("./examples/sample-openapi.yaml") == "sample-openapi.md"

    def test_local_file_name_is_independent_of_how_it_was_addressed(self):
        # Same document via two paths must not produce two report files.
        assert report_filename("/home/me/proj/openapi.yaml") == report_filename(
            "./openapi.yaml"
        )

    def test_doc_extension_is_stripped(self):
        assert report_filename("spec.JSON") == "spec.md"
        assert report_filename("page.html") == "page.md"

    def test_result_is_always_a_markdown_file(self):
        for target in ("/", "./", "https://example.com", "a.yaml"):
            assert report_filename(target).endswith(".md")

    def test_degenerate_target_falls_back(self):
        assert report_filename("/") == "artie-report.md"


class TestRender:
    def test_has_title_and_summary_table(self):
        out = render("spec.yaml", "openapi-yaml", [result()])
        assert out.startswith("# API Documentation AI-Readiness Report")
        assert "| | Check | Score | Severity |" in out
        assert "| PASS | Format Efficiency | 8/10 | good |" in out

    def test_reports_source_and_format(self):
        out = render("spec.yaml", "openapi-yaml", [result()])
        assert "`spec.yaml`" in out
        assert "openapi-yaml" in out

    def test_uses_format_label_when_given(self):
        out = render("d.md", "markdown", [result()], format_label="OpenAPI passthrough")
        assert "OpenAPI passthrough" in out

    def test_not_evaluable_check_renders_na(self):
        out = render(
            "spec.yaml",
            "openapi-yaml",
            [result(score=None, severity=Severity.NOT_EVALUABLE)],
        )
        assert "N/A" in out
        assert "not evaluable" in out

    def test_mean_counts_only_evaluable_checks(self):
        results = [
            result(name="A", score=10, severity=Severity.EXCELLENT),
            result(name="B", score=None, severity=Severity.NOT_EVALUABLE),
        ]
        out = render("spec.yaml", "openapi-yaml", results)
        assert "1 of 2 checks evaluable; mean score 10.0/10." in out

    def test_indented_findings_become_a_sublist(self):
        out = render(
            "spec.yaml",
            "openapi-yaml",
            [result(findings=["Cost to read:", "  Claude Opus 5: 1¢"])],
        )
        assert "- Cost to read:" in out
        assert "  - Claude Opus 5: 1¢" in out

    def test_recommendations_are_rendered(self):
        out = render(
            "spec.yaml", "openapi-yaml", [result(recommendations=["Serve YAML."])]
        )
        assert "**Recommendations**" in out
        assert "- Serve YAML." in out

    def test_generated_code_becomes_a_python_fence(self):
        out = render(
            "spec.yaml",
            "openapi-yaml",
            [result(name="Generation Quality", metadata={"code": "import requests"})],
        )
        assert "```python\nimport requests\n```" in out

    def test_baseline_code_is_collapsed(self):
        out = render(
            "spec.yaml",
            "openapi-yaml",
            [result(metadata={"baseline_code": "x = 1"})],
        )
        assert "<details><summary>Baseline code" in out

    def test_pipe_in_a_check_name_does_not_break_the_table(self):
        out = render("spec.yaml", "openapi-yaml", [result(name="A | B")])
        assert r"A \| B" in out
        # Column count must match the header once escaped pipes are discounted.
        cells = lambda line: line.replace(r"\|", "").count("|")
        header, *rows = [ln for ln in out.splitlines() if ln.startswith("| ")]
        assert all(cells(row) == cells(header) for row in rows)

    def test_content_type_shown_only_when_present(self):
        assert "Server returned" not in render("s", "yaml", [result()])
        assert "Server returned" in render(
            "s", "yaml", [result()], content_type="text/html"
        )

    def test_footer_links_the_research_site(self):
        assert "tokensnotjokin.com" in render("s", "yaml", [result()])
