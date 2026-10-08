# Quotation Agents

An independent Python package for the software quotation workflow. QA-001
provides validated configuration, commercial policy and rate constants,
editable quotation state, and an injectable provider boundary.

## Quick path

From this directory:

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

Python 3.11 or newer and `uv` are required. The package has its own
`pyproject.toml` and lockfile; it is not part of a repository-root workspace.

## Configuration

Copy `.env.example` to `.env` when local settings are useful. `load_config`
reads that file by default, then applies process environment variables, which
take precedence. It also accepts an explicit dotenv path and an injected
environment mapping for tests.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUOTATION_MODEL` | `gpt-4o-mini` | Configured model name |
| `QUOTATION_HTTP_TIMEOUT_SECONDS` | `15` | Positive request timeout, up to 120 seconds |

Do not put provider keys in `.env`; set `OPENAI_API_KEY` in the process
environment or use a secret manager.

## Commercial defaults

Rates and policy values are centralized in `quotation_agents.rates`. Monetary
values use `Decimal`; `quantize_money` rounds to two decimal places with
`ROUND_HALF_UP`. Hourly rates are fixed policy constants, not configuration
overrides.

| Category | Rate per hour |
| --- | ---: |
| Planning and coordination | S/10 |
| Backend | S/30 |
| Frontend | S/20 |
| DevOps | S/15 |

The policy also records that IGV is excluded, three available hours per day, a S/150 floor,
S/10,000 ceiling, S/700 payment threshold, 40% advance rate, and 14-day quote
validity. These are inputs for later workflow tasks; this package does not yet
calculate prices, payment schedules, or proposal documents.

## State and provider boundary

`QuotationDraft` requires a nonblank client/company and preserves the supplied
original request verbatim. Its inferred scope, assumptions, questions, risks,
approval state, and categorized work items are editable fields. Models reject
unknown fields. The state model does not infer missing requirements or approve
a quote automatically.

`resolve_invocation` accepts an injected callable or a model with an `invoke`
method. It does not construct a provider or make network calls. This keeps
automated tests offline; live provider construction belongs to a later task.

## QA-001 limits

This bootstrap does not implement requirement inference, task decomposition,
effort or price calculation, payment rules, human approval flow, persistence,
CLI behavior, or DOCX/PDF generation. In particular, no ideal-price formula or
contingency rule is defined here.
