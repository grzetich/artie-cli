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

By default artie runs the seven static checks, entirely offline. The optional Sample Generation check is opt-in: pass `--with-generation` and set an Anthropic API key.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
artie check ./openapi.yaml --with-generation
```

Without `--with-generation`, Sample Generation shows as N/A with a note on how to enable it.

## What it checks

**Seven static checks**, derived from the TNJ research:

- **Format Efficiency**: how token-efficient your documentation format is
- **Endpoint Completeness**: descriptions, operationIds, and documented path parameters
- **Example Coverage**: request and response body examples
- **Error Documentation**: 4xx and 5xx responses with meaningful descriptions and content schemas
- **Auth Clarity**: security schemes defined, described, and applied to operations
- **Parameter Naming**: consistent naming convention across parameters and schema properties
- **Schema Complexity**: nesting depth across component schemas

Each static check scores 0–10. Every threshold and weighting is documented in [docs/scoring.md](docs/scoring.md), along with which numbers are empirically grounded and which are heuristics awaiting calibration. artie deliberately reports no aggregate score.

**One optional, opt-in check**, applied to any input format:

- **Sample Generation**: an AI model is given your docs and asked to write a Python function that calls the API. The generated code is the deliverable — artie includes it in the report so you can see exactly what an agent writes from your docs, and comments on its structure (valid syntax, HTTP client import, error handling, request construction, response handling). It is **not scored**: one generation against one model is a sample, not a measurement. Enable it with `--with-generation`.

The static checks tell you what specifically to fix. Sample Generation shows you a concrete example of what an agent produces. Static checks return N/A when the input isn't OpenAPI; Sample Generation runs against anything.

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
# Pretty terminal output (default); static checks only, fully offline
artie check ./openapi.yaml

# JSON for CI pipelines (includes scoring_version)
artie check ./openapi.yaml --output json

# Fail the build if any check scores below 7
artie check ./openapi.yaml --fail-under 7

# Compare against a previously saved JSON report and show per-check deltas
artie check ./openapi.yaml --baseline previous.json

# Run the opt-in Sample Generation check (uses the Anthropic API)
artie check ./openapi.yaml --with-generation

# Differential mode: flag training-data contamination (implies --with-generation, doubles cost)
artie check ./openapi.yaml --differential

# Use a different model for Sample Generation
artie check ./openapi.yaml --with-generation --model claude-opus-4-7
```

## Configuration

Drop a `.artie.toml` in your repository root to pin per-check pass/fail thresholds, exclude checks from the gate, and set default flags. artie discovers it automatically from the working directory upward. See [`.artie.toml.example`](.artie.toml.example) for the full schema and [docs/scoring.md](docs/scoring.md) for what the thresholds mean.

## About Sample Generation and training contamination

Sample Generation has a real limitation worth understanding. When the model has seen an API during training (which is the case for AWS, Stripe, GitHub, and most public APIs with Python SDKs on PyPI), it can write working code from training alone, regardless of how complete the docs you're testing are. Good-looking code for a famous API tells you the model knows the API, not that the docs are good.

This is exactly why the check is unscored: a grade would imply a measurement the method can't honestly deliver. Instead artie shows you the generated code and comments on its structure.

The prompt instructs the model to use only information from the docs and to flag gaps in inline code comments. artie detects those gap comments automatically and reports them as evidence of real documentation deficiencies.

`--differential` mode adds a second API call with no docs body, measuring what the model produces from training alone. When that baseline is already strong, artie prints a contamination warning: the docs-informed sample reflects model capability, not docs quality. Differential mode is most informative for novel or internal APIs the model has not seen.

## Cost

Sample Generation makes one Anthropic API call per run (two with `--differential`). On Claude Sonnet 4.6 (the default), a typical docs page costs roughly $0.02 to $0.05 per run at retail pricing. Because the check is opt-in, CI runs stay free and offline unless you explicitly ask for it.

## Examples

```bash
artie check examples/bookclub-openapi.yaml
artie check examples/broken-openapi.yaml
artie check examples/sample-openapi.yaml
```

## Privacy

The static checks run entirely locally. Sample Generation sends your documentation content to Anthropic's API — but it is opt-in, so nothing leaves your machine unless you pass `--with-generation`.

## Why a CLI

artie is a checker, not a converter. CLI tools live where the docs do: in the repo, in the pipeline, next to the spec. You get a score, you act on it, the static-check data never leaves your machine.

## Research

artie's checks are grounded in empirical findings published in *Tokens Not Jokin'*. Key results:

- YAML uses up to 80% fewer tokens than OpenAPI 3.0 JSON
- Documentation format explains more than 10x the variance in generated code quality than model choice
- Disciplined error documentation produces dramatically better error handling in generated code

The Sample Generation check uses the same methodology as TNJ, applied per-spec: ask an AI to write code from these docs, then show what it produced.

Buy the book: [leanpub.com/tokensnotjokin](https://leanpub.com/tokensnotjokin)

## License

MIT
