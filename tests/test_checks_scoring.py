"""Tests for the remaining scoring changes.

Covers per-location parameter naming, the OpenAPI passthrough label, inline
schema analysis, prose structure, and servers validation.
"""

from pathlib import Path

from conftest import json_body, make_docs, make_endpoint

from artie.checks.endpoint_completeness import EndpointCompletenessCheck
from artie.checks.format_efficiency import FormatEfficiencyCheck
from artie.checks.parameter_naming import ParameterNamingCheck
from artie.checks.prose_structure import ProseStructureCheck
from artie.checks.schema_complexity import SchemaComplexityCheck
from artie.parsers import detect_format, display_format, parse

BODY_SCHEMA = {
    "type": "object",
    "properties": {
        "fileName": {"type": "string"},
        "contentLength": {"type": "integer"},
    },
}


def naming(endpoints, components=None):
    return ParameterNamingCheck().run(
        "", "openapi-yaml", make_docs(endpoints, components)
    )


class TestParameterNamingPerLocation:
    def test_http_header_convention_alongside_camel_body_is_not_penalized(self):
        # Kebab/Train-Case headers plus camelCase body is standard HTTP, and
        # used to score as "mixed" because all names were pooled.
        endpoint = make_endpoint(
            method="post",
            parameters=[
                {"name": "Content-Type", "in": "header"},
                {"name": "X-Api-Key", "in": "header"},
                {"name": "x-request-id", "in": "header"},
            ],
            requestBody={"content": json_body(BODY_SCHEMA)},
        )
        assert naming([endpoint]).score == 10

    def test_mixed_conventions_within_one_location_still_penalized(self):
        endpoint = make_endpoint(
            method="post",
            requestBody={
                "content": json_body(
                    {
                        "type": "object",
                        "properties": {
                            "fileName": {},
                            "file_size": {},
                            "ContentType": {},
                            "upload-url": {},
                        },
                    }
                )
            },
        )
        assert naming([endpoint]).score <= 3

    def test_non_hyphenated_header_is_flagged(self):
        endpoint = make_endpoint(
            parameters=[
                {"name": "content_type", "in": "header"},
                {"name": "Accept", "in": "header"},
            ]
        )
        result = naming([endpoint])
        assert result.score < 10
        assert any("hyphen" in r for r in result.recommendations)

    def test_query_and_body_scored_independently(self):
        # snake_case query params with camelCase body: each internally
        # consistent, so the document should not be marked inconsistent.
        endpoint = make_endpoint(
            method="post",
            parameters=[
                {"name": "page_size", "in": "query"},
                {"name": "page_token", "in": "query"},
            ],
            requestBody={"content": json_body(BODY_SCHEMA)},
        )
        assert naming([endpoint]).score == 10

    def test_per_location_metadata_is_exposed(self):
        endpoint = make_endpoint(
            parameters=[{"name": "Content-Type", "in": "header"}],
            requestBody={"content": json_body(BODY_SCHEMA)},
        )
        meta = naming([endpoint]).metadata
        assert "header" in meta["per_location"]
        assert "body" in meta["per_location"]

    def test_not_evaluable_without_names(self):
        assert naming([make_endpoint()]).is_evaluable is False


class TestOpenAPIPassthroughLabel:
    SPEC_IN_MARKDOWN = """# Payments API

Prose describing the API, long enough to look like a real page.

```yaml
openapi: 3.0.0
info: {title: Payments, version: "1.0"}
paths:
  /charges:
    get:
      summary: List charges
      responses:
        "200": {description: OK}
```
"""

    def _parsed(self):
        fmt = detect_format(self.SPEC_IN_MARKDOWN, path=Path("page.md"))
        return fmt, parse(self.SPEC_IN_MARKDOWN, fmt)

    def test_spec_in_markdown_is_labeled_passthrough(self):
        fmt, parsed = self._parsed()
        assert fmt == "markdown"
        assert display_format(fmt, parsed) == "OpenAPI passthrough"

    def test_plain_markdown_keeps_its_label(self):
        content = "# Guide\n\nJust prose, no spec.\n"
        parsed = parse(content, "markdown")
        assert display_format("markdown", parsed) == "markdown"

    def test_raw_format_is_unchanged_for_scoring(self):
        # The label is presentational; the score still keys off markdown.
        fmt, parsed = self._parsed()
        result = FormatEfficiencyCheck().run(self.SPEC_IN_MARKDOWN, fmt, parsed)
        assert result.metadata["format"] == "markdown"
        assert result.metadata["format_label"] == "OpenAPI passthrough"
        assert result.findings[0] == "Detected format: OpenAPI passthrough"

    def test_structured_format_label_is_passthrough_free(self):
        assert display_format("openapi-yaml", None) == "openapi-yaml"


class TestInlineSchemaComplexity:
    def test_inline_schemas_are_analyzed_without_components(self):
        endpoint = make_endpoint(
            method="post",
            path="/uploads",
            requestBody={
                "content": json_body(
                    {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                            }
                        },
                    }
                )
            },
        )
        result = SchemaComplexityCheck().run(
            "", "openapi-yaml", make_docs([endpoint])
        )
        assert result.is_evaluable
        assert result.metadata["schema_source"].startswith("inline")
        assert result.metadata["schemas_analyzed"] == 1

    def test_components_are_preferred_when_present(self):
        endpoint = make_endpoint(
            method="post",
            requestBody={"content": json_body({"type": "object", "properties": {}})},
        )
        components = {
            "schemas": {"Thing": {"type": "object", "properties": {"a": {"type": "string"}}}}
        }
        result = SchemaComplexityCheck().run(
            "", "openapi-yaml", make_docs([endpoint], components)
        )
        assert result.metadata["schema_source"] == "components.schemas"

    def test_inline_schema_names_point_at_their_operation(self):
        endpoint = make_endpoint(
            method="post",
            path="/uploads",
            requestBody={"content": json_body({"type": "object", "properties": {"a": {}}})},
        )
        result = SchemaComplexityCheck().run(
            "", "openapi-yaml", make_docs([endpoint])
        )
        assert any("POST /uploads" in name for name in result.metadata["depth_per_schema"])

    def test_still_not_evaluable_with_nothing_to_measure(self):
        result = SchemaComplexityCheck().run(
            "", "openapi-yaml", make_docs([make_endpoint()])
        )
        assert result.is_evaluable is False


class TestServersValidation:
    def _run(self, servers):
        raw = {"openapi": "3.0.0"}
        if servers is not None:
            raw["servers"] = servers
        endpoint = make_endpoint(summary="Get x", operationId="getX")
        return EndpointCompletenessCheck().run(
            "", "openapi-yaml", make_docs([endpoint], raw=raw)
        )

    def test_absolute_url_passes(self):
        result = self._run([{"url": "https://api.example.com/v1"}])
        assert not any("missing a scheme" in f for f in result.findings)

    def test_schemeless_url_is_flagged(self):
        result = self._run([{"url": "api.example.com/v1"}])
        assert any("missing a scheme" in f for f in result.findings)
        assert any("https://" in r for r in result.recommendations)

    def test_relative_url_is_allowed(self):
        # OpenAPI permits a server URL relative to the document's origin.
        result = self._run([{"url": "/v1"}])
        assert not any("missing a scheme" in f for f in result.findings)

    def test_templated_url_is_reported_separately(self):
        result = self._run([{"url": "{region}.example.com"}])
        assert any("templated" in f for f in result.findings)

    def test_missing_servers_block_is_flagged(self):
        result = self._run(None)
        assert any("never states a base URL" in f for f in result.findings)

    def test_servers_do_not_affect_the_score(self):
        # Scored per endpoint; the base URL is reported, not averaged in.
        good = self._run([{"url": "https://api.example.com"}]).score
        bad = self._run([{"url": "api.example.com"}]).score
        assert good == bad


class TestProseStructure:
    WELL_FORMED = """# Payments API

An introduction with enough words in it to clear the stub threshold that this
check applies before it will score anything at all.

## Create a charge

Create a charge against a card.

```python
requests.post("https://api.example.com/charges", json={"amount": 100})
```

## Refund a charge

Refund a charge that already settled.

```bash
curl -X POST https://api.example.com/refunds
```
"""

    def _run(self, content, format_type="markdown"):
        return ProseStructureCheck().run(content, format_type)

    def test_well_formed_page_scores_high(self):
        assert self._run(self.WELL_FORMED).score >= 9

    def test_wall_of_text_scores_low(self):
        content = "## Section\n\n" + ("filler words here. " * 400)
        assert self._run(content).score <= 4

    def test_discriminates_between_pages(self):
        # The point of the check: markdown pages must not all score the same.
        good = self._run(self.WELL_FORMED).score
        poor = self._run("## Only heading\n\n" + ("text " * 300)).score
        assert good > poor

    def test_missing_h1_is_reported(self):
        content = "## Sub only\n\n" + ("words " * 100)
        assert any("No H1" in f for f in self._run(content).findings)

    def test_skipped_heading_level_is_reported(self):
        content = "# Title\n\n" + ("words " * 60) + "\n\n### Skipped\n\n" + ("words " * 60)
        assert any("skipped heading level" in f for f in self._run(content).findings)

    def test_untagged_code_fence_is_reported(self):
        content = "# Title\n\n" + ("words " * 80) + "\n\n```\nplain\n```\n"
        assert any("no language tag" in f for f in self._run(content).findings)

    def test_version_in_heading_is_a_staleness_signal(self):
        content = "# API v2.1\n\n" + ("words " * 80)
        assert any("version or year" in f for f in self._run(content).findings)

    def test_heading_inside_code_fence_is_not_counted(self):
        content = (
            "# Title\n\n" + ("words " * 80) + "\n\n```bash\n# not a heading\necho hi\n```\n"
        )
        assert self._run(content).metadata["headings"] == 1

    def test_not_evaluable_on_structured_formats(self):
        assert self._run("openapi: 3.0.0", "openapi-yaml").is_evaluable is False

    def test_not_evaluable_on_stub_pages(self):
        assert self._run("# Hi").is_evaluable is False


class TestProseStructureHTML:
    """HTML is prose wearing markup; the same four signals must apply to it."""

    PAGE = """<!DOCTYPE html>
<html><head><title>Payments</title>
<style>.legacy-nav{color:red} .deprecated-badge{display:none}</style>
<script>var TODO = "analytics";</script></head>
<body>
<h1>Payments API</h1>
<p>An introduction with enough words in it to clear the stub threshold that
this check applies before it will score anything at all.</p>
<h2>Create a charge</h2>
<p>Create a charge against a card using the endpoint below.</p>
<pre><code class="language-python">requests.post("https://api.example.com/charges")</code></pre>
<h2>Refund a charge</h2>
<p>Refund a charge that already settled.</p>
<pre><code class="lang-bash">curl -X POST https://api.example.com/refunds</code></pre>
</body></html>
"""

    def _run(self, content, format_type="html"):
        return ProseStructureCheck().run(content, format_type)

    def test_html_is_evaluable(self):
        # The regression: HTML used to fall through to not_evaluable.
        assert self._run(self.PAGE).is_evaluable is True

    def test_well_formed_html_scores_high(self):
        assert self._run(self.PAGE).score >= 9

    def test_reports_that_it_scored_extracted_prose(self):
        assert any("extracted from HTML" in f for f in self._run(self.PAGE).findings)
        assert self._run(self.PAGE).metadata["converted_from_html"] is True

    def test_heading_levels_survive_conversion(self):
        metadata = self._run(self.PAGE).metadata
        assert metadata["headings"] == 3
        assert metadata["heading_levels"] == [1, 2]

    def test_pre_blocks_become_code_blocks_with_language(self):
        metadata = self._run(self.PAGE).metadata
        assert metadata["code_blocks"] == 2
        assert metadata["code_blocks_with_language"] == 2

    def test_untagged_pre_is_reported(self):
        page = self.PAGE.replace('<code class="lang-bash">', "<code>")
        assert any("no language tag" in f for f in self._run(page).findings)

    def test_script_and_style_do_not_trip_staleness(self):
        # "TODO" sits in a <script> and "legacy"/"deprecated" in CSS class
        # names. Scoring raw markup would flag all three as stale prose.
        result = self._run(self.PAGE)
        assert result.metadata["subscores"]["staleness"] == 1.0

    def test_stale_markers_in_real_prose_are_still_caught(self):
        page = self.PAGE.replace(
            "<p>Refund a charge that already settled.</p>",
            "<p>This endpoint is deprecated and will be removed.</p>",
        )
        assert any("Staleness markers" in f for f in self._run(page).findings)

    def test_markup_heavy_but_prose_thin_page_is_a_stub(self):
        page = "<html><body>" + '<div class="x"></div>' * 200 + "<p>Hi</p></body></html>"
        result = self._run(page)
        assert result.is_evaluable is False
        assert "Extracted prose" in result.findings[0]

    def test_missing_h1_is_reported_in_html(self):
        page = self.PAGE.replace("<h1>Payments API</h1>", "<h2>Payments API</h2>")
        assert any("No H1" in f for f in self._run(page).findings)
