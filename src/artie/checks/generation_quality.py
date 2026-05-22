"""Generation Quality check.

The empirical heart of artie: ask an AI model to write code from these docs,
then evaluate what it produced. This is the same methodology as Tokens Not
Jokin', applied per-spec instead of across a research corpus.

Five sub-criteria, each worth 2 points:

1. Parses as valid Python. If the model couldn't produce parseable code from
   these docs, that is itself a low score.
2. Imports an HTTP client library (requests, httpx, urllib.request, or aiohttp).
3. Includes error handling (try/except, raise_for_status, status code checks).
4. Constructs an HTTP request (any verb method on the client).
5. Handles the response (status check, body parsing, or return of parsed result).

The generated code is included in the check's findings so users can see what
the model actually wrote from their docs. That's the value an empirical check
delivers that no rule-based check ever could.
"""

import ast
import re
from typing import Any

from rich.console import Console

from artie.checks.base import BaseCheck, CheckResult
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
# the API identifier and no documentation content. The score from this run
# is what the model could produce from training alone. The delta between
# the informed run and this run measures what the documentation actually
# contributed.
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


class GenerationQualityCheck(BaseCheck):
    name = "Generation Quality"
    description = (
        "An AI model is given these docs and asked to write a Python function "
        "that calls the API. The check scores what it produced."
    )

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        enabled: bool = True,
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
                "Generation Quality is disabled. Remove --no-generation to enable."
            )

        if not has_api_key():
            return self.not_evaluable(
                "ANTHROPIC_API_KEY is not set. Export it to enable the "
                "empirical Generation Quality check."
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
            # with a note that differential measurement was unavailable.
            informed_eval.setdefault("findings", []).append(
                f"⚠ Differential baseline call failed: {exc}. "
                "Reporting informed score without delta."
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
            # Model declined to guess. Treat baseline as 0/10 (no training
            # knowledge of this API), so the informed score is entirely from
            # the docs.
            baseline_eval = {
                "score": 0,
                "criteria": {},
                "gap_count": 0,
                "raw_score": 0,
                "line_count": 0,
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


def _generation_error_result(check: "GenerationQualityCheck", exc: Exception) -> CheckResult:
    return CheckResult(
        name=check.name,
        description=check.description,
        score=0,
        max_score=check.max_score,
        severity=check.severity_for(0),
        findings=[f"Generation failed: {exc}"],
        recommendations=[
            "If this is a temporary overload (HTTP 529 or 429), wait a few "
            "minutes and try again. For other errors, check ANTHROPIC_API_KEY "
            "and your network. Use --no-generation to skip this check entirely."
        ],
        metadata={"error": str(exc)},
    )


def _no_code_result(
    check: "GenerationQualityCheck", result: "GenerationResult"
) -> CheckResult:
    return CheckResult(
        name=check.name,
        description=check.description,
        score=0,
        max_score=check.max_score,
        severity=check.severity_for(0),
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
    check: "GenerationQualityCheck",
    code: str,
    informed_result: "GenerationResult",
    informed_eval: dict[str, Any],
    truncated: bool,
    baseline_result: "GenerationResult | None" = None,
    baseline_eval: dict[str, Any] | None = None,
    baseline_code: str | None = None,
    identifier: str | None = None,
) -> CheckResult:
    """Build the final CheckResult, with differential context if available."""
    score = informed_eval["score"]
    severity = check.severity_for(score)

    findings = [
        f"Model: {informed_result.model}",
        f"Tokens: {informed_result.input_tokens:,} input, "
        f"{informed_result.output_tokens:,} output",
        f"Generated {informed_eval['line_count']} lines of Python",
        *informed_eval["findings"],
    ]
    if truncated:
        findings.insert(
            0,
            f"Docs were truncated to {MAX_DOCS_CHARS:,} characters before generation.",
        )

    recommendations = list(informed_eval["recommendations"])
    metadata: dict[str, Any] = {
        "model": informed_result.model,
        "input_tokens": informed_result.input_tokens,
        "output_tokens": informed_result.output_tokens,
        "stop_reason": informed_result.stop_reason,
        "code": code,
        "criteria": informed_eval["criteria"],
        "gap_count": informed_eval.get("gap_count", 0),
        "raw_score": informed_eval.get("raw_score", score),
        "docs_truncated": truncated,
    }

    if baseline_eval is not None:
        baseline_score = baseline_eval["score"]
        delta = score - baseline_score
        findings.extend([
            "",
            "Differential measurement:",
            f"  Baseline (training-only) score: {baseline_score}/10",
            f"  Informed (with docs) score: {score}/10",
            f"  Docs contribution: {delta:+d} points",
        ])
        if baseline_score >= 7:
            recommendations.append(
                "The baseline score is high, which means the model already "
                "knows this API well from training. The informed score "
                "primarily reflects model capability, not docs quality. "
                "This measurement is most reliable for internal or novel "
                "APIs the model has not seen."
            )
        elif delta <= 1:
            recommendations.append(
                "The docs added little measurable signal beyond what the "
                "model already knew. If the baseline score is low, this "
                "suggests the docs are not providing enough structured "
                "information for code generation."
            )
        metadata["baseline_score"] = baseline_score
        metadata["baseline_raw_score"] = baseline_eval.get("raw_score", baseline_score)
        metadata["delta"] = delta
        metadata["identifier"] = identifier
        if baseline_code:
            metadata["baseline_code"] = baseline_code
        if baseline_result:
            metadata["baseline_input_tokens"] = baseline_result.input_tokens
            metadata["baseline_output_tokens"] = baseline_result.output_tokens

    return CheckResult(
        name=check.name,
        description=check.description,
        score=score,
        max_score=check.max_score,
        severity=severity,
        findings=findings,
        recommendations=recommendations,
        metadata=metadata,
    )


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
    """Score generated code on five criteria and produce findings."""
    criteria = {
        "parses_as_python": False,
        "imports_http_client": False,
        "handles_errors": False,
        "constructs_request": False,
        "handles_response": False,
    }

    try:
        tree = ast.parse(code)
        criteria["parses_as_python"] = True
    except SyntaxError:
        tree = None

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

    score = sum(2 for passed in criteria.values() if passed)

    # Count gap markers in the generated code. Each is evidence of a real
    # documentation deficiency that the model had to work around, and
    # reduces the score by 1 (floored at 0).
    gap_markers = GAP_MARKER_PATTERN.findall(code)
    gap_count = len(gap_markers)
    raw_score = score
    score = max(0, score - gap_count)

    findings = []
    recommendations = []

    label_map = {
        "parses_as_python": "Valid Python syntax",
        "imports_http_client": "Imports an HTTP client (requests, httpx, urllib, aiohttp)",
        "handles_errors": "Includes error handling (try/except or status checks)",
        "constructs_request": "Constructs an HTTP request",
        "handles_response": "Handles the response body or status",
    }
    for key, passed in criteria.items():
        marker = "✓" if passed else "✗"
        findings.append(f"{marker} {label_map[key]}")

    if gap_count:
        findings.append(
            f"⚠ Model flagged {gap_count} documentation gap"
            f"{'s' if gap_count != 1 else ''} in code comments "
            f"(structural score {raw_score}/10, adjusted to {score}/10)"
        )
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
        "score": score,
        "criteria": criteria,
        "findings": findings,
        "recommendations": recommendations,
        "line_count": line_count,
        "gap_count": gap_count,
        "raw_score": raw_score,
    }
