# Architecture

artie-cli scores API documentation for AI readiness. It accepts either a local file or an HTTP URL, detects the format, parses what it can, runs a set of checks against the parsed content, and renders a report. Each check is an independent measurement; there is no aggregate score.

## Layout

```
src/artie/
├── __init__.py        Version string.
├── __main__.py        Lets `python -m artie` run the CLI.
├── cli.py             Typer-based CLI. Owns the request flow.
├── fetcher.py         HTTP fetcher using stdlib urllib. Returns raw content
│                      plus a format hint derived from Content-Type and URL.
├── generator.py       Minimal Anthropic Messages API client (stdlib urllib).
│                      Used by the Generation Quality check. Implements retry
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
│   ├── _schema_utils.py   Shared schema/example helpers: ref resolution,
│   │                      vacuous-schema detection, example parsing and
│   │                      shallow schema validation.
│   ├── _html_prose.py     Renders an HTML page as the markdown subset
│   │                      Prose Structure reads. Stdlib HTMLParser only.
│   ├── format_efficiency.py
│   ├── prose_structure.py
│   ├── endpoint_completeness.py
│   ├── example_coverage.py
│   ├── error_documentation.py
│   ├── auth_clarity.py
│   ├── parameter_naming.py
│   ├── schema_complexity.py
│   └── generation_quality.py
└── reporters/
    ├── __init__.py
    ├── terminal.py    Rich-based human-readable report.
    ├── json_report.py Machine-readable JSON for CI integration.
    └── markdown_report.py  Markdown file for sharing and diffing, plus the
                            `domain-path.md` naming rule.
```

## Request flow

The CLI does the same thing in every invocation:

1. Parse arguments. Resolve target as either a file path or an HTTP URL.
2. Read content. For files, read directly. For URLs, call `fetcher.fetch`, which sends an Accept header preferring structured formats and returns raw bytes, a Content-Type, and a format hint.
3. Detect format. `parsers.detect_format` combines the URL suffix, the Content-Type hint, and content inspection to return one of: `openapi-yaml`, `openapi-json`, `yaml`, `json`, `markdown`, `html`, `unknown`. `parsers.display_format` derives the human-facing name from that plus the parse result; it differs only for spec-in-markdown pages, which report as `OpenAPI passthrough`. The raw format string stays the routing key everywhere internally.
4. Parse. `parsers.parse` produces a `ParsedDocs`. For OpenAPI inputs this contains the raw dict, the extracted endpoints, and the components map. For markdown, parse scans code fences for an embedded OpenAPI spec; if found, the ParsedDocs is fully populated and `extracted_from` is set to `"markdown"`. For HTML or other unstructured inputs, raw is None and `parse_error` explains why.
5. Run checks. The CLI instantiates each check in `ALL_CHECKS`, plus `GenerationQualityCheck` constructed with CLI flags, and calls `check.run(content, format_type, parsed)` on each. Checks decide for themselves whether they can run. If they cannot, they return a not-evaluable result.
6. Render. Either terminal output via Rich or JSON via `json_report.render`.

## The check protocol

Every check subclasses `BaseCheck` and implements `run(content, format_type, parsed) -> CheckResult`. A check returns one of three things:

- An evaluable result with a score 0-10 and a severity computed from the score.
- A not-evaluable result, created by calling `self.not_evaluable(reason)`. Use this when the input does not provide enough information to score honestly. Examples: schema complexity has no `components.schemas` section, endpoint completeness was given markdown with no embedded spec, generation quality has no API key in the environment.
- An evaluable result with score 0 if the check ran but found nothing worth scoring above zero. Used sparingly. Prefer not-evaluable when the issue is missing information rather than missing quality.

`CheckResult.metadata` is a free-form dict. Checks use it to carry machine-readable data that does not belong in findings or recommendations: token counts, evaluation criteria booleans, generated code blocks, baseline scores in differential mode, and so on. The JSON reporter passes metadata through verbatim. The terminal reporter has special-case rendering for `metadata.code`, which it shows as a syntax-highlighted Python block.

## Notable design decisions

**No aggregate score.** Each check stands alone. We do not currently have empirical evidence for the right weights to combine them. See `docs/scoring.md` (forthcoming) for the rationale behind individual thresholds.

**Stdlib urllib instead of the anthropic SDK.** The generator does one kind of call: a single Messages request, no streaming, no batching. Adding httpx, pydantic, and the SDK would roughly double cold-start time under uvx. The fetcher uses the same approach for the same reason.

**Substance over presence.** Several checks originally credited a key for existing: any truthy `schema`, any non-null `example`. That let placeholders score as documentation — `properties: {}` counted as an error schema, and an `example` holding truncated JSON counted as an example. `checks/_schema_utils.py` centralizes the "does this actually say anything" tests so Example Coverage and Error Documentation can score substance. Examples are parsed and validated shallowly against their schema (type agreement, required properties, enum membership); it is deliberately not a full JSON Schema validator, because the goal is catching the errors that appear in published specs without adding a dependency or false-failing on exotic keywords.

**Format Efficiency measures cost, Prose Structure measures quality.** Format Efficiency scores the format and counts tokens, which means every markdown page gets the same score. That is correct but not useful on its own, so `prose_structure.py` does the discriminating for prose inputs: heading hierarchy, code-block presence and language tagging, section sizes, and staleness signals. HTML is prose wearing markup, so rather than teach the check a second dialect, `_html_prose.py` normalizes a page into the markdown subset the check already reads — `<h1>`-`<h6>` become ATX headings, `<pre>` becomes a fence carrying the language off the usual highlighter classes — and the same tested scoring runs unchanged. Scoring the extracted prose rather than the raw markup also keeps `class="legacy-nav"` or a `TODO` in a `<script>` from registering as staleness. Page-level token *variance* is deliberately absent — variance is a property of a corpus, and artie scores one target per invocation.

**Naming is scored per location.** Parameter Naming compares names within each location (path, query, header, cookie, body) rather than pooling them. Pooling penalized correct HTTP: `Content-Type` in a header next to `fileName` in a body is two conventions each used where it belongs, not one inconsistent API. Header names are judged against HTTP header convention (hyphen-delimited, case-insensitive) rather than by majority vote.

**Gap markers are elicited, not volunteered.** Generation Quality subtracts a point per comment where the model flags a missing detail — but `PROMPT_TEMPLATE` explicitly instructs it to write those comments. They are evidence the detail was absent from the docs; they are not evidence an unprompted agent would notice. Counts are only comparable across runs using the same prompt, so that paragraph of the prompt is part of the scoring contract. `tests/test_generation_prompt.py` fails if it is edited away.

**Embedded OpenAPI extraction.** Modern docs sites (Mintlify, Fern, ReadMe, Stainless, Scalar) embed the OpenAPI spec inside markdown code fences alongside prose and SDK examples. When the input is markdown, `parsers.openapi._parse_markdown` scans for the first fenced block whose contents parse as OpenAPI and uses that as the spec. The structured checks then run against the embedded spec while Format Efficiency still scores against the full markdown.

**Generation Quality is a separate kind of check.** It calls an external API, costs money, and produces results that depend partly on the model rather than entirely on the docs. It accepts a `console` parameter so it can render a spinner during the LLM call, and a `differential` flag that triggers a second baseline call to measure training contamination. It is the most complex check and the least empirically grounded. Treat it accordingly. Because it is the only check that spends money, it is **opt-in**: `--generate-code` turns it on and the default run is free, local, and offline. The inverted flag matters more than it looks — under the old `--no-generation` default, forgetting a flag cost money, and the safe path should not be the one you have to remember.

**Not-evaluable means we cannot measure, not that we did not try.** Schema Complexity used to return N/A whenever `components.schemas` was absent, which reported N/A on documents whose schemas were sitting inline on every operation — common on platforms that render one page per endpoint. It now falls back to inline request, response, and parameter schemas, and reports which source it used in `metadata.schema_source`.

**Not-evaluable is a first-class state, not an error.** A check returning N/A is honest: this measurement does not apply to this input. The terminal reporter renders N/A with its own symbol and severity color. The JSON reporter exposes `evaluable: false`. Both are intentional design choices to avoid pressuring checks into producing fake scores when they cannot honestly produce real ones.

## Adding a check

See `CONTRIBUTING.md`.
