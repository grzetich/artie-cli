"""Tests pinning the generation prompt's provenance contract.

The Generation Quality check subtracts a point per "gap marker" comment in the
generated code, and reports those comments as evidence of documentation gaps.
That reading is only honest because we know how the comments were produced:
the prompt asks for them.

These tests fail if that instruction is edited or removed, so the caveat in
the module docstring and in the report cannot drift away from what the prompt
actually says.
"""

import re

from artie.checks.generation_quality import (
    BASELINE_PROMPT_TEMPLATE,
    GAP_MARKER_PATTERN,
    PROMPT_TEMPLATE,
    _evaluate,
)


class TestPromptElicitsGapComments:
    def test_prompt_asks_for_inline_gap_comments(self):
        # The provenance claim rests on this instruction existing.
        assert "inline code comment" in PROMPT_TEMPLATE
        assert "which detail the docs do not provide" in PROMPT_TEMPLATE

    def test_prompt_forbids_relying_on_prior_knowledge(self):
        # The other half of the contract: markers mean "absent from these
        # docs", not "absent from the model's knowledge".
        assert "only information explicitly present" in PROMPT_TEMPLATE

    def test_baseline_prompt_also_invites_comments(self):
        # Both arms of the differential elicit comments, so a gap-count
        # comparison between them is directional, not absolute.
        assert "inline code comments" in BASELINE_PROMPT_TEMPLATE
        assert "guessing" in BASELINE_PROMPT_TEMPLATE

    def test_docstring_records_that_markers_are_elicited(self):
        import artie.checks.generation_quality as module

        assert "elicited" in module.__doc__


class TestGapMarkerAccounting:
    CODE = '''
import requests

def call() -> dict:
    # The docs do not specify the auth header name; using a placeholder.
    resp = requests.get("https://x.test", headers={"Authorization": "TOKEN"})
    resp.raise_for_status()
    return resp.json()
'''

    def test_marker_pattern_matches_a_gap_comment(self):
        assert GAP_MARKER_PATTERN.search("# not specified in the docs")
        assert GAP_MARKER_PATTERN.search("# placeholder value")

    def test_marker_pattern_ignores_ordinary_comments(self):
        assert not GAP_MARKER_PATTERN.search("# build the request")

    def test_gap_markers_reduce_the_score(self):
        result = _evaluate(self.CODE)
        assert result["gap_count"] >= 1
        assert result["score"] < result["raw_score"]

    def test_metadata_marks_gap_markers_as_elicited(self):
        # Downstream consumers need this to caveat the count correctly.
        assert _evaluate(self.CODE)["gap_markers_elicited"] is True

    def test_clean_code_has_no_gap_penalty(self):
        clean = re.sub(r"^\s*#.*$", "", self.CODE, flags=re.MULTILINE)
        result = _evaluate(clean)
        assert result["gap_count"] == 0
        assert result["score"] == result["raw_score"]
