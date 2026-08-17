"""Tests for the shared schema and example helpers.

These back the "substance, not presence" change: the helpers decide whether a
schema says anything and whether an example holds up, so the checks that call
them stop crediting placeholders.
"""

import pytest

from artie.checks._schema_utils import (
    is_vacuous_schema,
    parse_example,
    resolve_ref,
    validate_example,
)

COMPONENTS = {
    "schemas": {
        "Empty": {"properties": {}},
        "Error": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
        },
        "Loop": {"$ref": "#/components/schemas/Loop"},
    }
}


class TestIsVacuousSchema:
    @pytest.mark.parametrize(
        "schema",
        [
            {},
            {"properties": {}},
            {"type": "object", "properties": {}},
            {"type": "object"},
            {"description": "an error", "title": "Error"},
            None,
            "not a schema",
        ],
        ids=[
            "empty-dict",
            "empty-properties",
            "object-with-empty-properties",
            "object-without-properties",
            "prose-only-no-shape-keys",
            "none",
            "not-a-mapping",
        ],
    )
    def test_vacuous(self, schema):
        assert is_vacuous_schema(schema) is True

    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "string"},
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "array", "items": {"type": "string"}},
            {"enum": ["a", "b"]},
            {"type": "object", "additionalProperties": {"type": "string"}},
        ],
        ids=["scalar", "object", "array", "enum", "additional-properties"],
    )
    def test_substantive(self, schema):
        assert is_vacuous_schema(schema) is False

    def test_follows_refs(self):
        assert is_vacuous_schema({"$ref": "#/components/schemas/Empty"}, COMPONENTS)
        assert not is_vacuous_schema(
            {"$ref": "#/components/schemas/Error"}, COMPONENTS
        )

    def test_ref_cycle_terminates(self):
        # Must not recurse forever; that it returns at all is the assertion.
        result = is_vacuous_schema(
            {"$ref": "#/components/schemas/Loop"}, COMPONENTS
        )
        assert isinstance(result, bool)

    def test_combinator_vacuous_only_when_every_branch_is(self):
        assert is_vacuous_schema({"allOf": [{}, {"properties": {}}]})
        assert not is_vacuous_schema({"allOf": [{}, {"type": "string"}]})


class TestResolveRef:
    def test_resolves_known_ref(self):
        assert resolve_ref({"$ref": "#/components/schemas/Error"}, COMPONENTS) == (
            COMPONENTS["schemas"]["Error"]
        )

    def test_returns_input_for_unknown_ref(self):
        schema = {"$ref": "#/components/schemas/Missing"}
        assert resolve_ref(schema, COMPONENTS) == schema

    def test_returns_input_for_non_ref(self):
        schema = {"type": "string"}
        assert resolve_ref(schema, COMPONENTS) == schema


class TestParseExample:
    def test_structured_values_pass_through(self):
        ok, value, error = parse_example({"a": 1})
        assert (ok, value, error) == (True, {"a": 1}, None)

    def test_serialized_json_string_is_parsed(self):
        ok, value, error = parse_example('{"fileName": "a.png"}')
        assert ok and value == {"fileName": "a.png"} and error is None

    def test_truncated_json_is_rejected(self):
        # The malformed-upload case: looks present, is unusable.
        ok, value, error = parse_example('{"fileName": ')
        assert ok is False
        assert value is None
        assert "not valid JSON or YAML" in error

    def test_empty_string_is_rejected(self):
        ok, _, error = parse_example("   ")
        assert ok is False and "empty string" in error

    def test_null_is_rejected(self):
        ok, _, error = parse_example(None)
        assert ok is False and "null" in error

    def test_plain_scalar_string_is_not_an_error(self):
        # `example: hello` on a string field is legitimate.
        ok, value, error = parse_example("hello")
        assert (ok, value, error) == (True, "hello", None)


class TestValidateExample:
    SCHEMA = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }

    def test_valid_example_reports_nothing(self):
        assert validate_example({"id": 1, "name": "x"}, self.SCHEMA) == []

    def test_type_mismatch_is_reported(self):
        problems = validate_example({"id": "1", "name": "x"}, self.SCHEMA)
        assert any("declares integer" in p for p in problems)

    def test_missing_required_property_is_reported(self):
        problems = validate_example({"id": 1}, self.SCHEMA)
        assert any("omits required property name" in p for p in problems)

    def test_wrong_container_type_is_reported(self):
        problems = validate_example([], self.SCHEMA)
        assert any("declares object" in p for p in problems)

    def test_nested_array_item_type_is_checked(self):
        problems = validate_example(
            {"id": 1, "name": "x", "tags": [1]}, self.SCHEMA
        )
        assert any("tags[0]" in p for p in problems)

    def test_bool_is_not_accepted_as_integer(self):
        # bool subclasses int in Python; the validator must not be fooled.
        problems = validate_example(True, {"type": "integer"})
        assert problems != []

    def test_enum_membership_is_checked(self):
        assert validate_example("c", {"enum": ["a", "b"]}) != []
        assert validate_example("a", {"enum": ["a", "b"]}) == []

    def test_unknown_keywords_do_not_false_fail(self):
        # Not a full JSON Schema validator; exotic keywords must be ignored
        # rather than reported as violations.
        schema = {"type": "string", "minLength": 5, "pattern": "^a"}
        assert validate_example("ab", schema) == []
