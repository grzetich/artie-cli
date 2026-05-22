"""Render analysis reports to the terminal."""

from datetime import datetime, timezone

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from artie.baseline import Baseline
from artie.checks.base import CheckResult, Severity

SEVERITY_STYLE: dict[Severity, str] = {
    Severity.EXCELLENT: "bold green",
    Severity.GOOD: "green",
    Severity.NEEDS_WORK: "yellow",
    Severity.POOR: "red",
    Severity.NOT_EVALUABLE: "dim",
}

SEVERITY_SYMBOL: dict[Severity, str] = {
    Severity.EXCELLENT: "✓",
    Severity.GOOD: "✓",
    Severity.NEEDS_WORK: "⚠",
    Severity.POOR: "✗",
    Severity.NOT_EVALUABLE: "—",
}


def _visuals(result: CheckResult) -> tuple[str, str]:
    """Return the (symbol, style) for a check result.

    Informational checks (Sample Generation) get their own neutral treatment
    so they don't read as either a pass or a failure.
    """
    if result.informational:
        return "ℹ", "cyan"
    return SEVERITY_SYMBOL[result.severity], SEVERITY_STYLE[result.severity]


def _delta_cell(result: CheckResult, baseline: Baseline | None) -> Text:
    """Render the baseline-comparison cell for one check."""
    if baseline is None:
        return Text("")
    delta = baseline.delta_for(result.name, result.score)
    if delta is None:
        if result.name not in baseline.scores:
            return Text("new", style="dim")
        return Text("—", style="dim")
    if delta > 0:
        return Text(f"+{delta}", style="green")
    if delta < 0:
        return Text(str(delta), style="red")
    return Text("0", style="dim")


def render(
    source: str,
    format_type: str,
    results: list[CheckResult],
    console: Console | None = None,
    content_type: str | None = None,
    baseline: Baseline | None = None,
) -> None:
    """Render an analysis report to the terminal."""
    console = console or Console()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    header = Text()
    header.append("artie.fm", style="bold magenta")
    header.append(" — API Documentation AI-Readiness Report\n")
    header.append(f"Source: {source}\n", style="dim")
    header.append(f"Format: {format_type}", style="dim")
    if content_type and not _matches_format(content_type, format_type):
        # Surface content negotiation: the server returned something different
        # from what the URL suggests.
        header.append(
            f"\nServer returned: {content_type} (content negotiation honored)",
            style="dim cyan",
        )
    header.append(f"\nRetrieved: {timestamp}", style="dim")
    if baseline is not None:
        label = baseline.source or (str(baseline.path) if baseline.path else "?")
        header.append(f"\nCompared against baseline: {label}", style="dim cyan")
    console.print(Panel(header, expand=False))

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("", width=2)
    table.add_column("Check")
    table.add_column("Score", justify="right")
    table.add_column("Severity")
    if baseline is not None:
        table.add_column("Δ", justify="right")

    for result in results:
        symbol, style = _visuals(result)
        severity_label = (
            "informational"
            if result.informational
            else result.severity.value.replace("_", " ")
        )
        row = [
            Text(symbol, style=style),
            result.name,
            result.score_display,
            Text(severity_label, style=style),
        ]
        if baseline is not None:
            row.append(_delta_cell(result, baseline))
        table.add_row(*row)

    console.print(table)

    # Per-check detail sections
    for result in results:
        _render_check_detail(result, console, baseline)

    cta = Text()
    cta.append(
        "Based on Tokens Not Jokin' research: leanpub.com/tokensnotjokin",
        style="dim italic",
    )
    console.print(Panel(cta, expand=False))


def _render_check_detail(
    result: CheckResult, console: Console, baseline: Baseline | None
) -> None:
    """Render a single check's detail panel, including code block if present."""
    _, style = _visuals(result)
    body = Text()
    if result.findings:
        body.append("Findings:\n", style="bold")
        for finding in result.findings:
            body.append(f"  • {finding}\n")
    if result.recommendations:
        if result.findings:
            body.append("\n")
        body.append("Recommendations:\n", style="bold")
        for rec in result.recommendations:
            body.append(f"  → {rec}\n")
    if not result.findings and not result.recommendations:
        body.append("(no details)", style="dim")

    # If this check produced generated code, show it as a syntax-highlighted
    # block inside the same panel.
    code = result.metadata.get("code") if result.metadata else None
    if code:
        body.append("\nGenerated code:\n", style="bold")
        syntax = Syntax(code, "python", theme="ansi_dark", line_numbers=True)
        content = Group(body, syntax)
    else:
        content = body

    title = f"{result.name} — {result.score_display}"
    if baseline is not None:
        delta = baseline.delta_for(result.name, result.score)
        if delta is not None:
            title += f" ({delta:+d} vs baseline)"

    console.print(
        Panel(
            content,
            title=title,
            title_align="left",
            border_style=style,
            expand=False,
        )
    )


def _matches_format(content_type: str, format_type: str) -> bool:
    """Check if the server's content-type matches our detected format."""
    ct = content_type.lower()
    format_lower = format_type.lower()
    if "yaml" in ct and "yaml" in format_lower:
        return True
    if "json" in ct and "json" in format_lower:
        return True
    if "markdown" in ct and "markdown" in format_lower:
        return True
    if "html" in ct and "html" in format_lower:
        return True
    return False
