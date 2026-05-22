"""Sample Generation check.

The empirical companion to artie's static checks: ask an AI model to write
code from these docs, then show what it produced. This is the same
methodology as Tokens Not Jokin', applied per-spec instead of across a
research corpus.

This check is deliberately *not scored*. The generated code is the
deliverable — read it and judge whether it looks like working code against
your API. The five structural observations below are reported as commentary,
not summed into a 0-10 grade:

1. Parses as valid Python.
2. Imports an HTTP client library (requests, httpx, urllib.request, aiohttp).
3. Includes error handling (try/except, raise_for_status, status checks).
4. Constructs an HTTP request.
5. Handles the response (status check, body parsing, return of parsed result).

Why no score: a single generation against a single model is a sample, not a
measurement. The model's training-data familiarity with the API confounds it
(see the differential-mode contamination warning). The static checks tell you
what to fix; this check shows you a concrete example of what an agent writes.

The check is opt-in: pass --with-generation (or --differential) to run it.
"""

import ast
import re
from typing import Any

from rich.console import Console

from artie.checks.base import BaseCheck, CheckResult, Severity
from artie.generator import (
    DEFAULT_MODEL,
    GenerationError,
    GenerationResult,
    MissingAPIKeyError,
    generate,
    has_api_key,
)


# Cap on the docs payload sent to the model. Most docs pages fit easily;
# very large specs get truncated with a marker so the model knows.
MAX_DOCS_CHARS = 60_000

# In differential mode, a baseline (no-docs) run whose structural strength
# reaches this internal threshold means the model already knows the API well
# enough that the docs-informed run says little about the docs. Expressed on
# the legacy 0-10 structural scale (5 criteria x 2, minus gap markers); kept
# internal purely to drive the contamination warning.
CONTAMINATION_THRESHOLD = 7

PROMPT_TEMPLATE = """\
You are evaluating API documentation by attempting to use it.

Below is API documentation. Read it carefully and write a single Python \
function that calls the most representative endpoint from this API.

Critical constraint: use only information explicitly present in the \
documentation below. Do not draw on your general knowledge of similar APIs, \
related products, well-known authentication patterns, or common library \
conventions. If a detail you need is not in the documentation (URL format, \
header names, request body structure, authentication mechanism, parameter \
names, response shapes), write an inline code comment that says exactly \
which detail the docs do not provide, and either use a clearly-labeled \
placeholder or omit that section. This is a test of the documentation, \
not a test of your prior training.

Other requirements:
- Use the `requests` library
- Include type hints
- Handle errors appropriately
- Return the parsed response

Do not write a full SDK, just one function for one endpoint. Choose the \
endpoint that best demonstrates how to use this API.

Return ONLY the Python code inside a single ```python code block. No \
commentary before or after the code block.

API documentation:
---
{content}
---
"""

# Baseline prompt for differential mode: same task, but the model gets only
# the API identifier and no documentation content. What the model produces
# here is what it could write from training alone — useful for spotting when
# the docs-informed run is contaminated by training-data familiarity.
BASELINE_PROMPT_TEMPLATE = """\
You are writing client code for an API. Below is the API's identifier. \
Write a single Python function that calls the most representative endpoint \
of this API.

Use only your prior knowledge of this API. Do not invent endpoints, \
parameters, or behaviors that you are not confident exist. If you are not \
familiar with this API, write your best guess of what an API at this URL \
might look like and add inline code comments explaining what you are \
guessing.

Requirements:
- Use the `requests` library
- Include type hints
- Handle errors appropriately
- Return the parsed response

Return ONLY the Python code inside a single ```python code block. No \
commentary before or after the code block.

API identifier:
{identifier}
"""

CODE_BLOCK_PATTERN = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

# Patterns the model uses (under our constrained prompt) to flag details
# the documentation didn't provide. Each marker found in the generated code
# is evidence of a real gap in the docs.
GAP_MARKER_PATTERN = re.compile(
    r"#[^\n]*?\b("
    r"docs?\s+don'?t|"
    r"documentation\s+(?:doesn'?t|does\s+not)|"
    r"not\s+(?:specified|provided|stated|documented|in\s+the\s+docs?|"
    r"in\s+the\s+documentation)|"
    r"placeholder|"
    r"unclear\s+from|"
    r"assumed\s+from|"
    r"not\s+clear"
    r")\b",
    re.IGNORECASE,
)

# Human-readable labels for the five structural observations.
CRITERIA_LABELS = {
    "parses_as_python": "Parses as valid Python",
    "imports_http_client": "Imports an HTTP client (requests, httpx, urllib, aiohttp)",
    "handles_errors": "Includes error handling (try/except or status checks)",
    "constructs_request": "Constructs an HTTP request",
    "handles_response": "Handles the response body or status",
}


class SampleGenerationCheck(BaseCheck):
    name = "Sample Generation"
    description = (
        "An AI model is given these docs and asked to write a Python function "
        "that calls the API. The generated code is the deliverable; this check "
        "presents it and comments on its structure but assigns no score."
    )

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        enabled: bool = False,
        differential: bool = False,
        source: str = "",
        console: Console | None = None,
    ) -> None:
        self.model = model
        self.enabled = enabled
        self.differential = differential
        self.source = source
        self.console = console

    def _generate_with_status(
        self, prompt: str, status_label: str
    ) -> GenerationResult:
        """Call generate() with a spinner when a console is available."""
        if self.console is None:
            return generate(prompt, model=self.model)
        with self.console.status(status_label, spinner="dots"):
            return generate(prompt, model=self.model)

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        if not self.enabled:
            return self.not_evaluable(
                "Sample Generation did not run. Pass --with-generation to "
                "have a model write code from these docs (uses the Anthropic "
                "API; one call, or two with --differential)."
            )

        if not has_api_key():
            return self.not_evaluable(
                "ANTHROPIC_API_KEY is not set. Export it to enable the "
                "Sample Generation check."
            )

        if len(content.strip()) < 100:
            return self.not_evaluable(
                "Content is too short to generate meaningful code from."
            )

        # Informed run: full docs in the prompt.
        prompt_content = content
        truncated = False
        if len(prompt_content) > MAX_DOCS_CHARS:
            prompt_content = (
                prompt_content[:MAX_DOCS_CHARS]
                + "\n\n[...truncated by artie-cli for length...]"
            )
            truncated = True

        try:
            informed_result = self._generate_with_status(
                PROMPT_TEMPLATE.format(content=prompt_content),
                status_label="Generating code from the docs...",
            )
        except MissingAPIKeyError as exc:
            return self.not_evaluable(str(exc))
        except GenerationError as exc:
            return _generation_error_result(self, exc)

        informed_code = _extract_code(informed_result.text)
        if not informed_code:
            return _no_code_result(self, informed_result)

        informed_eval = _evaluate(informed_code)

        # If not in differential mode, return the informed result as-is.
        if not self.differential:
            return _build_result(
                self,
                code=informed_code,
                informed_result=informed_result,
                informed_eval=informed_eval,
                truncated=truncated,
            )

        # Differential mode: second call with no docs body.
        identifier = _build_identifier(parsed, self.source)
        try:
            baseline_result = self._generate_with_status(
                BASELINE_PROMPT_TEMPLATE.format(identifier=identifier),
                status_label="Generating baseline code without docs...",
            )
        except GenerationError as exc:
            # Baseline failed but we have an informed result; return informed
            # with a note that differential comparison was unavailable.
            informed_eval["commentary"].append(
                f"⚠ Differential baseline call failed: {exc}. "
                "Reporting the docs-informed sample without comparison."
            )
            return _build_result(
                self,
                code=informed_code,
                informed_result=informed_result,
                informed_eval=informed_eval,
                truncated=truncated,
            )

        baseline_code = _extract_code(baseline_result.text)
        if not baseline_code:
            # Model declined to guess: no training knowledge of this API.
            baseline_eval = {
                "criteria": {},
                "criteria_met": 0,
                "gap_count": 0,
                "structural_score": 0,
                "line_count": 0,
                "commentary": [],
                "recommendations": [],
            }
        else:
            baseline_eval = _evaluate(baseline_code)

        return _build_result(
            self,
            code=informed_code,
            informed_result=informed_result,
            informed_eval=informed_eval,
            truncated=truncated,
            baseline_result=baseline_result,
            baseline_eval=baseline_eval,
            baseline_code=baseline_code,
            identifier=identifier,
        )


def _build_identifier(parsed: Any, source: str) -> str:
    """Build the baseline-prompt identifier for an API.

    We give the model whatever public-facing handles it would normally have
    seen during training: URL, API title, and filename if local. We do NOT
    include any of the docs content itself.
    """
    lines: list[str] = []
    if source:
        if source.startswith(("http://", "https://")):
            lines.append(f"URL: {source}")
        else:
            lines.append(f"File: {source}")

    title = None
    if hasattr(parsed, "raw") and isinstance(parsed.raw, dict):
        info = parsed.raw.get("info")
        if isinstance(info, dict):
            title = info.get("title")
    if title:
        lines.append(f"Title: {title}")
    else:
        lines.append("Title: (not available)")

    return "\n".join(lines)


def _informational(
    check: "SampleGenerationCheck",
    findings: list[str],
    recommendations: list[str],
    metadata: dict[str, Any],
) -> CheckResult:
    """Build an informational (unscored) CheckResult for Sample Generation."""
    return CheckResult(
        name=check.name,
        description=check.description,
        score=None,
        max_score=check.max_score,
        severity=Severity.NOT_EVALUABLE,
        findings=findings,
        recommendations=recommendations,
        metadata=metadata,
        informational=True,
    )


def _generation_error_result(
    check: "SampleGenerationCheck", exc: Exception
) -> CheckResult:
    """The generation call failed outright — there is no sample to show."""
    return CheckResult(
        name=check.name,
        description=check.description,
        score=None,
        max_score=check.max_score,
        severity=Severity.NOT_EVALUABLE,
        findings=[f"Sample generation could not run: {exc}"],
        recommendations=[
            "If this is a temporary overload (HTTP 529 or 429), wait a few "
            "minutes and try again. For other errors, check ANTHROPIC_API_KEY "
            "and your network, or omit --with-generation to skip this check."
        ],
        metadata={"error": str(exc)},
    )


def _no_code_result(
    check: "SampleGenerationCheck", result: "GenerationResult"
) -> CheckResult:
    """The model replied but produced no code block — nothing to present."""
    return CheckResult(
        name=check.name,
        description=check.description,
        score=None,
        max_score=check.max_score,
        severity=Severity.NOT_EVALUABLE,
        findings=[
            "The model returned a response but no Python code block. "
            "This usually means the documentation didn't contain enough "
            "information for the model to attempt code.",
            f"Model response preview: {result.text[:200]}",
        ],
        recommendations=[
            "Add concrete endpoint information, request and response shapes, "
            "and at least one example to the documentation."
        ],
        metadata={
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "raw_response": result.text,
        },
    )


def _build_result(
    check: "SampleGenerationCheck",
    code: str,
    informed_result: "GenerationResult",
    informed_eval: dict[str, Any],
    truncated: bool,
    baseline_result: "GenerationResult | None" = None,
    baseline_eval: dict[str, Any] | None = None,
    baseline_code: str | None = None,
    identifier: str | None = None,
) -> CheckResult:
    """Build the informational CheckResult, with differential context if any."""
    findings = [
        f"Model: {informed_result.model}",
        f"Tokens: {informed_result.input_tokens:,} input, "
        f"{informed_result.output_tokens:,} output",
        f"Generated {informed_eval['line_count']} lines of Python from "
        f"your documentation.",
    ]
    if truncated:
        findings.append(
            f"Docs were truncated to {MAX_DOCS_CHARS:,} characters before "
            f"generation."
        )

    findings.append("")
    findings.append("What the generated code contains (commentary, not a score):")
    findings.extend(informed_eval["commentary"])

    recommendations = list(informed_eval["recommendations"])
    metadata: dict[str, Any] = {
        "model": informed_result.model,
        "input_tokens": informed_result.input_tokens,
        "output_tokens": informed_result.output_tokens,
        "stop_reason": informed_result.stop_reason,
        "code": code,
        "criteria": informed_eval["criteria"],
        "criteria_met": informed_eval["criteria_met"],
        "gap_count": informed_eval.get("gap_count", 0),
        "docs_truncated": truncated,
    }

    if baseline_eval is not None:
        baseline_met = baseline_eval["criteria_met"]
        informed_met = informed_eval["criteria_met"]
        contaminated = (
            baseline_eval.get("structural_score", 0) >= CONTAMINATION_THRESHOLD
        )

        if contaminated:
            # The contamination warning is the headline of a differential run:
            # it tells the reader the comparison below is not about the docs.
            findings.insert(
                0,
                "⚠ Contamination warning: this model has training-data "
                "familiarity with this API. The generated code primarily "
                "reflects model capability, not docs quality.",
            )

        findings.extend([
            "",
            "Differential comparison (does the model already know this API?):",
            f"  Without your docs, the model's code met {baseline_met} of 5 "
            f"structural criteria.",
            f"  With your docs, the generated code met {informed_met} of 5.",
        ])
        if contaminated:
            findings.append(
                "  Because the baseline is already strong, treat the "
                "docs-informed sample as a capability demo, not a docs grade. "
                "Differential mode is most informative for internal or novel "
                "APIs the model has not seen."
            )
        elif informed_met <= baseline_met:
            recommendations.append(
                "The docs added little structural signal beyond what the "
                "model already knew. If the baseline sample is also weak, "
                "the docs are not providing enough structured information "
                "for code generation."
            )

        metadata["baseline_criteria"] = baseline_eval["criteria"]
        metadata["baseline_criteria_met"] = baseline_met
        metadata["contamination_warning"] = contaminated
        metadata["identifier"] = identifier
        if baseline_code:
            metadata["baseline_code"] = baseline_code
        if baseline_result:
            metadata["baseline_input_tokens"] = baseline_result.input_tokens
            metadata["baseline_output_tokens"] = baseline_result.output_tokens

    return _informational(check, findings, recommendations, metadata)


def _extract_code(text: str) -> str | None:
    """Pull the first Python code block from the model's response."""
    match = CODE_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    # Fall back: if the entire response looks like code without fences.
    stripped = text.strip()
    if stripped.startswith(("import ", "from ", "def ", "async def ", "class ")):
        return stripped
    return None


def _evaluate(code: str) -> dict[str, Any]:
    """Inspect generated code on five structural criteria.

    Returns the raw observations plus human-readable commentary. The
    `structural_score` is a legacy 0-10 figure kept only to drive the
    differential contamination warning; it is never surfaced as a grade.
    """
    criteria = {
        "parses_as_python": False,
        "imports_http_client": False,
        "handles_errors": False,
        "constructs_request": False,
        "handles_response": False,
    }

    try:
        ast.parse(code)
        criteria["parses_as_python"] = True
    except SyntaxError:
        pass

    lower_code = code.lower()
    line_count = code.count("\n") + 1

    if any(
        token in code
        for token in (
            "import requests",
            "from requests",
            "import httpx",
            "from httpx",
            "import aiohttp",
            "from aiohttp",
            "from urllib",
            "import urllib",
        )
    ):
        criteria["imports_http_client"] = True

    if (
        "try:" in code
        or "except" in code
        or "raise_for_status" in code
        or re.search(r"\.status_code\s*[!=<>]=", code)
        or "response.ok" in lower_code
    ):
        criteria["handles_errors"] = True

    if re.search(
        r"\b(requests|httpx|client|session)\.(get|post|put|patch|delete|head|options|request)\b",
        code,
    ) or "urlopen(" in code:
        criteria["constructs_request"] = True

    if (
        ".json()" in code
        or ".text" in code
        or "json.loads" in code
        or "status_code" in code
        or "raise_for_status" in code
    ):
        criteria["handles_response"] = True

    criteria_met = sum(1 for passed in criteria.values() if passed)

    # Count gap markers: each is a detail the model says the docs didn't
    # provide and had to work around. Pure commentary, not a deduction.
    gap_count = len(GAP_MARKER_PATTERN.findall(code))

    # Legacy structural score, internal only (see CONTAMINATION_THRESHOLD).
    structural_score = max(0, criteria_met * 2 - gap_count)

    commentary: list[str] = []
    for key, passed in criteria.items():
        marker = "✓" if passed else "✗"
        commentary.append(f"{marker} {CRITERIA_LABELS[key]}")
    if gap_count:
        commentary.append(
            f"⚠ Model flagged {gap_count} documentation gap"
            f"{'s' if gap_count != 1 else ''} as inline code comments."
        )

    recommendations: list[str] = []
    if gap_count:
        recommendations.append(
            "The model flagged details the docs did not provide and worked "
            "around them with placeholders or guesses. The exact gaps appear "
            "as comments in the generated code; fix those in the source docs."
        )
    if not criteria["parses_as_python"]:
        recommendations.append(
            "The model produced syntactically invalid Python. This usually "
            "means the docs lacked enough structure (URLs, methods, parameter "
            "names) for the model to compose a coherent function. Add a "
            "complete code example or an OpenAPI spec."
        )
    if not criteria["handles_errors"]:
        recommendations.append(
            "The generated code has no error handling. The TNJ Chapter 5 "
            "finding (DON's 98.2% try/except adoption rate) showed this "
            "comes from documenting error responses with descriptions and "
            "schemas. Add 4xx/5xx documentation."
        )
    if not criteria["imports_http_client"]:
        recommendations.append(
            "The generated code doesn't use a standard HTTP client. This "
            "usually means the docs didn't make the HTTP nature of the API "
            "clear. Show full URLs, methods, and headers in your examples."
        )

    return {
        "criteria": criteria,
        "criteria_met": criteria_met,
        "commentary": commentary,
        "recommendations": recommendations,
        "line_count": line_count,
        "gap_count": gap_count,
        "structural_score": structural_score,
    }
