"""artie command line interface."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from artie import SCORING_VERSION, __version__
from artie.baseline import Baseline, BaselineError, load_baseline
from artie.checks import ALL_CHECKS, BaseCheck, CheckResult
from artie.checks.generation_quality import SampleGenerationCheck
from artie.config import ArtieConfig, ConfigError, load_config
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
        typer.echo(f"artie-cli {__version__} (scoring rubric v{SCORING_VERSION})")
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
            help="Exit non-zero if any scored check without its own configured "
            "threshold scores below this value (0-10). Per-check thresholds "
            "in .artie.toml take precedence.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Timeout in seconds for HTTP requests.",
        ),
    ] = 20,
    with_generation: Annotated[
        bool | None,
        typer.Option(
            "--with-generation",
            help="Run the Sample Generation check: an AI model writes code "
            "from these docs (uses the Anthropic API, costs money). Off by "
            "default; the static checks always run.",
        ),
    ] = None,
    differential: Annotated[
        bool | None,
        typer.Option(
            "--differential",
            help=(
                "Run Sample Generation in differential mode (implies "
                "--with-generation). Two API calls per run. Adds a baseline "
                "generation with no docs to flag training-data contamination."
            ),
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Model to use for the Sample Generation check.",
        ),
    ] = None,
    baseline_path: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help="Path to a previously saved JSON report. The run is compared "
            "against it and per-check score deltas are reported.",
        ),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Path to an explicit .artie.toml. By default artie searches "
            "the current directory and its parents.",
        ),
    ] = None,
) -> None:
    """Analyze documentation and report AI-readiness scores."""
    console = Console()
    err = Console(stderr=True)

    # Configuration: an explicit --config, or an auto-discovered .artie.toml.
    try:
        config = load_config(explicit=config_path)
    except ConfigError as exc:
        err.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=2)
    for warning in config.warnings:
        err.print(f"[yellow]Config warning:[/yellow] {warning}")
    if config.source_path is not None:
        err.print(f"[dim]Using config: {config.source_path}[/dim]")

    # CLI flags override config defaults. A None flag means "not passed".
    effective_with_generation = (
        with_generation if with_generation is not None else config.with_generation
    )
    effective_differential = (
        differential if differential is not None else config.differential
    )
    effective_model = model or config.model or DEFAULT_MODEL
    # Differential mode is meaningless without generation, so it implies it.
    generation_enabled = effective_with_generation or effective_differential

    baseline = _load_baseline(baseline_path, err)

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

    # Instantiate all static checks plus Sample Generation with its flags.
    # The console only goes to Sample Generation when rendering to terminal;
    # for JSON output we don't want the spinner.
    check_instances: list[BaseCheck] = [cls() for cls in ALL_CHECKS]
    generation_console = console if output.lower() == "terminal" else None
    check_instances.append(
        SampleGenerationCheck(
            model=effective_model,
            enabled=generation_enabled,
            differential=effective_differential,
            source=source,
            console=generation_console,
        )
    )

    results = [
        check_instance.run(content, format_type, parsed=parsed)
        for check_instance in check_instances
    ]

    output_lower = output.lower()
    if output_lower == "json":
        typer.echo(json_report.render(source, format_type, results, baseline))
    elif output_lower == "terminal":
        terminal.render(
            source,
            format_type,
            results,
            console=console,
            content_type=content_type_header,
            baseline=baseline,
        )
    else:
        raise typer.BadParameter(
            f"Unknown output format: {output}. Use 'terminal' or 'json'."
        )

    if _gate_failed(results, config, fail_under, err):
        raise typer.Exit(code=1)


def _load_baseline(baseline_path: Path | None, err: Console) -> Baseline | None:
    """Load a baseline report, or exit on error."""
    if baseline_path is None:
        return None
    try:
        baseline = load_baseline(baseline_path)
    except BaselineError as exc:
        err.print(f"[red]Baseline error:[/red] {exc}")
        raise typer.Exit(code=2)
    if baseline.scoring_version and baseline.scoring_version != SCORING_VERSION:
        err.print(
            f"[yellow]Baseline warning:[/yellow] baseline was scored under "
            f"rubric v{baseline.scoring_version}, this run uses v{SCORING_VERSION}. "
            f"Deltas may not be comparable."
        )
    return baseline


def _gate_failed(
    results: list[CheckResult],
    config: ArtieConfig,
    cli_fail_under: int | None,
    err: Console,
) -> bool:
    """Apply the pass/fail gate. Returns True if the run should exit non-zero.

    A check fails when its score is below its threshold. The threshold is the
    per-check value from .artie.toml if set, otherwise the global value
    (--fail-under on the CLI overrides defaults.fail_under in config).
    Checks listed in the config's `ignore` are never gated. Informational and
    not-evaluable checks have no score and are skipped.
    """
    global_threshold = (
        cli_fail_under if cli_fail_under is not None else config.fail_under
    )

    failures: list[str] = []
    for result in results:
        if result.name in config.ignore:
            continue
        if result.score is None or not result.is_evaluable:
            continue
        threshold = config.thresholds.get(result.name, global_threshold)
        if threshold is not None and result.score < threshold:
            failures.append(
                f"{result.name}: {result.score}/{result.max_score} "
                f"(threshold {threshold})"
            )

    if failures:
        err.print(
            f"[red]Gate failed:[/red] {len(failures)} check(s) below threshold:"
        )
        for failure in failures:
            err.print(f"  [red]✗[/red] {failure}")
        return True
    return False


if __name__ == "__main__":
    app()
