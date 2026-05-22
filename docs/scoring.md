# artie scoring rubric

This document describes every score artie produces: the thresholds, the
buckets, the weightings, and — honestly — which of them rest on the *Tokens
Not Jokin'* (TNJ) data versus which are heuristics awaiting empirical
calibration.

**Scoring version: 1.0** (`artie.SCORING_VERSION`, mirrored in
`pyproject.toml [tool.artie]` and emitted in JSON output as `scoring_version`).

## How to read this

artie runs eight checks. Seven produce a 0–10 score; one (Sample Generation)
is informational and produces none. A run does **not** produce an aggregate
score — see "Why there is no aggregate score" at the end.

> **Calibration status.** The static-check *structure* (what each check
> measures) is grounded in TNJ. The exact *numbers* — the format scores, the
> depth buckets, the 15-character description floor, the equal sub-score
> weightings — are reasoned heuristics, not yet validated against
> code-generation outcomes. Calibrating them against the TNJ corpus is
> tracked as planned work. Where a threshold is a heuristic, this document
> says so. Treat scores as directional, not as measurements, until
> `scoring_version` reaches 2.0.

## Severity bands

Every scored check maps its 0–10 score to a severity band (`base.py`,
`severity_for`). Bands are a fixed ratio of score to max:

| Band       | Ratio of score/max | 0–10 score |
|------------|--------------------|------------|
| excellent  | ≥ 0.90             | 9–10       |
| good       | ≥ 0.70             | 7–8        |
| needs_work | ≥ 0.40             | 4–6        |
| poor       | < 0.40             | 0–3        |

*Basis: heuristic.* The bands are conventional lint-style cutoffs, not
derived from TNJ.

## Format Efficiency

Scores the documentation format itself, before any content analysis
(`format_efficiency.py`, `FORMAT_SCORES`).

| Format               | Score |
|----------------------|-------|
| OpenAPI YAML / YAML   | 10    |
| DON                   | 9     |
| Markdown              | 7     |
| OpenAPI JSON / JSON   | 5     |
| HTML                  | 1     |
| unknown               | 5     |

*Basis: TNJ finding, heuristic numbers.* TNJ established that format choice
explains far more variance in generation quality than model choice, and that
YAML uses up to ~80% fewer tokens than OpenAPI 3.0 JSON. The **ordering**
(YAML > DON > Markdown > JSON > HTML) follows from that finding. The **exact
points** (why JSON is 5 and not 4 or 6) are a heuristic spacing, calibration
pending.

The cost-to-read figures in the findings use retail input pricing and are
ballpark only — real-world cost is typically 10–100× lower once prompt
caching, batch pricing, or enterprise discounts apply. They are there to make
token differences tangible, not to be read as invoices.

## Endpoint Completeness

Three sub-scores, each a 0.0–1.0 ratio, **averaged with equal weight** and
scaled to 0–10 (`endpoint_completeness.py`):

1. Fraction of operations with a `description` or `summary`.
2. Fraction of operations with an `operationId`.
3. Fraction of path parameters carrying a `description`.

If the spec has no path parameters, sub-score 3 is dropped and the average is
over the remaining two.

*Basis: TNJ for the signals, heuristic for the weighting.* Descriptions,
operationIds, and documented path parameters are all things TNJ showed agents
rely on. Whether they deserve **equal** weight is a heuristic; calibration
pending.

## Example Coverage

Two sub-scores, equally weighted, scaled to 0–10
(`example_coverage.py`):

1. Fraction of operations with a response example (in a 2xx response, at the
   media-type `example`/`examples` level or the schema `example`).
2. Fraction of operations *that accept a request body* with a request
   example.

If no operation accepts a request body, sub-score 2 is dropped.

*Basis: TNJ.* TNJ identified examples as the strongest single predictor of
correct generated code. The equal weighting of request vs response examples
is a heuristic.

## Error Documentation

Three sub-scores, equally weighted, scaled to 0–10
(`error_documentation.py`):

1. Fraction of operations documenting at least one `4xx`, `5xx`, or
   `default` response.
2. Fraction of those error responses with a description of at least
   **15 characters** (`MEANINGFUL_DESCRIPTION_CHARS`).
3. Fraction of those error responses with a content schema.

If a shared `Error`-style schema exists in `components.schemas`, sub-score 3
gets a **+0.2 bump** (capped at 1.0).

*Basis: TNJ for the signal, heuristic for the numbers.* TNJ Chapter 5 tied
disciplined error documentation to high try/except adoption in generated
code. The 15-character description floor and the +0.2 shared-schema bump are
heuristics — 15 characters is roughly "longer than `bad request`" and the
bump rewards a real positive pattern, but neither number is calibrated.

The shared-schema detector matches case-insensitive names `error`,
`errorresponse`, `errorbody`, `apierror`, `problem`, `problemdetails`.

## Auth Clarity

Three sub-scores, equally weighted, scaled to 0–10 (`auth_clarity.py`):

1. Whether at least one security scheme is defined (1.0 or 0.0).
2. Fraction of schemes that are "described".
3. Fraction of operations whose security posture is documented (explicit
   `security`, including `security: []`, or an inherited top-level
   requirement).

A scheme counts as "described" if it has a description of at least
**10 characters**, or its `type` is self-documenting (`http`, `apiKey`,
`openIdConnect`).

Special case: if nothing anywhere mentions security, the check scores 0 and
explains it cannot tell a genuinely public API from an undocumented one.

*Basis: TNJ for the signals, heuristic for the numbers.* The 10-character
description floor and the equal weighting are heuristics.

## Parameter Naming

A single ratio: `count of the most common convention / total
convention-bearing names`, scaled to 0–10 (`parameter_naming.py`).

Conventions recognized: `snake_case`, `camelCase`, `PascalCase`,
`kebab-case`. Single-word lowercase names are **ambiguous** (compatible with
several conventions) and are excluded from scoring entirely. Names matching
no convention count against the total.

The score rewards **consistency**, not any particular convention — a fully
camelCase API and a fully snake_case API both score 10.

*Basis: heuristic.* TNJ supports "consistency helps agents"; the linear
consistency-to-score mapping is a heuristic.

## Schema Complexity

Scores the **maximum** nesting depth across `components.schemas` against
fixed buckets (`schema_complexity.py`, `DEPTH_BUCKETS`):

| Max nesting depth | Score |
|-------------------|-------|
| ≤ 3               | 10    |
| ≤ 5               | 8     |
| ≤ 7               | 5     |
| ≤ 9               | 3     |
| > 9               | 1     |

*Basis: TNJ observation, heuristic buckets.* TNJ observed that most
well-shaped APIs sit at depths 3–5 and that depth beyond ~8 correlates with
worse generated code. The **bucket edges** (3/5/7/9) and the **scores**
(10/8/5/3/1) are a heuristic translation of that observation and are a prime
candidate for empirical calibration — see below.

## Sample Generation (informational, no score)

Sample Generation is **opt-in** (`--with-generation`, or `--differential`)
and is **not scored**. An AI model is asked to write a Python function from
the docs; the generated code is the deliverable. The check reports five
structural observations as commentary, never summed into a grade:

1. Parses as valid Python.
2. Imports an HTTP client (`requests`, `httpx`, `urllib`, `aiohttp`).
3. Includes error handling.
4. Constructs an HTTP request.
5. Handles the response.

It is unscored on purpose: one generation against one model is a sample, not
a measurement, and the model's training-data familiarity with the API
confounds it.

**Differential mode** adds a second generation with no docs (the "baseline").
If the baseline is structurally strong — internal threshold
`CONTAMINATION_THRESHOLD = 7` on a legacy 0–10 structural scale — artie emits
a **contamination warning**: the model already knows this API, so the
docs-informed sample reflects model capability, not docs quality. This
internal 0–10 figure exists only to trip that warning; it is never shown as a
grade.

## Why there is no aggregate score

artie deliberately does not roll the seven checks into one number. Doing so
honestly requires knowing how much each check actually predicts
code-generation outcomes — i.e. empirically calibrated weights. Until the
thresholds above are calibrated against the TNJ corpus, any aggregate would
imply a precision artie does not have. A weighted aggregate is a planned
feature once calibration is done; it will arrive with a `scoring_version`
bump.

## Versioning

`scoring_version` changes whenever any threshold, bucket, or weighting in
this document changes. JSON output carries it so consumers can detect when
two runs are not comparable. When comparing runs with `--baseline`, artie
warns if the baseline's `scoring_version` differs from the current one.

The runtime source of truth is `artie.SCORING_VERSION`; `pyproject.toml`
`[tool.artie] scoring_version` mirrors it, and `tests/test_scoring_version.py`
asserts the two stay in sync.

## Configuring thresholds (`.artie.toml`)

Per-check pass/fail thresholds, ignored checks, and default flags live in a
`.artie.toml` file discovered from the working directory upward (or passed
with `--config`). See `.artie.toml.example` in the repository root for the
full schema. Per-check thresholds there take precedence over the global
`--fail-under` flag.
