"""artie command line interface."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from artie import __version__
from artie.checks import ALL_CHECKS, BaseCheck
from artie.checks.generation_quality import GenerationQualityCheck
from artie.fetcher import FetchError, fetch, is_url
from artie.generator import DEFAULT_MODEL
from artie.parsers import detect_format, parse
from artie.reporters import json_report, terminal

app = typer.Typer(
    name="artie",
    help="Score your API documentation for AI-readiness. "
    "Based on the Tokens Not Jokin' research.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"artie-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
) -> None:
    """artie.fm: read the manual so AI agents can too."""


@app.command()
def check(
    target: Annotated[
        str,
        typer.Argument(
            help="Path to a documentation file, or an http(s) URL.",
        ),
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Output format: terminal or json.",
            case_sensitive=False,
        ),
    ] = "terminal",
    fail_under: Annotated[
        int | None,
        typer.Option(
            "--fail-under",
            help="Exit non-zero if any evaluable check scores below this value (0-10).",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Timeout in seconds for HTTP requests.",
        ),
    ] = 20,
    no_generation: Annotated[
        bool,
        typer.Option(
            "--no-generation",
            help="Skip the empirical Generation Quality check (faster, no API cost).",
        ),
    ] = False,
    model: Annotated[
        str,
        typer.Option(
            "--model",
            help="Model to use for the Generation Quality check.",
        ),
    ] = DEFAULT_MODEL,
    differential: Annotated[
        bool,
        typer.Option(
            "--differential",
            help=(
                "Run Generation Quality in differential mode. Two API calls "
                "per run (doubles cost). Measures what the docs contributed "
                "beyond the model's training knowledge."
            ),
        ),
    ] = False,
) -> None:
    """Analyze documentation and report AI-readiness scores."""
    console = Console()

    if is_url(target):
        try:
            fetched = fetch(target, timeout=timeout)
        except FetchError as exc:
            console.print(f"[red]Fetch failed:[/red] {exc}")
            raise typer.Exit(code=2)
        source = fetched.final_url
        content = fetched.content
        format_type = detect_format(content, hint=fetched.format_hint)
        content_type_header = fetched.content_type
    else:
        path = Path(target)
        if not path.exists():
            console.print(f"[red]File not found:[/red] {target}")
            raise typer.Exit(code=2)
        if not path.is_file():
            console.print(f"[red]Not a file:[/red] {target}")
            raise typer.Exit(code=2)
        content = path.read_text(encoding="utf-8", errors="replace")
        format_type = detect_format(content, path=path)
        source = str(path)
        content_type_header = None

    parsed = parse(content, format_type)

    # Instantiate all static checks plus the generation check with its flags.
    # The console only gets passed to the generation check when we're rendering
    # to terminal; for JSON output we don't want the spinner.
    check_instances: list[BaseCheck] = [cls() for cls in ALL_CHECKS]
    generation_console = console if output.lower() == "terminal" else None
    check_instances.append(
        GenerationQualityCheck(
            model=model,
            enabled=not no_generation,
            differential=differential,
            source=source,
            console=generation_console,
        )
    )

    results = []
    for check_instance in check_instances:
        result = check_instance.run(content, format_type, parsed=parsed)
        results.append(result)

    output_lower = output.lower()
    if output_lower == "json":
        typer.echo(json_report.render(source, format_type, results))
    elif output_lower == "terminal":
        terminal.render(
            source,
            format_type,
            results,
            console=console,
            content_type=content_type_header,
        )
    else:
        raise typer.BadParameter(
            f"Unknown output format: {output}. Use 'terminal' or 'json'."
        )

    if fail_under is not None:
        failing = [
            r
            for r in results
            if r.is_evaluable and r.score is not None and r.score < fail_under
        ]
        if failing:
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
