"""Format efficiency check.

Scores documentation based on how token-efficient its format is for AI consumption.
Grounded in Tokens Not Jokin' findings: format choice explains more than 10x the
variance in code generation quality than model choice, and YAML uses up to 80%
fewer tokens than OpenAPI 3.0 JSON.
"""

from typing import Any

import tiktoken

from artie.checks.base import BaseCheck, CheckResult, Severity


# Format efficiency scores out of 10. Anchored to TNJ data:
# YAML and DON are the most token-efficient structured formats.
# JSON carries syntactic overhead. Markdown is readable but unstructured.
# HTML is the worst for AI consumption: structural noise, low signal.
FORMAT_SCORES: dict[str, int] = {
    "openapi-yaml": 10,
    "yaml": 10,
    "don": 9,
    "markdown": 7,
    "openapi-json": 5,
    "json": 5,
    "html": 1,
    "unknown": 5,
}

# Input pricing per million tokens for representative models, in USD.
# Used to translate token counts into agent-read costs that a docs team
# can put on a slide. These prices change occasionally; users should treat
# them as ballpark figures, not invoices.
MODEL_INPUT_PRICING: dict[str, float] = {
    "Claude Sonnet 4.6": 3.00,
    "GPT-4o": 2.50,
    "Claude Haiku 4.5": 1.00,
}


def _format_per_call(dollars: float) -> str:
    """Format a small dollar amount in the most readable unit."""
    if dollars >= 1:
        return f"${dollars:,.2f}"
    if dollars >= 0.01:
        return f"${dollars:.4f}"
    # Sub-cent: show in microcents/microdollars for readability.
    cents = dollars * 100
    if cents >= 0.001:
        return f"{cents:.4f}¢"
    micros = dollars * 1_000_000
    return f"{micros:.2f}μ$"


def _count_tokens(content: str) -> tuple[int, str]:
    """Count tokens, falling back to a character-based estimate on failure.

    Returns (count, source_label). Source is "gpt-4o" when tiktoken succeeds,
    "estimated" when we fall back to chars/4 because tiktoken can't load BPE
    files (e.g., no network on first use, or restricted environments).
    """
    try:
        encoding = tiktoken.encoding_for_model("gpt-4o")
        return len(encoding.encode(content)), "gpt-4o"
    except Exception:
        # Industry rule of thumb: ~4 characters per token for English text.
        # Good enough for relative comparison when we can't load tiktoken.
        return len(content) // 4, "estimated"


class FormatEfficiencyCheck(BaseCheck):
    name = "Format Efficiency"
    description = (
        "How token-efficient is the documentation format for AI consumption. "
        "Lower-overhead formats let agents read more docs per context window."
    )

    def run(self, content: str, format_type: str, parsed: Any = None) -> CheckResult:
        if not content.strip():
            return self.not_evaluable("Empty content")

        format_key = format_type.lower()
        score = FORMAT_SCORES.get(format_key, FORMAT_SCORES["unknown"])
        severity = self.severity_for(score)

        # Token count using GPT-4o encoding as a reasonable industry baseline.
        # Different models tokenize differently; this is for relative comparison.
        char_count = len(content)
        token_count, token_source = _count_tokens(content)

        findings = [
            f"Detected format: {format_type}",
            f"Token count ({token_source}): {token_count:,}",
            f"Character count: {char_count:,}",
        ]

        # Cost to read at representative model pricing. The same docs page
        # fetched many times a day adds up; surface the math so docs teams
        # can quantify the win from reducing tokens.
        if token_count > 0:
            findings.append("Cost to read at input pricing:")
            for model_label, price_per_million in MODEL_INPUT_PRICING.items():
                per_call = token_count / 1_000_000 * price_per_million
                per_million_reads = per_call * 1_000_000
                findings.append(
                    f"  {model_label}: {_format_per_call(per_call)}/read, "
                    f"${per_million_reads:,.0f}/1M reads"
                )

        # Surface positive signals from the parser, when present.
        if (
            parsed is not None
            and hasattr(parsed, "extracted_from")
            and parsed.extracted_from == "markdown"
            and getattr(parsed, "is_openapi", False)
        ):
            findings.append(
                "✓ Embedded OpenAPI spec detected inside markdown; "
                "structured checks ran against it."
            )

        recommendations: list[str] = []
        if format_key in ("openapi-json", "json"):
            recommendations.append(
                "Serve YAML alongside JSON. Same structure, "
                "significantly fewer tokens per request."
            )
        if format_key == "html":
            recommendations.append(
                "HTML carries structural noise that costs tokens without adding "
                "API information. Offer a structured alternative: OpenAPI YAML, "
                "a .md suffix on doc URLs, or an llms.txt index."
            )
            severity = Severity.POOR
        if format_key == "markdown":
            # If we successfully extracted an OpenAPI spec from the markdown,
            # the user already did the right thing. Don't tell them to do it again.
            has_embedded_spec = (
                parsed is not None
                and hasattr(parsed, "extracted_from")
                and parsed.extracted_from == "markdown"
                and getattr(parsed, "is_openapi", False)
            )
            if not has_embedded_spec:
                recommendations.append(
                    "Markdown is readable but unstructured. If this content describes "
                    "an API, pair it with an OpenAPI spec so agents get reliable shapes."
                )

        return CheckResult(
            name=self.name,
            description=self.description,
            score=score,
            max_score=self.max_score,
            severity=severity,
            findings=findings,
            recommendations=recommendations,
            metadata={
                "format": format_type,
                "tokens": token_count,
                "characters": char_count,
            },
        )
