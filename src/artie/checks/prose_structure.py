"""Prose Structure check.

Format Efficiency answers "how expensive is this to read". It deliberately
does not answer "is this page any good", which is why it returns a flat score
for every markdown page it sees. This check does the discriminating.

The signals are the ones that decide whether an agent can find and use an
answer inside a prose page:

1. Heading structure. Headings are how a retrieval system chunks a page and
   how an agent locates the section it needs. A page with no H1, or one that
   jumps H1 -> H3, chunks badly.
2. Code blocks. API prose without a single code block makes the agent infer
   call shapes from sentences. Untagged fences (``` with no language) also
   cost accuracy, because the agent has to guess whether it is looking at
   shell, JSON, or Python.
3. Chunk size. Text between two headings is the unit a retriever returns.
   One enormous unbroken section means every retrieval either overflows or
   truncates mid-thought.
4. Staleness signals. Version strings in headings, "deprecated", and "coming
   soon" mean the page describes something other than the current API. An
   agent has no way to tell which parts still apply.

Not implemented: page-level token variance across a corpus. Variance is a
property of a set of pages, and artie scores one target per invocation, so
there is nothing to compare against in a single run. It needs a corpus mode.
"""

from __future__ import annotations

import re
from typing import Any

from artie.checks._html_prose import html_to_prose
from artie.checks.base import BaseCheck, CheckResult

# A section longer than this chunks badly: at roughly 4 characters per token
# it is over ~1,000 tokens, which overflows a typical retrieval window and
# forces a mid-sentence truncation.
LARGE_SECTION_CHARS = 4_000

# Below this, a page is a stub and its structure tells us nothing.
MIN_PROSE_CHARS = 200

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_FENCE_PATTERN = re.compile(
    r"^[ \t]*```(?P<lang>[a-zA-Z0-9_+-]*)[^\n]*\n(?P<body>.*?)^[ \t]*```",
    re.DOTALL | re.MULTILINE,
)

# Staleness markers. Version strings are matched only in headings, where they
# describe the section's subject; in body text "v2" is usually just prose.
_VERSION_IN_HEADING = re.compile(r"\bv\d+(\.\d+)*\b|\b20(1\d|2[0-5])\b", re.IGNORECASE)
_STALE_PHRASES = (
    "deprecated",
    "coming soon",
    "no longer supported",
    "will be removed",
    "legacy",
    "todo",
    "tbd",
)


class ProseStructureCheck(BaseCheck):
    name = "Prose Structure"
    description = (
        "Heading hierarchy, code blocks, section sizes, and staleness signals "
        "in prose documentation."
    )

    def run(
        self, content: str, format_type: str, parsed: Any = None
    ) -> CheckResult:
        fmt = format_type.lower()
        if fmt not in ("markdown", "unknown", "html"):
            return self.not_evaluable(
                f"Prose Structure applies to prose documentation; "
                f"this input is {format_type}."
            )

        # HTML is prose wearing markup. Normalize it into the markdown subset
        # this check reads so the same four signals apply; see _html_prose.
        converted_from_html = fmt == "html"
        original_content = content
        if converted_from_html:
            content = html_to_prose(content)

        stripped = content.strip()
        if len(stripped) < MIN_PROSE_CHARS:
            noun = "Extracted prose" if converted_from_html else "Content"
            return self.not_evaluable(
                f"{noun} is under {MIN_PROSE_CHARS} characters; too short for "
                f"structure to be meaningful."
            )

        headings = _headings(content)
        fences = _fences(content)
        sections = _sections(content, headings)

        heading_score, heading_findings = _score_headings(headings)
        code_score, code_findings = _score_code_blocks(fences)
        chunk_score, chunk_findings = _score_chunks(sections)
        staleness_score, staleness_findings = _score_staleness(headings, content)

        subscores = [heading_score, code_score, chunk_score, staleness_score]
        composite = sum(subscores) / len(subscores)
        score = round(composite * self.max_score)
        severity = self.severity_for(score)

        findings = [
            *heading_findings,
            *code_findings,
            *chunk_findings,
            *staleness_findings,
        ]
        if converted_from_html:
            # Say so explicitly: these numbers describe the prose recovered
            # from the markup, not the raw page Format Efficiency scored.
            findings.insert(
                0,
                f"Scored the prose extracted from HTML "
                f"({len(stripped):,} characters of text from "
                f"{len(original_content):,} of markup)",
            )

        recommendations = _recommendations(
            heading_score, code_score, chunk_score, staleness_score
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
                "converted_from_html": converted_from_html,
                "headings": len(headings),
                "heading_levels": sorted({level for level, _ in headings}),
                "code_blocks": len(fences),
                "code_blocks_with_language": sum(1 for lang, _ in fences if lang),
                "sections": len(sections),
                "largest_section_chars": max((len(s) for s in sections), default=0),
                "oversized_sections": sum(
                    1 for s in sections if len(s) > LARGE_SECTION_CHARS
                ),
                "subscores": {
                    "headings": round(heading_score, 3),
                    "code_blocks": round(code_score, 3),
                    "chunk_size": round(chunk_score, 3),
                    "staleness": round(staleness_score, 3),
                },
            },
        )


def _headings(content: str) -> list[tuple[int, str]]:
    """Every ATX heading as (level, text), skipping ones inside code fences."""
    masked = _FENCE_PATTERN.sub(_blank_out, content)
    return [
        (len(match.group(1)), match.group(2).strip())
        for match in _HEADING_PATTERN.finditer(masked)
    ]


def _blank_out(match: re.Match[str]) -> str:
    """Replace a fenced block with blank lines so offsets stay stable.

    Keeping the line count means headings after a fence are still found at
    their real positions, and a `#` inside a shell example is not mistaken
    for a heading.
    """
    return "\n" * match.group(0).count("\n")


def _fences(content: str) -> list[tuple[str, str]]:
    """Every fenced code block as (language, body)."""
    return [
        (match.group("lang").strip(), match.group("body"))
        for match in _FENCE_PATTERN.finditer(content)
    ]


def _sections(content: str, headings: list[tuple[int, str]]) -> list[str]:
    """Split content on headings. Each section is the text under one heading."""
    masked = _FENCE_PATTERN.sub(_blank_out, content)
    boundaries = [match.start() for match in _HEADING_PATTERN.finditer(masked)]
    if not boundaries:
        return [content] if content.strip() else []

    sections: list[str] = []
    preamble = content[: boundaries[0]].strip()
    if preamble:
        sections.append(preamble)
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(content)
        sections.append(content[start:end])
    return sections


def _score_headings(headings: list[tuple[int, str]]) -> tuple[float, list[str]]:
    if not headings:
        return 0.0, ["✗ No headings; the page cannot be chunked by section"]

    levels = [level for level, _ in headings]
    findings = [f"{len(headings)} headings, levels {sorted(set(levels))}"]

    score = 0.0
    if levels[0] == 1 or 1 in levels:
        score += 0.4
        findings.append("✓ Page has an H1")
    else:
        findings.append("✗ No H1; the page has no single stated subject")

    skips = [
        (levels[i], levels[i + 1])
        for i in range(len(levels) - 1)
        if levels[i + 1] - levels[i] > 1
    ]
    if not skips:
        score += 0.3
        findings.append("✓ No skipped heading levels")
    else:
        first = skips[0]
        findings.append(
            f"✗ {len(skips)} skipped heading level"
            f"{'s' if len(skips) != 1 else ''} "
            f"(e.g. H{first[0]} directly to H{first[1]})"
        )

    if len(headings) >= 2:
        score += 0.3
    else:
        findings.append("✗ Only one heading; no internal structure to retrieve against")

    return score, findings


def _score_code_blocks(fences: list[tuple[str, str]]) -> tuple[float, list[str]]:
    if not fences:
        return 0.0, ["✗ No code blocks; call shapes must be inferred from prose"]

    tagged = sum(1 for lang, _ in fences if lang)
    ratio = tagged / len(fences)
    score = 0.5 + 0.5 * ratio

    findings = [f"{len(fences)} code blocks, {tagged} with a language tag"]
    if ratio < 1.0:
        findings.append(
            f"✗ {len(fences) - tagged} code block"
            f"{'s have' if len(fences) - tagged != 1 else ' has'} no language tag"
        )
    return score, findings


def _score_chunks(sections: list[str]) -> tuple[float, list[str]]:
    if not sections:
        return 0.0, ["✗ No sections to measure"]

    sizes = [len(section) for section in sections]
    oversized = [size for size in sizes if size > LARGE_SECTION_CHARS]
    largest = max(sizes)

    findings = [
        f"Largest section: {largest:,} characters "
        f"(~{largest // 4:,} tokens) across {len(sections)} sections"
    ]

    if not oversized:
        return 1.0, findings

    # Penalize by how much of the page sits in oversized sections, so one long
    # appendix on an otherwise well-chunked page is a small hit and a wall of
    # undivided text is a large one.
    share = sum(oversized) / sum(sizes)
    findings.append(
        f"✗ {len(oversized)} section{'s exceed' if len(oversized) != 1 else ' exceeds'} "
        f"{LARGE_SECTION_CHARS:,} characters, holding {share:.0%} of the page"
    )
    return max(0.0, 1.0 - share), findings


def _score_staleness(
    headings: list[tuple[int, str]], content: str
) -> tuple[float, list[str]]:
    findings: list[str] = []
    penalties = 0.0

    versioned = [text for _, text in headings if _VERSION_IN_HEADING.search(text)]
    if versioned:
        penalties += 0.4
        findings.append(
            f"✗ {len(versioned)} heading{'s contain' if len(versioned) != 1 else ' contains'} "
            f"a version or year: {', '.join(versioned[:3])}"
        )

    lowered = content.lower()
    present = [phrase for phrase in _STALE_PHRASES if phrase in lowered]
    if present:
        penalties += min(0.4, 0.2 * len(present))
        findings.append(
            f"✗ Staleness markers in body text: {', '.join(present[:4])}"
        )

    if not findings:
        findings.append("✓ No version-in-heading or staleness markers found")

    return max(0.0, 1.0 - penalties), findings


def _recommendations(
    heading_score: float,
    code_score: float,
    chunk_score: float,
    staleness_score: float,
) -> list[str]:
    recommendations: list[str] = []
    if heading_score < 1.0:
        recommendations.append(
            "Give the page one H1 and a heading for every distinct topic, "
            "without skipping levels. Headings are the chunk boundaries a "
            "retrieval system uses; a page that does not declare them gets "
            "split arbitrarily."
        )
    if code_score < 1.0:
        recommendations.append(
            "Add a runnable code block for each operation the page describes, "
            "and tag every fence with its language. An untagged fence forces "
            "the agent to guess whether it is reading shell, JSON, or Python."
        )
    if chunk_score < 1.0:
        recommendations.append(
            f"Break sections longer than ~{LARGE_SECTION_CHARS:,} characters "
            f"into subsections. Oversized sections either overflow a "
            f"retrieval window or get truncated mid-explanation."
        )
    if staleness_score < 1.0:
        recommendations.append(
            "Move version numbers out of headings and resolve deprecated or "
            "'coming soon' markers. An agent cannot tell which parts of a "
            "page still describe the current API."
        )
    return recommendations
