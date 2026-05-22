# Contributing

## Development setup

```bash
git clone https://github.com/grzetich/artie-cli
cd artie-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
artie check examples/bookclub-openapi.yaml --no-generation
```

If you want to exercise the Generation Quality check, export an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
artie check examples/bookclub-openapi.yaml
```

Read `ARCHITECTURE.md` before touching the code. It explains the request flow, the check protocol, and the design decisions that constrain implementation choices.

## Running examples

Three samples live in `examples/`:

- `bookclub-openapi.yaml` is the gold standard. Every check should score 10/10 against it. If a change makes it score lower, the change is suspect.
- `sample-openapi.yaml` is a minimal spec. Endpoint Completeness scores well, Example Coverage and Auth Clarity do not. Useful for checking middle-of-the-road behavior.
- `broken-openapi.yaml` is deliberately bad. Most checks score zero or near zero, with named operations and properties in the recommendations. Useful for verifying that low scores produce actionable findings.

Run each before and after any scoring change to make sure the change does what you expect.

## Writing a new check

Subclass `BaseCheck`, implement `run`, register in `checks/__init__.py`.

```python
from typing import Any

from artie.checks.base import BaseCheck, CheckResult
from artie.parsers.types import ParsedDocs


class MyNewCheck(BaseCheck):
    name = "My New Check"
    description = "What this check measures."

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not isinstance(parsed, ParsedDocs) or not parsed.is_openapi:
            return self.not_evaluable("This check needs a parsed OpenAPI spec.")

        # Compute the score on a 0-10 scale.
        score = self._compute(parsed)
        severity = self.severity_for(score)

        return CheckResult(
            name=self.name,
            description=self.description,
            score=score,
            max_score=self.max_score,
            severity=severity,
            findings=["What we observed."],
            recommendations=["What to do about it."],
            metadata={"raw_data": "for JSON consumers"},
        )

    def _compute(self, parsed: ParsedDocs) -> int:
        ...
```

Then add it to `ALL_CHECKS` in `checks/__init__.py`. Order matters because it determines display order in the report.

Things to honor in your check:

- Return `not_evaluable` when the check cannot honestly score the input. Do not return a fake zero or a fake ten just to have a number on the report.
- Use `self.severity_for(score)` to map the score to a severity bucket. Do not invent your own mapping.
- Findings are observations. Recommendations are advice. Keep them distinct.
- Findings should be specific to the input being scored. "5 of 14 endpoints" beats "many endpoints." When pointing at specific problems, name the operations or properties (up to about five examples, truncated with an ellipsis).
- Metadata is for machine consumers. Put structured data there instead of synthesizing it from finding strings.

## Style notes

Write the way the existing code reads. Concrete observations, named items, no hedging. Avoid these:

- Em or en dashes. Use a comma or split the sentence.
- "Leverage," "seamless," "robust," "fundamentally," "paradigm," "ecosystem" as metaphor, and the rest of the AI-tells list.
- Guided-tour phrasings like "Let's look at." Just look at it.
- Long bolded thesis sentences that summarize a paragraph. Let the paragraph carry its own weight.
- Sentences clustered on "This." More than two in a row signals laziness.

For docstrings, one sentence is usually enough. Longer when the function does something non-obvious. Module docstrings should explain why the module exists and what it produces, not narrate every function.

## Scoring conventions

Scores are 0-10 integers. The mapping to severity, in `BaseCheck.severity_for`:

- 9-10: excellent
- 7-8: good
- 4-6: needs work
- 0-3: poor
- None: not evaluable

If you find yourself wanting a different bucket size or a different scale, that is a sign to add a new check rather than redefine the scale. The convention is shared across all checks so users can read across them.

When a check has multiple sub-signals, average them and scale the result to 0-10. When sub-signals do not apply (no path parameters, no request bodies), drop them from the average rather than scoring them zero.

Document threshold choices in code comments at the top of the check. Future calibration work needs to know what each threshold currently corresponds to.

## Tests

Tests live under `tests/` (forthcoming). Use pytest. Cover at minimum:

- Each check's scoring math, including the edge cases for not-evaluable.
- The format detector across all supported formats.
- The OpenAPI parser including embedded extraction from markdown.
- The fetcher's content-type hint logic without making real network calls.
- The generator's retry behavior using mocked HTTP responses.

Run with `pytest`. CI should run the suite on every push.

## Versioning

Bump the version in `pyproject.toml` and `src/artie/__init__.py` together. They must match. Use semver. A change to the scoring rubric is a minor version bump because it changes user-visible behavior even when code APIs do not change.

Track the scoring rubric version separately when it diverges from the package version. Include it in JSON output so downstream tooling can pin against it.

## Pull requests

Keep them focused. One check, one bug fix, one CI feature per PR. If you find yourself wanting to do unrelated cleanups, open a separate PR for those.

Run the three example specs before and after your change. Include the diff in the PR description when scores change. If a sample's score moves, explain why the new score is more correct than the old one.
