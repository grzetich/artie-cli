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

The eight static checks run locally with no key and no network. The empirical Generation Quality check is opt-in, because it makes a billed Anthropic API call:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
artie check ./openapi.yaml --generate-code
```

Without `--generate-code` — or without a key — Generation Quality shows as N/A with a note about how to enable it, and the rest of the report is unaffected.

## What it checks

**Eight static checks**, derived from the TNJ research:

- **Format Efficiency**: how token-efficient your documentation format is
- **Prose Structure**: heading hierarchy, code blocks, section sizes, and staleness signals in prose pages. Format Efficiency scores what a page costs to read; this scores whether an agent can find an answer inside it. Applies to Markdown and HTML
- **Endpoint Completeness**: descriptions, operationIds, and documented path parameters
- **Example Coverage**: request and response body examples
- **Error Documentation**: 4xx and 5xx responses with meaningful descriptions and content schemas
- **Auth Clarity**: security schemes defined, described, and applied to operations
- **Parameter Naming**: consistent naming convention across parameters and schema properties
- **Schema Complexity**: nesting depth across component schemas

**One empirical check**, applied to any input format:

- **Generation Quality**: an AI model is given your docs and asked to write a Python function that calls the API. The check evaluates what it produced on five criteria: valid syntax, HTTP client import, error handling, request construction, and response handling. The generated code is included in the report so you can see exactly what the model wrote from your docs.

Format Efficiency reports a token count and what a page costs to read at several vendors' input prices. Those counts come from a local GPT-4o tokenizer so the check can run offline with no API key, and every model tokenizes differently — use the figures to compare formats against each other, which is what the check is for, rather than as a billing estimate.

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

# Print the report and also write it to a markdown file
artie check ./openapi.yaml --output md

# Fail the build if any check scores below 7
artie check ./openapi.yaml --fail-under 7

# Run the empirical Generation Quality check (billed API call)
artie check ./openapi.yaml --generate-code

# Use a different model for generation
artie check ./openapi.yaml --generate-code --model claude-opus-5

# Differential mode: measure what the docs add beyond training (doubles cost)
artie check ./openapi.yaml --generate-code --differential
```

`--output md` prints the usual terminal report and additionally writes `domain-path.md` into the current directory, named from what you
checked: `https://api.example.com/v1/openapi.yaml` becomes
`api-example-com-v1-openapi.md`, and a local `./spec/openapi.yaml` becomes
`openapi.md`. A local file is named from the file itself rather than its full path, so
the same document always produces the same report regardless of how you addressed it.
Re-running overwrites the report in place.

## About generation quality and training contamination

The Generation Quality check has a real limitation worth understanding. When the model has seen an API during training (which is the case for AWS, Stripe, GitHub, and most public APIs with Python SDKs on PyPI), it can write working code from training alone, regardless of how complete the docs you're testing are. A 10/10 score on a famous API tells you the model knows the API, not that the docs are good.

The check mitigates this two ways:

The prompt instructs the model to use only information from the docs and to flag gaps in code comments. Gap comments are detected automatically and reduce the score by 1 each. This shifts the failure mode from "writes confident wrong code" to "writes hedgy code with explicit gap markers," which is more useful.

`--differential` mode adds a second API call with no docs body, measuring what the model produces from training alone. The delta between the two scores is what the docs actually contributed. This doubles the API cost but produces the most honest measurement, especially valuable for novel or internal APIs the model has not seen.

For docs the model already knows well, expect a high baseline and a small delta. That's not a failure of your docs; it's the limit of what empirical generation testing can tell you for that API.

## Cost

Generation Quality is off unless you pass `--generate-code`, so a default run costs nothing. With the flag it makes one Anthropic API call per run; on Claude Sonnet 5 (the default model) a typical docs page costs about $0.02 to $0.05. For CI that runs on every PR, leave the flag off for fast free feedback and add `--generate-code` on a schedule.

## Examples

```bash
artie check examples/bookclub-openapi.yaml
artie check examples/broken-openapi.yaml
artie check examples/sample-openapi.yaml
```

## Privacy

The static checks run entirely locally. The Generation Quality check sends your documentation content to Anthropic's API, and only runs when you pass `--generate-code`. If your docs are confidential, simply omit that flag.

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
