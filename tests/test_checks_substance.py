"""Tests for the substance-over-presence changes.

Example Coverage and Error Documentation both used to credit a key for
existing. These cover the cases where the key exists and the content behind
it is useless.
"""

from conftest import json_body, make_docs, make_endpoint

from artie.checks.error_documentation import ErrorDocumentationCheck
from artie.checks.example_coverage import ExampleCoverageCheck

GOOD_SCHEMA = {
    "type": "object",
    "required": ["id"],
    "properties": {"id": {"type": "string"}},
}


def run_examples(endpoints, components=None):
    return ExampleCoverageCheck().run(
        "", "openapi-yaml", make_docs(endpoints, components)
    )


def run_errors(endpoints, components=None):
    return ErrorDocumentationCheck().run(
        "", "openapi-yaml", make_docs(endpoints, components)
    )


class TestExampleSubstance:
    def test_valid_example_counts(self):
        endpoint = make_endpoint(
            responses={
                "200": {
                    "description": "ok",
                    "content": json_body(GOOD_SCHEMA, example={"id": "a"}),
                }
            }
        )
        result = run_examples([endpoint])
        assert result.score == 10
        assert result.metadata["endpoints_with_response_examples"] == 1

    def test_malformed_example_does_not_count(self):
        # The upload case: an `example` key holding unparseable text.
        endpoint = make_endpoint(
            responses={
                "200": {
                    "description": "ok",
                    "content": json_body(GOOD_SCHEMA, example='{"id": '),
                }
            }
        )
        result = run_examples([endpoint])
        assert result.score == 0
        assert result.metadata["endpoints_with_response_examples"] == 0
        assert result.metadata["endpoints_with_broken_response_examples"] == 1

    def test_example_contradicting_schema_does_not_count(self):
        endpoint = make_endpoint(
            responses={
                "200": {
                    "description": "ok",
                    # Omits the required `id`.
                    "content": json_body(GOOD_SCHEMA, example={"other": 1}),
                }
            }
        )
        result = run_examples([endpoint])
        assert result.score == 0
        assert result.metadata["endpoints_with_broken_response_examples"] == 1

    def test_broken_example_is_distinguished_from_missing(self):
        broken = make_endpoint(
            path="/a",
            responses={
                "200": {"description": "ok", "content": json_body(GOOD_SCHEMA, example="{")},
            },
        )
        missing = make_endpoint(
            path="/b",
            responses={"200": {"description": "ok", "content": json_body(GOOD_SCHEMA)}},
        )
        result = run_examples([broken, missing])
        assert result.metadata["endpoints_with_broken_response_examples"] == 1
        # Only the broken one produces a per-example detail line.
        assert len(result.metadata["broken_examples"]) == 1
        assert "/a" in result.metadata["broken_examples"][0]

    def test_one_good_example_among_several_is_enough(self):
        endpoint = make_endpoint(
            responses={
                "200": {
                    "description": "ok",
                    "content": {
                        "application/json": {
                            "schema": GOOD_SCHEMA,
                            "examples": {
                                "bad": {"value": {"wrong": 1}},
                                "good": {"value": {"id": "a"}},
                            },
                        }
                    },
                }
            }
        )
        assert run_examples([endpoint]).score == 10

    def test_external_value_is_credited_not_penalized(self):
        # We do not fetch the URL, so we have no evidence it is broken.
        endpoint = make_endpoint(
            responses={
                "200": {
                    "description": "ok",
                    "content": {
                        "application/json": {
                            "schema": GOOD_SCHEMA,
                            "examples": {
                                "a": {"externalValue": "https://x.test/e.json"}
                            },
                        }
                    },
                }
            }
        )
        result = run_examples([endpoint])
        assert result.score == 10
        assert result.metadata["endpoints_with_broken_response_examples"] == 0

    def test_request_example_validated_against_request_schema(self):
        endpoint = make_endpoint(
            method="post",
            requestBody={"content": json_body(GOOD_SCHEMA, example={"nope": 1})},
            responses={
                "200": {"description": "ok", "content": json_body(GOOD_SCHEMA, example={"id": "a"})}
            },
        )
        result = run_examples([endpoint])
        assert result.metadata["endpoints_with_request_examples"] == 0
        assert result.metadata["endpoints_with_broken_request_examples"] == 1


class TestErrorSchemaSubstance:
    def _endpoint(self, error_schema):
        return make_endpoint(
            responses={
                "200": {"description": "ok"},
                "400": {
                    "description": "The request body failed validation",
                    "content": {"application/json": {"schema": error_schema}},
                },
            }
        )

    def test_real_schema_is_credited(self):
        result = run_errors([self._endpoint(GOOD_SCHEMA)])
        assert result.metadata["errors_with_schema"] == 1
        assert result.metadata["errors_with_vacuous_schema"] == 0

    def test_empty_properties_is_not_credited(self):
        result = run_errors([self._endpoint({"properties": {}})])
        assert result.metadata["errors_with_schema"] == 0
        assert result.metadata["errors_with_vacuous_schema"] == 1

    def test_vacuous_schema_is_reported_as_placeholder(self):
        result = run_errors([self._endpoint({"properties": {}})])
        assert any("describes no fields" in f for f in result.findings)
        assert any("placeholder" in r.lower() for r in result.recommendations)

    def test_vacuous_schema_scores_below_real_schema(self):
        real = run_errors([self._endpoint(GOOD_SCHEMA)]).score
        vacuous = run_errors([self._endpoint({"properties": {}})]).score
        assert vacuous < real

    def test_ref_to_empty_component_is_not_credited(self):
        components = {"schemas": {"Error": {"properties": {}}}}
        endpoint = self._endpoint({"$ref": "#/components/schemas/Error"})
        result = run_errors([endpoint], components)
        assert result.metadata["errors_with_vacuous_schema"] == 1

    def test_absent_schema_is_not_counted_as_vacuous(self):
        # No schema at all is "missing", a different authoring problem.
        endpoint = make_endpoint(
            responses={
                "400": {"description": "The request body failed validation"}
            }
        )
        result = run_errors([endpoint])
        assert result.metadata["errors_with_schema"] == 0
        assert result.metadata["errors_with_vacuous_schema"] == 0
