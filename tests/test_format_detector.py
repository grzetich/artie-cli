"""Tests for the documentation format detector."""

from pathlib import Path

import pytest

from artie.parsers import detect_format
from artie.parsers import _looks_like_openapi, _looks_like_yaml

OPENAPI_YAML = "openapi: 3.0.0\ninfo:\n  title: X\npaths: {}\n"
OPENAPI_JSON = '{"openapi": "3.0.0", "info": {"title": "X"}, "paths": {}}'
PLAIN_JSON = '{"name": "thing", "value": 1}'
PLAIN_YAML = "name: thing\nvalue: 1\nother: 2\n"
HTML_DOC = "<!DOCTYPE html>\n<html><body>hi</body></html>"
MARKDOWN_DOC = "# Title\n\nSome prose about an API.\n"


class TestDetectFormat:
    def test_openapi_yaml_by_content(self):
        assert detect_format(OPENAPI_YAML) == "openapi-yaml"

    def test_openapi_json_by_content(self):
        assert detect_format(OPENAPI_JSON) == "openapi-json"

    def test_plain_json(self):
        assert detect_format(PLAIN_JSON) == "json"

    def test_plain_yaml(self):
        assert detect_format(PLAIN_YAML) == "yaml"

    def test_html_by_doctype(self):
        assert detect_format(HTML_DOC) == "html"

    def test_markdown_by_heading_fallback(self):
        assert detect_format(MARKDOWN_DOC) == "markdown"

    def test_unknown_for_unmarked_text(self):
        assert detect_format("just some words with no structure") == "unknown"

    def test_extension_overrides_to_markdown(self):
        # Content has no markdown markers, but the .md suffix wins.
        assert detect_format("plain text", path=Path("doc.md")) == "markdown"

    def test_json_extension_with_openapi_content(self):
        assert (
            detect_format(OPENAPI_JSON, path=Path("api.json")) == "openapi-json"
        )

    def test_yaml_extension_without_openapi_markers(self):
        assert detect_format(PLAIN_YAML, path=Path("data.yaml")) == "yaml"

    def test_hint_yaml_with_openapi_content(self):
        assert detect_format(OPENAPI_YAML, hint="yaml") == "openapi-yaml"

    def test_hint_html(self):
        assert detect_format("<html>", hint="html") == "html"

    def test_hint_markdown(self):
        assert detect_format("anything", hint="markdown") == "markdown"

    def test_hint_json_plain(self):
        assert detect_format(PLAIN_JSON, hint="json") == "json"

    def test_swagger_2_detected_as_openapi(self):
        # The detector treats `swagger:` the same as `openapi:`.
        assert detect_format("swagger: '2.0'\npaths: {}\n") == "openapi-yaml"

    @pytest.mark.parametrize(
        "content,expected",
        [
            (OPENAPI_YAML, "openapi-yaml"),
            (OPENAPI_JSON, "openapi-json"),
            (PLAIN_JSON, "json"),
            (HTML_DOC, "html"),
        ],
    )
    def test_table(self, content, expected):
        assert detect_format(content) == expected


class TestLooksLikeOpenAPI:
    def test_yaml_marker(self):
        assert _looks_like_openapi("openapi: 3.0.0")

    def test_json_marker(self):
        assert _looks_like_openapi('{"openapi": "3.0.0"}')

    def test_swagger_marker(self):
        assert _looks_like_openapi("swagger: '2.0'")

    def test_no_marker(self):
        assert not _looks_like_openapi("name: thing\nvalue: 1")

    def test_marker_must_be_near_the_top(self):
        # The check only scans the first 2000 characters.
        buried = "x: 1\n" * 600 + "openapi: 3.0.0"
        assert not _looks_like_openapi(buried)


class TestLooksLikeYAML:
    def test_keyvalue_pairs(self):
        assert _looks_like_yaml("name: thing\nvalue: 1\n")

    def test_single_pair_is_not_enough(self):
        assert not _looks_like_yaml("name: thing\n")

    def test_comment_and_indented_lines_ignored(self):
        assert not _looks_like_yaml("# comment\n  indented: x\n- item: y\n")
