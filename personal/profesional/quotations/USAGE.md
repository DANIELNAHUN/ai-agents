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

## Quotation workspaces

Each quotation lives in its own folder, so you can stop at any time and continue later
without starting from zero. From inside `personal/profesional/quotations/`:

```bash
uv run quotation setup "Sistema de Campañas Cableclub"   # create a workspace
uv run quotation list                                    # see all your quotations
uv run quotation resume sistema-de-campanas-cableclub    # continue where you left off
uv run quotation profile                                 # improve your developer profile
```

Every command accepts `--root DIR` (workspaces folder) and `--dotenv FILE`. Without
`--root`, workspaces go to `$QUOTATION_WORKSPACES`, or to `quotes/` inside this package
(git-ignored, because it holds client data). Running `uv run quotation` alone prints help.

### Workspace layout

```
quotes/
├── _profile/
│   ├── profile.md          # your base developer profile
│   └── learned.json        # which quotations the profile agent already reviewed
└── sistema-de-campanas-cableclub/
    ├── documentations/     # drop your draft files here (PDF, DOCX, MD, TXT)
    ├── profile.md          # this project's editable copy of your profile
    ├── notes.md            # what the agent discovered and what you decided
    ├── state.json          # where you left off (phase, approved data, digests)
    └── output/             # generated quotations, one folder per version
```

### setup

`setup` asks for the quotation name when you omit it and proposes a folder name. Names
whose folder name would exceed 40 characters are summarized by the model; you can accept
the proposal or type another. An existing folder gets a numeric suffix (`crm-2`).

The base profile is copied into the workspace. If you have none yet, setup offers to create
one from a template. Setup then shows the profile and asks whether to adjust anything for
this project (useful for collaborative projects): describe the change, and approve each edit
the agent proposes. Only the project copy changes; decisions are logged in `notes.md`.

### Developer profile

`profile.md` is Markdown with YAML frontmatter, editable by hand:

```markdown
---
stack: [Python, FastAPI, React]
tools: [ClickUp, GitHub]
mcps: [github, context7]
project_kinds: [backend, fullstack, ai, n8n]
team:
- name: Daniel
  role: fullstack
---
## Conventions
Free text the agents should know.
```

The profile guides requirement inference and task decomposition (technologies, tools,
conventions). It does not change pricing: hourly rates stay in `rates.py`. A team member's
optional `rate_per_hour` is stored for the future but not used yet.

### list

`list` shows every workspace with its name, phase, last activity, and latest generated
version and total. Folders with a missing or broken `state.json` are shown as `invalid`
with the reason, so you can fix them by hand.

### resume

`resume` continues a quotation from its last checkpoint. Without a folder name it shows your
quotations numbered so you can pick one. Each run is a new session in `notes.md`:

1. New or changed files in `documentations/` are summarized (unchanged files are never read
   again; a file that fails to summarize is retried next time).
2. A short "where you left off" summary is printed from `state.json`.
3. The workflow continues from the current phase: intake → scope review → task decomposition
   → pricing → generation.

Every approval is saved immediately, so quitting (or Ctrl+C) never loses approved work. The
next `resume` starts where you stopped.

When the scope is already approved, `resume` offers a menu:

| Option | Effect |
|---|---|
| `c` Continue | Go on from the current phase (hidden once a version is generated) |
| `s` Reopen scope | Review the scope again; approved tasks are kept as a draft, revised by the agents against the new scope, and shown to you for approval; pricing is recalculated |
| `t` Reopen tasks | Review the approved tasks again, then re-price |
| `p` Re-price | Recalculate the quote and generate a new version |
| `q` Quit | Stop without changes |

If new or changed documents arrived after the scope was approved, `resume` asks whether to
reopen the scope review first.

`--language`, `--provider-name`, and `--project-name` (default: the workspace name) apply
to the generated documents.

### Draft documents

Supported files are PDF, DOCX, Markdown, and UTF-8 TXT. Each file is read once and
summarized into a digest stored in `state.json` and `notes.md`; later runs reuse the
digests instead of re-reading the files. Scanned PDFs need OCR first. Document text is
treated as source material, not as agent instructions.

### Progress output

Every LLM step prints which agent is running, its live status, and a one-line summary:

```
  ▸ Requirement inference agent · gpt-4o-mini
    ⠹ waiting for model (call 1)... 12s
  ✔ Requirement inference agent · gpt-4o-mini · 14.3s · 1 model call · 5,312 in / 812 out tokens
```

Each phase uses one specialized agent (inference, one decomposition agent per category, and
commercial synthesis). The status shows model calls and tool calls; the model's internal
reasoning is not exposed. On a terminal the status is a single spinner line updated in place;
when output is redirected, each status change is printed once. Consoles that cannot render the
symbols fall back to ASCII (`>`, `OK`, `FAIL`).

If a step keeps waiting with large documents, raise `QUOTATION_HTTP_TIMEOUT_SECONDS`
(default 15, maximum 120) in `.env`.

### Reviewing and correcting

Each checkpoint offers a menu instead of a yes/no question:

| Checkpoint | Options |
|---|---|
| Scope (phase 2) | `a` approve · `r` revise with feedback (the inference agent reruns with your comment and its previous result) · `q` quit |
| Tasks (phase 3) | `a` approve · `e` edit the hours of one task · `r` revise one category with feedback · `g` revise all categories with the same feedback · `q` quit |
| Quote (phase 4) | `a` accept · `b` back to tasks to adjust and recalculate · `q` quit |

Tasks cannot be approved while any task lacks estimated hours. Edited hours must be a
plain positive number (`6`, `2.5`, or `2,5`); forms such as `1e3` are rejected. If pricing
cannot be calculated, the CLI returns to task review instead of exiting.

The category menu marks categories without tasks as `(no tasks)`; you can still pick one
and ask its agent to add work. Approving while any category is empty asks for explicit
confirmation, because the quote would include no work for it.

With `g`, every category agent reruns with the same feedback and its own numbered tasks;
agents whose category the feedback does not concern return their tasks unchanged. If one
agent fails, that category keeps its previous tasks and the others are still updated.

Feedback can refer to tasks by the numbers shown in the list (for example "14. takes 3
hours, remove 17."); the agent receives the previous tasks with those same numbers. If an
agent fails, for example by returning an invalid estimate, the CLI shows the error, keeps the
previous result, and returns to the menu so you can retry, edit hours, or approve.

### Output files

Each generation writes a new version folder and never overwrites an earlier one:
`output/v1/`, `output/v2/`, … Every version folder contains:

| File | Audience | Content |
|---|---|---|
| `quotation-internal.docx` | You | Full technical breakdown: tasks, hours per category, pricing bands, assumptions, risks |
| `quotation-commercial.docx` | Client | Business-language summary: modular components, cost table, payment milestones, deliverables |
| `snapshot.json` | You | Approved scope, tasks, and quote behind this version, for comparing versions |

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
│   ├── cli.py           # Interactive workflow phases
│   ├── workspace_cli.py # Entry point: setup, list, resume, profile
│   ├── workspace.py     # Workspace folders, names and listing
│   ├── state.py         # state.json model (phase, approved data, digests)
│   ├── notes.py         # Append-only notes.md log
│   ├── ingestion.py     # Document digests, read once
│   ├── profile.py       # Developer profile file format
│   ├── profile_agent.py # Profile edit and learning agents
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
