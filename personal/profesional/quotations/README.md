# Quotation Agents

An independent Python package for the software quotation workflow. QA-001
provides validated configuration, commercial policy and rate constants,
editable quotation state, and an injectable provider boundary. QA-002 adds
provider-injected client intake, requirement inference, and explicit human
approval boundaries. QA-003 adds category-specific task decomposition.

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

The policy records that IGV is excluded, three available hours per day, a S/150 floor,
S/10,000 ceiling, S/700 payment threshold, 40% advance rate, and 14-day quote
validity. `CommercialPolicy` rejects a floor above its ceiling; callers may provide a
validated custom policy to calculations.

## State and provider boundary

`QuotationDraft` requires a nonblank client/company and preserves the supplied
original request verbatim. Its inferred scope, assumptions, questions, risks,
approval state, and categorized work items are editable fields. Models reject
unknown fields. The state model does not infer missing requirements or approve
a quote automatically.

`resolve_invocation` accepts an injected callable or a model with an `invoke`
method. It does not construct a provider or make network calls. This keeps
automated tests offline; live provider construction belongs to a later task.

## QA-002 intake and approval

Requirement inference is represented separately from `QuotationDraft`:
`RequirementInference` contains only editable inferred scope, assumptions,
questions, and risks. Unknown fields are rejected, so a provider response cannot
approve a draft or replace its original request.

Pass a callable, model, or already-created agent explicitly to `intake_draft`:

```python
from quotation_agents import (
    approve_draft,
    intake_draft,
    require_approved_draft,
    revise_draft,
)


def offline_inference(request):
    return {
        "structured_response": {
            "inferred_scope": ["Booking flow"],
            "assumptions": ["Payment provider is not selected"],
            "questions": ["Which provider should be used?"],
            "risks": ["Payment requirements may change"],
        }
    }


draft = intake_draft("Example Ltd", "Build a booking site", invoke=offline_inference)
approved = approve_draft(draft)
require_approved_draft(approved)  # Safe boundary for later proposal generation.
draft_again = revise_draft(approved, inferred_scope=["Booking flow", "Checkout"])
assert draft_again.approval_state.value == "pending"
```

`intake_draft` validates the client/company and preserves the exact original
request. It always returns `ApprovalState.PENDING`, regardless of provider
output. `approve_draft` is the explicit human approval step; `revise_draft`
returns an edited copy and resets approval to pending without changing the
original request. `require_approved_draft` raises
`DraftApprovalRequiredError` for pending drafts.

`create_requirement_inference_agent(model)` follows the LangChain 1.x
`create_agent(..., response_format=RequirementInference)` convention. The model
is injected by the caller. The package never constructs a provider, reads
credentials, makes network calls, or invokes a live model implicitly. Tests can
use the same `invoke` contract with an offline callable or fake model.

## QA-003 task decomposition

`decompose_category` accepts only an approved `QuotationDraft` and decomposes
one explicit `WorkCategory`: planning and coordination, backend, frontend, or
DevOps. The provider must return a structured `TaskDecomposition` containing
`QuotationTask` values. Unknown fields, malformed tasks, invalid categories,
and tasks assigned to a different category are rejected; an empty task list is
valid when that category has no applicable work.

The decomposition request preserves the exact client/company and
`original_request` values, plus the editable intake analysis. Source data is
wrapped in explicit untrusted-input delimiters and is never treated as
instructions. Use an injected callable, model, or prebuilt agent; no provider
is constructed and no credentials or network calls are used implicitly.

Decomposition does not mutate or approve the input draft. Apply returned tasks
with `revise_draft(approved, tasks=result.tasks)` when appropriate; revision
intentionally resets the draft to `ApprovalState.PENDING`, so it must be
approved again before downstream proposal work.

## QA-004 effort and pricing

`estimate_effort` consumes the editable `QuotationTask.estimated_hours` values. Every
task must have a positive Decimal estimate. It sums hours by category, calculates each
category subtotal as `hours * hourly_rate`, rounds each subtotal with Decimal
`ROUND_HALF_UP`, and sums those subtotals into `raw_amount`. Calendar days are
`ceil(total_hours / 3)`; the three hours/day assumption is controlled by
`CommercialPolicy.available_hours_per_day`.

`calculate_quote` accepts only an approved `QuotationDraft`, returns a new
`QuoteResult`, and never mutates the draft. Its editable `QuoteInputs` are explicit:

```text
raw       = sum(category subtotals)
minimum   = raw
ideal     = raw * complexity_factor * dependency_factor
maximum   = ideal * risk_factor * (1 + contingency_rate)
selected  = selected band, or custom_amount when supplied
```

All monetary results are rounded with `ROUND_HALF_UP`. Defaults are
`complexity_factor=1.00`, `dependency_factor=1.00`, `risk_factor=1.00`, and
`contingency_rate=0.00`, so no hidden commercial contingency is added. The raw amount
is retained separately. Factors are editable and are deliberately explicit rather
than inferred from provider output.

The effective floor is applied only as a minimum (`max(selected, floor)`), so the raw
amount is not lost. A value exactly at S/10,000 is valid. A value above the ceiling is
never clipped: `ceiling_exceeded`, `requires_modularization`, and
`manual_approval_required` are set to `True` so a human can approve a modular/manual
commercial decision.

## QA-004 modules and payments

`split_modules` accepts a mapping or `ModuleSpec` values containing zero-based task
indexes. It rejects blank/empty modules, duplicate module names, duplicate task
assignments, unassigned tasks, and invalid indexes. It returns the original task
category and description in deterministic module order; it does not mutate tasks.

Below S/700, the schedule contains exactly one `Full project` payment. At or above
S/700, it contains a 40% `Advance` and the remaining balance is allocated by module
raw effort (or one `Project completion` milestone when modules are absent). Decimal
cent rounding residuals are assigned deterministically and every schedule reconciles
exactly to the selected quote amount.

## Current limits

This package does not implement persistence, CLI behavior, automatic approval,
provider construction, or DOCX/PDF generation. Quote inputs/results are in-memory
Pydantic models; revise editable draft tasks with `revise_draft`, then approve again
before downstream calculations. No calculation silently approves a draft or creates
a proposal document.
