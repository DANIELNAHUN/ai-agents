# Quotation Agents — Usage Guide

A two-output quotation workflow: one internal technical proposal (for you) and one client-facing commercial proposal (Cableclub format, for the client).

## Architecture overview

```
Project description
        │
        ▼
┌────────────────────┐
│  Phase 1 — Intake  │  LLM infers scope, assumptions, risks, questions
└────────┬───────────┘
         │  ← Your approval
         ▼
┌─────────────────────────────┐
│  Phase 2 — Scope review     │  You confirm or abort
└────────┬────────────────────┘
         │  ← Approved
         ▼
┌──────────────────────────────────┐
│  Phase 3 — Technical decomp.     │  LLM breaks down Backend / Frontend / DevOps / Planning tasks with hours
└────────┬─────────────────────────┘
         │  ← Your approval
         ▼
┌──────────────────────────────────┐
│  Phase 4 — Pricing               │  Deterministic: min / ideal / max in PEN, payment schedule
└────────┬─────────────────────────┘
         │  ← Your approval
         ▼
┌────────────────────────────────────────────────────┐
│  Phase 5 — Two DOCX files generated                │
│   quotation-internal.docx   → for you (technical)  │
│   quotation-commercial.docx → for the client        │
└────────────────────────────────────────────────────┘
```

## Prerequisites

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) installed
- An LLM provider API key (OpenAI, Ollama, or compatible)

## Setup

### 1. Install dependencies

```bash
cd personal/profesional/quotations
uv sync
```

### 2. Configure credentials

Create a `.env` file in `personal/profesional/quotations/`:

**OpenAI (recommended for production):**
```env
QUOTATION_PROVIDER=openai
QUOTATION_MODEL=gpt-4o-mini
QUOTATION_API_KEY=sk-...
```

**Ollama (local, no cost):**
```env
QUOTATION_PROVIDER=ollama
QUOTATION_MODEL=llama3.2
QUOTATION_BASE_URL=http://localhost:11434/v1
```

**Custom OpenAI-compatible endpoint:**
```env
QUOTATION_PROVIDER=omniroute
QUOTATION_MODEL=your-model-name
QUOTATION_BASE_URL=https://your-endpoint/v1
QUOTATION_API_KEY=your-key
```

> **Note:** The `.env` file is gitignored. Never commit credentials.

---

## Running the interactive CLI

From inside `personal/profesional/quotations/`:

```bash
# Default: saves to ./proposals/ in Spanish
uv run quotation

# Custom output directory
uv run quotation --output ./out/proposals

# Set the project name in the commercial proposal
uv run quotation --project-name "Sistema de Campañas Cableclub"

# Set your name as provider
uv run quotation --provider-name "Daniel Calcina"

# Use a specific .env file
uv run quotation --dotenv /path/to/.env

# Internal proposal language: es (default) or en
uv run quotation --language es

# Add requirement documents as context (repeat --attachment for each file)
uv run quotation --attachment .\requirements.pdf --attachment .\scope.docx

# All options combined
uv run quotation \
  --output ./proposals \
  --project-name "Sistema de Campañas" \
  --provider-name "Daniel Calcina" \
  --language es
```

Attachments support PDF, DOCX, Markdown, and UTF-8 TXT files. The CLI extracts their
text locally and sends it to the configured model during intake and task decomposition.
Scanned PDFs need OCR before attachment. The document text is treated as source material,
not as agent instructions.

### Output files

| File | Audience | Content |
|---|---|---|
| `quotation-internal.docx` | You | Full technical breakdown: tasks, hours per category, pricing bands, assumptions, risks |
| `quotation-commercial.docx` | Client | Business-language summary: modular components, cost table, payment milestones, deliverables |

---

## Using the package in a custom script

You can wire up the workflow yourself without using the CLI:

```python
from quotation_agents import (
    approve_draft,
    calculate_quote,
    create_configured_model,
    decompose_category,
    generate_commercial_proposal_documents,
    generate_proposal_documents,
    intake_draft,
    review_quote,
    revise_draft,
    split_modules,
    synthesize_commercial_proposal,
    WorkCategory,
)

# 1. Load the configured LLM model
model = create_configured_model()  # reads from .env or environment

# 2. Intake: infer requirements from the client description
draft = intake_draft(
    "Cableclub",
    "Sistema web para gestionar campañas de beneficios a clientes de TV e Internet...",
    model=model,
)

# 3. Review and approve the scope (in a real workflow, you show this to the user first)
print(draft.inferred_scope)
print(draft.assumptions)
draft = approve_draft(draft)

# 4. Decompose into technical tasks per category
all_tasks = []
for category in WorkCategory:
    decomposition = decompose_category(draft, category, model=model)
    all_tasks.extend(decomposition.tasks)

draft = approve_draft(revise_draft(draft, tasks=all_tasks))

# 5. (Optional) Group tasks into business modules for the payment schedule
modules = split_modules(
    draft.tasks,
    {
        "Base de Datos y ETL": [0, 1],
        "Backend API completo": [2, 3, 4],
        "Frontend Asesor + Supervisor": [5, 6],
        "Frontend Admin + Deploy": [7, 8],
    },
)

# 6. Calculate the quote
quote = calculate_quote(draft, modules=modules)
print(f"Total: S/ {quote.selected_amount}")
print(f"Hours: {quote.effort.total_hours}")

# 7. Review the quote before generating documents
review = review_quote(draft, quote)
assert review.ready_for_document, [i.message for i in review.errors]

# 8. Generate the internal technical proposal
generate_proposal_documents(
    draft,
    quote,
    output_dir="./proposals",
    filename="quotation-internal",
    language="es",
    overwrite=True,
)

# 9. Synthesize the client-facing commercial proposal
commercial = synthesize_commercial_proposal(
    draft,
    quote,
    project_name="Sistema de Campañas y Beneficios Cableclub",
    provider_name="Daniel Calcina",
    modules=modules,
    model=model,             # omit for deterministic fallback (no LLM call)
)

generate_commercial_proposal_documents(
    commercial,
    output_dir="./proposals",
    filename="quotation-commercial",
    overwrite=True,
)
```

### Deterministic commercial proposal (no extra LLM call)

If you want to skip the synthesis LLM call and build the commercial proposal directly from the quote data (faster, no token cost):

```python
from quotation_agents import build_commercial_proposal_from_quote

commercial = build_commercial_proposal_from_quote(
    draft,
    quote,
    project_name="Sistema Cableclub",
    provider_name="Daniel Calcina",
    modules=modules,
    discount=Decimal("300.00"),  # optional commercial discount in PEN
)
```

---

## Commercial rates (PEN/hour)

| Category | Rate |
|---|---|
| Planning and coordination | S/ 10 |
| Backend | S/ 30 |
| Frontend | S/ 20 |
| DevOps | S/ 15 |

## Commercial rules

- **Floor:** S/ 150 minimum per proposal.
- **Ceiling:** S/ 10,000 per proposal or module. Above this, modularization or manual approval is required.
- **Payment threshold:** Projects at or above S/ 700 split into a 40% advance + module payments. Below S/ 700 = one payment.
- **Validity:** 14 calendar days.
- **IGV:** Not included.
- **Exclusions:** Cloud/hosting, scope changes after approval, new modules, third-party integrations not specified.

---

## Running the tests

```bash
uv run pytest
```

All 112 tests must pass before committing.

```bash
# Linter
uv run ruff check .

# Syntax validation
python -m compileall src tests
```

---

## Project structure

```
quotations/
├── src/quotation_agents/
│   ├── cli.py           # Interactive CLI entry point
│   ├── commercial.py    # Commercial proposal models + synthesis agent
│   ├── config.py        # Provider configuration (.env loading)
│   ├── decomposition.py # LLM-powered task decomposition per category
│   ├── documents.py     # DOCX/PDF generation (internal + commercial)
│   ├── inference.py     # LLM-powered requirement inference
│   ├── models.py        # Core domain models (QuotationDraft, QuotationTask, …)
│   ├── pricing.py       # Deterministic pricing, effort, payment schedule
│   ├── provider.py      # Provider-neutral LLM invocation boundary
│   ├── rates.py         # Hourly rates and commercial policy constants
│   ├── review.py        # Deterministic quote review checks
│   └── workflow.py      # Human-gated draft lifecycle (approve, revise, …)
├── templates/
│   ├── proposal_template.json          # JSON Schema for CommercialProposal
│   └── proposal_cableclub_example.json # Real example (Cableclub project)
├── tests/
│   └── test_commercial.py   # Commercial proposal tests
│   └── …
├── pyproject.toml
└── USAGE.md             # This file
```
