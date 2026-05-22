# Architecture

artie-cli scores API documentation for AI readiness. It accepts either a local file or an HTTP URL, detects the format, parses what it can, runs a set of checks against the parsed content, and renders a report. Each check is an independent measurement; there is no aggregate score.

## Layout

```
src/artie/
├── __init__.py        Package version and SCORING_VERSION.
├── __main__.py        Lets `python -m artie` run the CLI.
├── cli.py             Typer-based CLI. Owns the request flow and the gate.
├── config.py          Loads .artie.toml: per-check thresholds, ignored
│                      checks, default flags.
├── baseline.py        Loads a saved JSON report for run-over-run deltas.
├── fetcher.py         HTTP fetcher using stdlib urllib. Returns raw content
│                      plus a format hint derived from Content-Type and URL.
├── generator.py       Minimal Anthropic Messages API client (stdlib urllib).
│                      Used by the Sample Generation check. Implements retry
│                      logic for transient errors (429, 503, 529).
├── parsers/
│   ├── __init__.py    Format detection (detect_format) and the public
│   │                  parse() entry point.
│   ├── openapi.py     OpenAPI YAML and JSON parsing. Also extracts embedded
│   │                  OpenAPI specs from markdown code fences.
│   └── types.py       Endpoint and ParsedDocs dataclasses. Shared by all
│                      checks that need a structured view of the spec.
├── checks/
│   ├── __init__.py    The ALL_CHECKS registry.
│   ├── base.py        BaseCheck, CheckResult, Severity. The check protocol.
│   ├── format_efficiency.py
│   ├── endpoint_completeness.py
│   ├── example_coverage.py
│   ├── error_documentation.py
│   ├── auth_clarity.py
│   ├── parameter_naming.py
│   ├── schema_complexity.py
│   └── generation_quality.py  SampleGenerationCheck (opt-in, unscored).
└── reporters/
    ├── __init__.py
    ├── terminal.py    Rich-based human-readable report.
    └── json_report.py Machine-readable JSON for CI integration.
```

## Request flow

The CLI does the same thing in every invocation:

1. Parse arguments. Resolve target as either a file path or an HTTP URL.
2. Load configuration. `config.load_config` reads a `.artie.toml` (an explicit `--config` path, or auto-discovered from the working directory upward). CLI flags override config defaults; a `None` flag means "not passed". If `--baseline` is given, `baseline.load_baseline` reads the prior JSON report.
3. Read content. For files, read directly. For URLs, call `fetcher.fetch`, which sends an Accept header preferring structured formats and returns raw bytes, a Content-Type, and a format hint.
4. Detect format. `parsers.detect_format` combines the URL suffix, the Content-Type hint, and content inspection to return one of: `openapi-yaml`, `openapi-json`, `yaml`, `json`, `markdown`, `html`, `unknown`.
5. Parse. `parsers.parse` produces a `ParsedDocs`. For OpenAPI inputs this contains the raw dict, the extracted endpoints, and the components map. For markdown, parse scans code fences for an embedded OpenAPI spec; if found, the ParsedDocs is fully populated and `extracted_from` is set to `"markdown"`. For HTML or other unstructured inputs, raw is None and `parse_error` explains why.
6. Run checks. The CLI instantiates each check in `ALL_CHECKS`, plus `SampleGenerationCheck` constructed with the resolved flags, and calls `check.run(content, format_type, parsed)` on each. Checks decide for themselves whether they can run. If they cannot, they return a not-evaluable result.
7. Render. Either terminal output via Rich or JSON via `json_report.render`, both passed the baseline for delta reporting.
8. Apply the gate. `_gate_failed` exits non-zero if any scored, non-ignored check is below its threshold (per-check from config, else the global `--fail-under` or `defaults.fail_under`).

## The check protocol

Every check subclasses `BaseCheck` and implements `run(content, format_type, parsed) -> CheckResult`. A check returns one of three things:

- An evaluable result with a score 0-10 and a severity computed from the score.
- A not-evaluable result, created by calling `self.not_evaluable(reason)`. Use this when the input does not provide enough information to score honestly. Examples: schema complexity has no `components.schemas` section, endpoint completeness was given markdown with no embedded spec, generation quality has no API key in the environment.
- An evaluable result with score 0 if the check ran but found nothing worth scoring above zero. Used sparingly. Prefer not-evaluable when the issue is missing information rather than missing quality.

`CheckResult.metadata` is a free-form dict. Checks use it to carry machine-readable data that does not belong in findings or recommendations: token counts, evaluation criteria booleans, generated code blocks, baseline scores in differential mode, and so on. The JSON reporter passes metadata through verbatim. The terminal reporter has special-case rendering for `metadata.code`, which it shows as a syntax-highlighted Python block.

## Notable design decisions

**No aggregate score.** Each check stands alone. We do not currently have empirical evidence for the right weights to combine them. See `docs/scoring.md` for every threshold, its evidence basis, and the rationale for not aggregating.

**Stdlib urllib instead of the anthropic SDK.** The generator does one kind of call: a single Messages request, no streaming, no batching. Adding httpx, pydantic, and the SDK would roughly double cold-start time under uvx. The fetcher uses the same approach for the same reason.

**Embedded OpenAPI extraction.** Modern docs sites (Mintlify, Fern, ReadMe, Stainless, Scalar) embed the OpenAPI spec inside markdown code fences alongside prose and SDK examples. When the input is markdown, `parsers.openapi._parse_markdown` scans for the first fenced block whose contents parse as OpenAPI and uses that as the spec. The structured checks then run against the embedded spec while Format Efficiency still scores against the full markdown.

**Sample Generation is a separate kind of check, and unscored.** It calls an external API, costs money, and produces results that depend partly on the model rather than entirely on the docs. Because of that it is opt-in (`--with-generation`) and deliberately produces no 0-10 score: its `CheckResult` has `informational=True` and `score=None`. The generated code is the deliverable; the five structural criteria are reported as commentary. It accepts a `console` parameter so it can render a spinner during the LLM call, and a `differential` flag that triggers a second baseline call. When that baseline is structurally strong it emits a contamination warning. It is the most complex check and the least empirically grounded. Treat it accordingly.

**Informational is a third result state.** Alongside scored and not-evaluable, a `CheckResult` can be `informational`: the check ran and has findings but assigns no score. It is excluded from `is_evaluable` and from the pass/fail gate. Only Sample Generation uses it.

**Not-evaluable is a first-class state, not an error.** A check returning N/A is honest: this measurement does not apply to this input. The terminal reporter renders N/A with its own symbol and severity color. The JSON reporter exposes `evaluable: false`. Both are intentional design choices to avoid pressuring checks into producing fake scores when they cannot honestly produce real ones.

## Adding a check

See `CONTRIBUTING.md`.
