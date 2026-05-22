# artie-cli

Score your API documentation for AI-readiness.

artie reads your API docs the way an AI agent would, then reports how well your documentation actually supports code generation. The checks are derived from [*Tokens Not Jokin'*](https://leanpub.com/tokensnotjokin), a 21,462-test empirical study comparing four AI models against four documentation formats.

artie measures and reports. It does not convert, clean, or modify your documentation.

## Quickstart

```bash
# No install required
uvx artie-cli check ./openapi.yaml
uvx artie-cli check https://api.example.com/openapi.yaml

# Install with pipx
pipx install artie-cli
artie check ./openapi.yaml
```

For the empirical Generation Quality check, set an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
artie check ./openapi.yaml
```

Without a key, artie still runs the seven static checks and reports their results. The Generation Quality check shows as N/A with a note about how to enable it.

## What it checks

**Seven static checks**, derived from the TNJ research:

- **Format Efficiency**: how token-efficient your documentation format is
- **Endpoint Completeness**: descriptions, operationIds, and documented path parameters
- **Example Coverage**: request and response body examples
- **Error Documentation**: 4xx and 5xx responses with meaningful descriptions and content schemas
- **Auth Clarity**: security schemes defined, described, and applied to operations
- **Parameter Naming**: consistent naming convention across parameters and schema properties
- **Schema Complexity**: nesting depth across component schemas

**One empirical check**, applied to any input format:

- **Generation Quality**: an AI model is given your docs and asked to write a Python function that calls the API. The check evaluates what it produced on five criteria: valid syntax, HTTP client import, error handling, request construction, and response handling. The generated code is included in the report so you can see exactly what the model wrote from your docs.

The static checks tell you what specifically to fix. The Generation Quality check tells you whether the fixes are working. Static checks return N/A when the input isn't OpenAPI. Generation Quality runs against anything.

## Inputs

artie accepts either a local file or an HTTP/HTTPS URL:

```bash
artie check ./openapi.yaml
artie check https://api.example.com/openapi.yaml
artie check https://docs.example.com/getting-started
```

Supported formats: OpenAPI YAML, OpenAPI JSON, plain YAML, plain JSON, Markdown, HTML.

When the input is markdown, artie scans for an OpenAPI spec embedded in a code fence and runs the structured checks against that spec. Modern docs sites (Mintlify, Fern, ReadMe, Stainless) embed the spec inline alongside prose and SDK examples, and artie picks it up automatically.

When fetching URLs, artie sends an `Accept` header that requests structured formats first. If the server honors content negotiation (some major docs sites do, including parts of AWS and most Mintlify-hosted sites), you may receive a different format than the URL suggests. The report calls this out.

## Output formats

```bash
# Pretty terminal output with the generated code highlighted (default)
artie check ./openapi.yaml

# JSON for CI pipelines
artie check ./openapi.yaml --output json

# Fail the build if any check scores below 7
artie check ./openapi.yaml --fail-under 7

# Skip the LLM call (faster, no API cost)
artie check ./openapi.yaml --no-generation

# Use a different model for generation
artie check ./openapi.yaml --model claude-opus-4-7

# Differential mode: measure what the docs add beyond training (doubles cost)
artie check ./openapi.yaml --differential
```

## About generation quality and training contamination

The Generation Quality check has a real limitation worth understanding. When the model has seen an API during training (which is the case for AWS, Stripe, GitHub, and most public APIs with Python SDKs on PyPI), it can write working code from training alone, regardless of how complete the docs you're testing are. A 10/10 score on a famous API tells you the model knows the API, not that the docs are good.

The check mitigates this two ways:

The prompt instructs the model to use only information from the docs and to flag gaps in code comments. Gap comments are detected automatically and reduce the score by 1 each. This shifts the failure mode from "writes confident wrong code" to "writes hedgy code with explicit gap markers," which is more useful.

`--differential` mode adds a second API call with no docs body, measuring what the model produces from training alone. The delta between the two scores is what the docs actually contributed. This doubles the API cost but produces the most honest measurement, especially valuable for novel or internal APIs the model has not seen.

For docs the model already knows well, expect a high baseline and a small delta. That's not a failure of your docs; it's the limit of what empirical generation testing can tell you for that API.

## Cost

The Generation Quality check makes one Anthropic API call per artie run. On Claude Sonnet 4.6 (the default), a typical docs page costs about $0.02 to $0.05 per run. For CI integration that runs on every PR, use `--no-generation` for fast feedback and run the full suite on a schedule.

## Examples

```bash
artie check examples/bookclub-openapi.yaml
artie check examples/broken-openapi.yaml
artie check examples/sample-openapi.yaml
```

## Privacy

The static checks run entirely locally. The Generation Quality check sends your documentation content to Anthropic's API. If your docs are confidential, use `--no-generation` or unset `ANTHROPIC_API_KEY` to skip the empirical check.

## Why a CLI

artie is a checker, not a converter. CLI tools live where the docs do: in the repo, in the pipeline, next to the spec. You get a score, you act on it, the static-check data never leaves your machine.

## Research

artie's checks are grounded in empirical findings published in *Tokens Not Jokin'*. Key results:

- YAML uses up to 80% fewer tokens than OpenAPI 3.0 JSON
- Documentation format explains more than 10x the variance in generated code quality than model choice
- Disciplined error documentation produces dramatically better error handling in generated code

The Generation Quality check uses the same methodology as TNJ, applied per-spec: ask an AI to write code from these docs, then evaluate what it produced.

Buy the book: [leanpub.com/tokensnotjokin](https://leanpub.com/tokensnotjokin)

## License

MIT
