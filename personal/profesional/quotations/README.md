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
| `QUOTATION_PROVIDER` | `openai` | OpenAI-compatible provider: `openai`, `ollama`, `omniroute`, or `freellm` |
| `QUOTATION_MODEL` | `gpt-4o-mini` | Configured model name |
| `QUOTATION_BASE_URL` | Provider-dependent | HTTP(S) endpoint; optional for OpenAI, defaulted for Ollama, required for OmniRoute and FreeLLM |
| `QUOTATION_API_KEY` | Provider-dependent | Generic secret key, taking precedence over provider-specific fallbacks |
| `QUOTATION_HTTP_TIMEOUT_SECONDS` | `15` | Positive request timeout, up to 120 seconds |

Provider-specific key fallbacks are `OPENAI_API_KEY`, `OLLAMA_API_KEY`,
`OMNIROUTE_API_KEY`, and `FREELLM_API_KEY`. Ollama does not require a real key;
the model factory uses the harmless local sentinel `ollama` when no key is set.
Provider names are case-insensitive and common forms such as `omni-route` and
`free-llm` are normalized.

The provider matrix is:

| Provider | Adapter | Base URL | API key |
| --- | --- | --- | --- |
| `openai` | `langchain-openai` / `ChatOpenAI` | Optional; the adapter default is used when omitted | `QUOTATION_API_KEY` or `OPENAI_API_KEY` required by the factory |
| `ollama` | `langchain-openai` / `ChatOpenAI` | Defaults to `http://localhost:11434/v1` | Optional; uses `ollama` locally when omitted |
| `omniroute` | `langchain-openai` / `ChatOpenAI` | Explicit `QUOTATION_BASE_URL` required | `QUOTATION_API_KEY` or `OMNIROUTE_API_KEY` |
| `freellm` | `langchain-openai` / `ChatOpenAI` | Explicit `QUOTATION_BASE_URL` required | `QUOTATION_API_KEY` or `FREELLM_API_KEY` |

For a local setup, copy the example and edit only the local file:

```bash
copy .env.example .env  # PowerShell/cmd on Windows; use cp on Unix
```

`.env` is ignored by this package and MUST NEVER be committed. Use placeholders
in `.env.example`, and never print or log API keys.

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
automated tests offline. `create_configured_model` is the explicit opt-in
factory for constructing a `ChatOpenAI` model from `QuotationConfig`, `.env`,
or process environment settings; construction itself does not invoke the
endpoint.

Manual live smoke test (run only when the configured endpoint and credentials
are available):

```python
from quotation_agents import create_configured_model

model = create_configured_model()
response = model.invoke("Reply with exactly: quotation provider is reachable")
print(response.content)
```

This snippet is intentionally not part of the automated suite and can contact
the configured provider. Keep credentials in the ignored local `.env` or a
secret manager, not in source control.

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
`QuoteResult` with a deterministic SHA-256 `source_draft_fingerprint`, and never
mutates the draft. Its editable `QuoteInputs` are explicit:

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

## QA-005 proposal documents

`generate_proposal_documents` is the only document-generation entry point. It requires an
`ApprovalState.APPROVED` `QuotationDraft` and an existing deterministic `QuoteResult` whose
`source_draft_fingerprint` matches the supplied draft; it does not infer, approve, or
recalculate either value. The DOCX preserves the client/company,
original request, interpreted scope, categorized tasks, three-hour calendar days, category
rates/subtotals, quote bands, selected amount, payment milestones, assumptions, risks, and
questions. It also states that IGV is excluded, validity is 14 calendar days, and the three
separate-charge exclusions are adjustments, new functionality outside approved requirements,
and server migrations. Amounts above S/10,000 remain visible and disclose modularization and
manual approval.

```python
from quotation_agents import generate_proposal_documents, libreoffice_pdf_converter

documents = generate_proposal_documents(
    approved_draft,
    quote_result,
    "out/quotations",
    filename="booking-proposal",
    pdf_converter=libreoffice_pdf_converter,  # Optional local PDF conversion
)
print(documents.docx_path, documents.pdf_path, documents.docx_validation)
```

Output names are deterministic and existing files are protected unless `overwrite=True` is
explicitly passed. PDF conversion is injectable, so tests can use a fake converter without
LibreOffice. The default package does not invoke LibreOffice implicitly; when real conversion
is desired, `soffice` must be installed and available on `PATH`. `validate_docx` and
`validate_pdf` provide dependency-free structural checks for generated outputs.

## QA-006 review and operational workflow

Use this order for an offline quotation run:

1. Intake the client/company and original request with `intake_draft`.
2. Review or edit inferred scope, assumptions, questions, risks, and tasks; approve the draft.
3. Decompose approved work by category when needed, then revise and approve again.
4. Calculate effort and pricing, optionally splitting tasks into modules.
5. Run `review_quote(approved_draft, quote)` before document generation.
6. Generate the DOCX (and optionally an injected PDF) only after the review gate passes;
   `generate_proposal_documents` invokes the same review gate before writing output.

The review is deterministic and provider-free. It checks that the approved scope and quote
fingerprint match, effort and category arithmetic reconcile, scope notes are nonblank, the
selected band/floor/ceiling flags are coherent, and payment rules reconcile. `passed=False`
means an error must be corrected, and document generation rejects those error finding codes
before creating files. Warnings are returned separately and remain explicit in the workflow and
generated document; open questions make `ready_for_document=False`. A quote above S/ 10,000 can
still pass arithmetic review and remain renderable as an approval request, but
`requires_manual_approval=True` and `ready_for_document=False`: retain the full amount,
modularize delivery, and obtain the required human exception approval rather than clipping it.

Representative focused verification from this directory:

```bash
uv run pytest tests/test_review.py tests/test_scenarios.py
```

The package has no CLI and does not make live provider calls in tests. PDF output remains
optional: inject a converter for tests, or pass `libreoffice_pdf_converter` when `soffice` is
installed and available on `PATH`. DOCX structural validation is always performed locally.

## Current limits

This package does not implement persistence, CLI behavior, automatic approval, or provider
construction. Quote inputs/results and proposal documents are in-memory/domain outputs; revise
editable draft tasks with `revise_draft`, then approve again before downstream calculations or
document generation. No calculation or document call silently approves a draft.
