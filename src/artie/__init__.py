"""artie-cli: Score your API documentation for AI-readiness."""

__version__ = "0.7.0"

# Version of the scoring rubric: the thresholds, buckets, and weightings that
# turn documentation into scores. Bump this whenever any of those change, so
# JSON consumers can tell whether two runs are comparable. This is the runtime
# source of truth; pyproject.toml [tool.artie] mirrors it for packaging tools,
# and tests/test_scoring_version.py asserts the two stay in sync.
# See docs/scoring.md for the full rubric.
SCORING_VERSION = "1.0"
