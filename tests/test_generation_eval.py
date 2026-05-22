"""Tests for Sample Generation internals: gap regex, identifier, evaluation."""

import pytest
from helpers import base_spec, parsed

from artie.checks.generation_quality import (
    GAP_MARKER_PATTERN,
    _build_identifier,
    _evaluate,
    _extract_code,
)

GOOD_CODE = """\
import requests


def get_book(book_id: str) -> dict:
    try:
        response = requests.get(f"https://api.example.com/books/{book_id}")
        response.raise_for_status()
    except requests.RequestException:
        raise
    return response.json()
"""


class TestGapMarkerRegex:
    @pytest.mark.parametrize(
        "comment",
        [
            "# the docs don't specify the base URL",
            "# documentation doesn't describe the auth header",
            "# not specified in the documentation",
            "# value not provided by the docs",
            "# using a placeholder here",
            "# unclear from the docs which field this is",
            "# header name assumed from convention",
            "# the response shape is not clear",
        ],
    )
    def test_matches_gap_comments(self, comment):
        assert GAP_MARKER_PATTERN.search(comment)

    @pytest.mark.parametrize(
        "text",
        [
            "x = 1  # a perfectly ordinary comment",
            "# this comment praises the docs",
            'url = "the docs dont mention this"',  # in a string, not a comment
            "response = requests.get(url)",
        ],
    )
    def test_ignores_non_gap_text(self, text):
        assert not GAP_MARKER_PATTERN.search(text)

    def test_counts_multiple_markers(self):
        code = (
            "# docs don't say the URL\n"
            "x = 1\n"
            "# header name not specified\n"
        )
        assert len(GAP_MARKER_PATTERN.findall(code)) == 2


class TestBuildIdentifier:
    def test_url_source(self):
        ident = _build_identifier(None, "https://api.example.com/openapi.yaml")
        assert "URL: https://api.example.com/openapi.yaml" in ident

    def test_file_source(self):
        ident = _build_identifier(None, "./local/openapi.yaml")
        assert "File: ./local/openapi.yaml" in ident

    def test_title_from_parsed_spec(self):
        docs = parsed(base_spec(info={"title": "Book Club API"}))
        ident = _build_identifier(docs, "openapi.yaml")
        assert "Title: Book Club API" in ident

    def test_missing_title_is_explicit(self):
        docs = parsed({"openapi": "3.0.0", "info": {}, "paths": {}})
        ident = _build_identifier(docs, "openapi.yaml")
        assert "Title: (not available)" in ident

    def test_handles_none_parsed(self):
        ident = _build_identifier(None, "openapi.yaml")
        assert "Title: (not available)" in ident


class TestEvaluate:
    def test_good_code_meets_all_criteria(self):
        result = _evaluate(GOOD_CODE)
        assert result["criteria_met"] == 5
        assert all(result["criteria"].values())
        assert result["gap_count"] == 0
        assert result["structural_score"] == 10

    def test_invalid_python_fails_parse(self):
        result = _evaluate("def broken(:\n    pass")
        assert not result["criteria"]["parses_as_python"]

    def test_code_without_http_client(self):
        result = _evaluate("def add(a: int, b: int) -> int:\n    return a + b")
        assert result["criteria"]["parses_as_python"]
        assert not result["criteria"]["imports_http_client"]
        assert not result["criteria"]["constructs_request"]

    def test_gap_markers_lower_structural_score(self):
        code = (
            "import requests\n\n"
            "def f() -> dict:\n"
            "    # the docs don't specify the base URL\n"
            '    url = "PLACEHOLDER"\n'
            "    return requests.get(url).json()\n"
        )
        result = _evaluate(code)
        assert result["gap_count"] == 1
        # 4 criteria met (no error handling) -> 8, minus 1 gap -> 7
        assert result["criteria_met"] == 4
        assert result["structural_score"] == 7

    def test_structural_score_floored_at_zero(self):
        code = "# docs don't say\n# not specified\n# not provided\nx = 1\n"
        result = _evaluate(code)
        assert result["structural_score"] == 0

    def test_httpx_counts_as_http_client(self):
        result = _evaluate("import httpx\n\nx = httpx.get('http://a')\n")
        assert result["criteria"]["imports_http_client"]


class TestExtractCode:
    def test_python_fenced_block(self):
        text = "Here you go:\n```python\nimport requests\n```\nDone."
        assert _extract_code(text) == "import requests"

    def test_unlabeled_fenced_block(self):
        assert _extract_code("```\ndef f():\n    pass\n```") == "def f():\n    pass"

    def test_unfenced_code_fallback(self):
        assert _extract_code("import requests\nx = 1") == "import requests\nx = 1"

    def test_prose_returns_none(self):
        assert _extract_code("I cannot write code from these docs.") is None
