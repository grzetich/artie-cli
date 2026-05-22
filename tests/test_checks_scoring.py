"""Tests for each check's scoring math, severity bands, and threshold buckets."""

import pytest
from helpers import base_spec, parsed

from artie.checks.auth_clarity import AuthClarityCheck
from artie.checks.base import BaseCheck, Severity
from artie.checks.endpoint_completeness import EndpointCompletenessCheck
from artie.checks.error_documentation import (
    ErrorDocumentationCheck,
    _has_shared_error_schema,
)
from artie.checks.example_coverage import ExampleCoverageCheck
from artie.checks.format_efficiency import FormatEfficiencyCheck
from artie.checks.parameter_naming import ParameterNamingCheck
from artie.checks.schema_complexity import (
    SchemaComplexityCheck,
    _max_depth,
    _score_for_depth,
)


class TestSeverityBands:
    """severity_for maps a 0-10 score to a band by fixed ratio cutoffs."""

    @pytest.mark.parametrize(
        "score,expected",
        [
            (10, Severity.EXCELLENT),
            (9, Severity.EXCELLENT),
            (8, Severity.GOOD),
            (7, Severity.GOOD),
            (6, Severity.NEEDS_WORK),
            (4, Severity.NEEDS_WORK),
            (3, Severity.POOR),
            (0, Severity.POOR),
        ],
    )
    def test_bands(self, score, expected):
        assert BaseCheck().severity_for(score) == expected


class TestFormatEfficiency:
    @pytest.mark.parametrize(
        "format_type,expected_score",
        [
            ("openapi-yaml", 10),
            ("yaml", 10),
            ("don", 9),
            ("markdown", 7),
            ("openapi-json", 5),
            ("json", 5),
            ("html", 1),
            ("unknown", 5),
        ],
    )
    def test_format_scores(self, format_type, expected_score):
        result = FormatEfficiencyCheck().run("some content here", format_type)
        assert result.score == expected_score

    def test_empty_content_not_evaluable(self):
        result = FormatEfficiencyCheck().run("   ", "openapi-yaml")
        assert not result.is_evaluable

    def test_html_severity_forced_poor(self):
        result = FormatEfficiencyCheck().run("<html></html>", "html")
        assert result.severity == Severity.POOR

    def test_cost_caveat_present(self):
        result = FormatEfficiencyCheck().run("openapi: 3.0.0\n" * 5, "openapi-yaml")
        assert any("Retail pricing" in f for f in result.findings)


class TestEndpointCompleteness:
    def test_full_marks(self):
        spec = base_spec(
            paths={
                "/books": {
                    "get": {"summary": "List books", "operationId": "listBooks"}
                }
            }
        )
        result = EndpointCompletenessCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 10

    def test_half_of_endpoints_documented(self):
        # 2 endpoints: one fully documented, one bare.
        spec = base_spec(
            paths={
                "/a": {"get": {"summary": "A", "operationId": "a"}},
                "/b": {"get": {}},
            }
        )
        result = EndpointCompletenessCheck().run("", "openapi-json", parsed(spec))
        # desc 0.5, opId 0.5 -> composite 0.5 -> 5
        assert result.score == 5

    def test_documented_path_parameter(self):
        spec = base_spec(
            paths={
                "/books/{bookId}": {
                    "get": {
                        "summary": "Get",
                        "operationId": "getBook",
                        "parameters": [
                            {
                                "name": "bookId",
                                "in": "path",
                                "description": "the book identifier",
                            }
                        ],
                    }
                }
            }
        )
        result = EndpointCompletenessCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 10

    def test_undocumented_path_parameter_drags_score(self):
        spec = base_spec(
            paths={
                "/books/{bookId}": {
                    "get": {
                        "summary": "Get",
                        "operationId": "getBook",
                        "parameters": [{"name": "bookId", "in": "path"}],
                    }
                }
            }
        )
        result = EndpointCompletenessCheck().run("", "openapi-json", parsed(spec))
        # subscores [desc 1, opId 1, path 0] -> 0.667 -> round -> 7
        assert result.score == 7

    def test_not_evaluable_without_openapi(self):
        result = EndpointCompletenessCheck().run("plain", "markdown", None)
        assert not result.is_evaluable

    def test_not_evaluable_with_no_endpoints(self):
        result = EndpointCompletenessCheck().run(
            "", "openapi-json", parsed(base_spec())
        )
        assert not result.is_evaluable


class TestExampleCoverage:
    def _spec_with_response_example(self, with_example: bool):
        content = (
            {"application/json": {"example": {"id": 1}}} if with_example else {}
        )
        return base_spec(
            paths={
                "/books": {
                    "get": {
                        "operationId": "list",
                        "responses": {"200": {"description": "ok", "content": content}},
                    }
                }
            }
        )

    def test_response_example_present(self):
        result = ExampleCoverageCheck().run(
            "", "openapi-json", parsed(self._spec_with_response_example(True))
        )
        assert result.score == 10

    def test_response_example_absent(self):
        result = ExampleCoverageCheck().run(
            "", "openapi-json", parsed(self._spec_with_response_example(False))
        )
        assert result.score == 0

    def test_request_example_missing_halves_score(self):
        spec = base_spec(
            paths={
                "/books": {
                    "post": {
                        "operationId": "create",
                        "requestBody": {
                            "content": {"application/json": {"schema": {}}}
                        },
                        "responses": {
                            "201": {
                                "description": "created",
                                "content": {
                                    "application/json": {"example": {"id": 1}}
                                },
                            }
                        },
                    }
                }
            }
        )
        result = ExampleCoverageCheck().run("", "openapi-json", parsed(spec))
        # response ratio 1.0, request ratio 0.0 -> avg 0.5 -> 5
        assert result.score == 5


class TestErrorDocumentation:
    def test_fully_documented_error(self):
        spec = base_spec(
            paths={
                "/books": {
                    "get": {
                        "operationId": "list",
                        "responses": {
                            "404": {
                                "description": "The requested book was not found",
                                "content": {
                                    "application/json": {"schema": {"type": "object"}}
                                },
                            }
                        },
                    }
                }
            }
        )
        result = ErrorDocumentationCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 10

    def test_bare_error_response(self):
        spec = base_spec(
            paths={
                "/books": {
                    "get": {
                        "operationId": "list",
                        "responses": {"404": {"description": "no"}},
                    }
                }
            }
        )
        result = ErrorDocumentationCheck().run("", "openapi-json", parsed(spec))
        # endpoint 1, desc 0 (too short), schema 0 -> 0.333 -> 3
        assert result.score == 3

    def test_shared_error_schema_detected(self):
        assert _has_shared_error_schema({"schemas": {"Error": {}}})
        assert _has_shared_error_schema({"schemas": {"ProblemDetails": {}}})
        assert not _has_shared_error_schema({"schemas": {"Book": {}}})
        assert not _has_shared_error_schema({})


class TestAuthClarity:
    def test_no_security_anywhere_scores_zero(self):
        spec = base_spec(paths={"/books": {"get": {"operationId": "list"}}})
        result = AuthClarityCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 0
        assert any("unauthenticated" in f for f in result.findings)

    def test_fully_documented_auth(self):
        spec = base_spec(
            paths={"/books": {"get": {"operationId": "list"}}},
            security=[{"bearerAuth": []}],
            components={
                "securitySchemes": {
                    "bearerAuth": {"type": "http", "scheme": "bearer"}
                }
            },
        )
        result = AuthClarityCheck().run("", "openapi-json", parsed(spec))
        # scheme defined 1, http type self-documents 1, global security covers
        # the one operation 1 -> composite 1 -> 10
        assert result.score == 10


class TestParameterNaming:
    def test_consistent_convention_scores_full(self):
        spec = base_spec(
            paths={
                "/books": {
                    "get": {
                        "operationId": "list",
                        "parameters": [
                            {"name": "userId", "in": "query"},
                            {"name": "bookId", "in": "query"},
                            {"name": "pageSize", "in": "query"},
                        ],
                    }
                }
            }
        )
        result = ParameterNamingCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 10
        assert result.metadata["primary_convention"] == "camelCase"

    def test_mixed_conventions_drag_score(self):
        spec = base_spec(
            paths={
                "/books": {
                    "get": {
                        "operationId": "list",
                        "parameters": [
                            {"name": "userId", "in": "query"},
                            {"name": "bookId", "in": "query"},
                            {"name": "created_at", "in": "query"},
                        ],
                    }
                }
            }
        )
        result = ParameterNamingCheck().run("", "openapi-json", parsed(spec))
        # camelCase 2 of 3 convention-bearing names -> 0.667 -> round -> 7
        assert result.score == 7


class TestSchemaComplexityBuckets:
    @pytest.mark.parametrize(
        "depth,expected",
        [
            (0, 10),
            (3, 10),
            (4, 8),
            (5, 8),
            (6, 5),
            (7, 5),
            (8, 3),
            (9, 3),
            (10, 1),
            (50, 1),
        ],
    )
    def test_score_for_depth(self, depth, expected):
        assert _score_for_depth(depth) == expected

    def test_max_depth_flat_schema(self):
        assert _max_depth({"type": "string"}, {}, set()) == 0

    def test_max_depth_one_level(self):
        schema = {"properties": {"a": {"type": "string"}}}
        assert _max_depth(schema, {}, set()) == 1

    def test_max_depth_nested(self):
        schema = {
            "properties": {
                "a": {"properties": {"b": {"properties": {"c": {}}}}}
            }
        }
        assert _max_depth(schema, {}, set()) == 3

    def test_max_depth_follows_refs(self):
        schemas = {
            "A": {"properties": {"a": {"$ref": "#/components/schemas/B"}}},
            "B": {"properties": {"b": {"type": "string"}}},
        }
        assert _max_depth(schemas["A"], schemas, set()) == 2

    def test_max_depth_handles_ref_cycles(self):
        schemas = {
            "A": {"properties": {"a": {"$ref": "#/components/schemas/B"}}},
            "B": {"properties": {"b": {"$ref": "#/components/schemas/A"}}},
        }
        # Must terminate and return a finite depth despite the cycle.
        depth = _max_depth(schemas["A"], schemas, set())
        assert isinstance(depth, int)
        assert depth < 100

    def test_shallow_schema_scores_full(self):
        spec = base_spec(
            components={
                "schemas": {
                    "Book": {"properties": {"title": {"type": "string"}}}
                }
            }
        )
        result = SchemaComplexityCheck().run("", "openapi-json", parsed(spec))
        assert result.score == 10
        assert result.metadata["max_depth"] == 1

    def test_not_evaluable_without_component_schemas(self):
        result = SchemaComplexityCheck().run(
            "", "openapi-json", parsed(base_spec())
        )
        assert not result.is_evaluable
