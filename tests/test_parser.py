"""Tests for the OpenAPI parser, including embedded-spec extraction."""

from artie.parsers.openapi import (
    _extract_embedded_openapi,
    parse,
    path_parameters,
)

OPENAPI_YAML = """\
openapi: 3.0.0
info:
  title: Book API
paths:
  /books:
    get:
      operationId: listBooks
      responses:
        '200':
          description: ok
  /books/{bookId}:
    get:
      operationId: getBook
      responses:
        '200':
          description: ok
components:
  schemas:
    Book:
      type: object
"""

OPENAPI_JSON = (
    '{"openapi": "3.0.0", "info": {"title": "J"}, '
    '"paths": {"/x": {"get": {"operationId": "getX"}}}}'
)


class TestParseStructured:
    def test_parse_yaml_extracts_endpoints(self):
        docs = parse(OPENAPI_YAML, "openapi-yaml")
        assert docs.parsed
        assert docs.is_openapi
        assert len(docs.endpoints) == 2
        assert {e.display for e in docs.endpoints} == {
            "GET /books",
            "GET /books/{bookId}",
        }

    def test_parse_yaml_extracts_components(self):
        docs = parse(OPENAPI_YAML, "openapi-yaml")
        assert "Book" in docs.components.get("schemas", {})

    def test_parse_json(self):
        docs = parse(OPENAPI_JSON, "openapi-json")
        assert docs.is_openapi
        assert docs.endpoints[0].operation_id == "getX"

    def test_invalid_yaml_returns_parse_error(self):
        docs = parse("openapi: 3.0.0\n  bad: : indent", "openapi-yaml")
        assert not docs.parsed
        assert docs.parse_error is not None

    def test_invalid_json_returns_parse_error(self):
        docs = parse('{"openapi": ', "openapi-json")
        assert not docs.parsed
        assert docs.parse_error is not None

    def test_non_mapping_top_level(self):
        docs = parse("[1, 2, 3]", "openapi-json")
        assert not docs.parsed
        assert "not a mapping" in docs.parse_error

    def test_unstructured_format_has_no_parser(self):
        docs = parse("<html></html>", "html")
        assert not docs.parsed
        assert "No structured parser" in docs.parse_error

    def test_endpoints_skip_non_method_keys(self):
        # `parameters` and `summary` at the path-item level are not methods.
        spec = (
            '{"openapi":"3.0.0","info":{"title":"x"},"paths":'
            '{"/p":{"summary":"s","parameters":[],"get":{"operationId":"g"}}}}'
        )
        docs = parse(spec, "openapi-json")
        assert len(docs.endpoints) == 1
        assert docs.endpoints[0].method == "get"


class TestEmbeddedExtraction:
    def test_yaml_fence_with_language(self):
        md = "# Docs\n\n```yaml\nopenapi: 3.0.0\npaths: {}\n```\n"
        docs = parse(md, "markdown")
        assert docs.is_openapi
        assert docs.extracted_from == "markdown"

    def test_json_fence(self):
        md = '# Docs\n\n```json\n{"openapi": "3.0.0", "paths": {}}\n```\n'
        docs = parse(md, "markdown")
        assert docs.is_openapi
        assert docs.extracted_from == "markdown"

    def test_fence_without_language_label(self):
        # Docs sites sometimes omit the fence language.
        md = "# Docs\n\n```\nopenapi: 3.0.0\npaths: {}\n```\n"
        docs = parse(md, "markdown")
        assert docs.is_openapi

    def test_first_non_spec_fence_is_skipped(self):
        md = (
            "# Docs\n\n```python\nprint('hi')\n```\n\n"
            "```yaml\nopenapi: 3.0.0\npaths: {}\n```\n"
        )
        docs = parse(md, "markdown")
        assert docs.is_openapi

    def test_markdown_without_embedded_spec(self):
        docs = parse("# Just prose\n\nNo spec here.\n", "markdown")
        assert not docs.parsed
        assert "No embedded OpenAPI spec" in docs.parse_error

    def test_extract_returns_lang(self):
        body, lang = _extract_embedded_openapi(
            "```yaml\nopenapi: 3.0.0\n```"
        )
        assert lang == "yaml"
        assert "openapi: 3.0.0" in body

    def test_extract_json_lang(self):
        result = _extract_embedded_openapi(
            '```\n{"openapi": "3.0.0"}\n```'
        )
        assert result is not None
        _, lang = result
        assert lang == "json"

    def test_extract_none_when_absent(self):
        assert _extract_embedded_openapi("```\nplain text\n```") is None


class TestPathParameters:
    def test_single_parameter(self):
        assert path_parameters("/books/{bookId}") == ["bookId"]

    def test_multiple_parameters(self):
        assert path_parameters("/users/{userId}/books/{bookId}") == [
            "userId",
            "bookId",
        ]

    def test_no_parameters(self):
        assert path_parameters("/books") == []

    def test_empty_braces_ignored(self):
        assert path_parameters("/books/{}") == []

    def test_unclosed_brace_ignored(self):
        assert path_parameters("/books/{bookId") == []
