# Quotation Workspaces — Design

Date: 2026-11-14
Scope: `personal/profesional/quotations` (Python CLI, `uv run quotation`)

## Intent and why

Today the quotation agent is a single-shot CLI: every run starts from zero, source
documents are passed with repeated `--attachment` flags (long, unwieldy commands),
and nothing survives between runs. If the user stops mid-way, all work is lost.

The user wants each quotation to be a **persistent workspace**:

- A `setup` step creates a folder for the quotation. The user gives a name; the
  agent shortens it when it is too long.
- Inside, a `documentations/` folder is where the user drops draft files. The agent
  reads that folder instead of `--attachment` flags.
- The agent records what it discovers and what the user decides. Resuming a
  quotation continues from where the user left off, reading the session/decision
  summary — **not** re-reading every document.
- The uploaded files are drafts (early, incomplete material).
- A **developer profile** (stack, e.g. Python + React; team members; tools, e.g.
  ClickUp, GitHub; MCPs; conventions) is copied into each project, where it can be
  customized. The agent asks whether to adjust it for this project (projects may be
  collaborative).
- A **specialized profile agent** improves the base profile over time, from two
  sources: what the user tells it changed, and what it learns from past quotations
  (new technologies, new project kinds such as backend, fullstack, AI, n8n).

## Goals

- `uv run quotation setup "<name>"` creates a workspace.
- `uv run quotation resume <workspace>` continues from the last approved phase.
- Documents in `documentations/` are read once; later runs use stored summaries.
- Profile context (stack, tools, MCPs, conventions) guides intake and task
  decomposition.
- `uv run quotation profile` lets the user update the base profile conversationally
  and reviews past quotations for suggestions.

## Non-goals

- No Claude Code slash command or Claude-hosted agent (decided: Python only for now).
- Profile does **not** drive pricing yet (decided: option 1). Hourly rates and the
  3 hours/day policy stay in `rates.py`. The profile reserves an optional, unused
  section for future team rates.
- No multi-user locking or sync; collaboration means sharing the folder (e.g. git).
- No OCR for scanned PDFs (existing limitation stays).

## Anti-goals (failure even if it "works")

- Resume that silently re-reads and re-sends all documents to the LLM.
- The profile agent editing the base profile without explicit user approval.
- Losing approved work because a later phase crashes.
- State files the user cannot read or fix by hand.

## Constraints

- Python ≥ 3.11, `uv`, LangChain 1.x `create_agent` with structured
  `response_format`, Pydantic models, existing provider config (`QUOTATION_*`).
- Existing pricing (`pricing.py`, `rates.py`) and document generation stay as is.
- Source text remains untrusted data, never instructions (existing prompt rule).
- Workspaces contain client data: they must not be committed to this repo.
- Artifacts (code, file contents, prompts) in English.

## Approaches considered

1. **Plain files in the workspace folder** (`notes.md` + `state.json` +
   `profile.md`). Human-readable and editable, git-friendly, shareable with a
   collaborator. Cost: careful validation when loading JSON. — **Chosen by the
   user.**
2. **SQLite per project.** Robust queries, but opaque to the user and to
   collaborators; decisions cannot be edited by hand.
3. **Store full conversation transcripts and summarize on resume.** Nothing lost,
   but it reintroduces re-reading everything on every resume and the token cost
   the user wants to avoid.

## Design

### Workspace layout

```
<workspaces root>/                  default: ./quotes (configurable, see below)
├── _profile/
│   ├── profile.md                  base developer profile (source of truth)
│   └── learned.json                which projects the profile agent already reviewed
└── <project-slug>/
    ├── documentations/             user's draft files (PDF/DOCX/MD/TXT)
    ├── profile.md                  project copy of the profile, editable
    ├── notes.md                    discoveries + decisions log (human-readable)
    ├── state.json                  machine state: phase, approved data, digests
    └── output/                     generated DOCX files
```

- Workspaces root: `--root DIR` flag, else `QUOTATION_WORKSPACES` env var, else
  `quotes/` **anchored to the quotations package directory** (not the current
  working directory), so default runs never drop client data elsewhere in the repo.
  `quotes/` is added to the package `.gitignore`.
- `_profile/` is a reserved name; slugs can never be `_profile`.

### `setup "<name>"`

1. Takes the quotation name from the argument (asks if missing).
2. Builds a slug: lowercase, ASCII, hyphenated. If the slug exceeds ~40
   characters, an LLM summarizes the name into a short slug (2–5 words). The user
   sees the proposed folder name and can accept or type another. Collisions get a
   numeric suffix or a prompt.
3. Creates the layout above; writes `state.json` with `phase: "setup"` and the
   original name; starts `notes.md` with a header.
4. Copies `_profile/profile.md` into the project. If no base profile exists, offers
   to create one from a template (asked interactively).
5. Shows the profile summary and asks: "Adjust anything for this project?" If yes,
   the user describes changes in free text, the LLM proposes edits to the project
   copy, the user approves. Decision recorded in `notes.md`.
6. Tells the user to drop drafts in `documentations/` and run `resume`.

### Document ingestion (read once)

- On `resume`, the agent lists `documentations/` and compares against
  `state.json.documents` (filename + content hash).
- New or changed files are extracted with the existing `attachments.py` loader and
  passed to a **document digest agent** that returns a structured summary
  (requirements, constraints, open questions, technologies mentioned).
- Digests are stored in `state.json` and appended to `notes.md`. Raw extracted text
  is **not** sent again on later runs.
- Downstream agents (intake, decomposition, commercial) receive the digests instead
  of full document text. Unchanged files are never re-read.
- Changed files (same name, new hash) count as new: the new digest replaces the
  old one, and `notes.md` records the update.
- Removed files: their digest is marked removed and excluded (noted in `notes.md`).
- Unsupported or unreadable files: warning, skipped, recorded; the run continues.
- `--attachment` is removed (breaking CLI change; README/USAGE updated).

### `resume <workspace>`

- Loads `state.json` (validated with Pydantic; clear error pointing at the file if
  invalid) and the project `profile.md`.
- Ingests new/changed documents (above).
- Prints a short "where you left off" summary from `notes.md`/`state.json`.
- Continues from the current phase:
  `setup → intake → scope_review → decomposition → pricing → generated`.
- **Checkpoint after every approval**: approved draft, tasks, and quote inputs are
  written to `state.json` immediately, plus a decision entry in `notes.md`. A crash
  or Ctrl+C never loses an approved phase.
- Intake: the client name and project description are asked once and saved; the
  documents' digests feed the requirement inference agent.
- At any review step the user can still go back (existing behavior), and on resume
  can choose to reopen an earlier approved phase (e.g. "re-review tasks").
- If new or changed documents arrive after scope was approved, the agent says so
  and asks whether to reopen scope review.
- **Reopening an earlier phase keeps later work as a draft** (decided by the user):
  e.g. reopening scope keeps the approved tasks as the starting point; the
  decomposition agent revises them against the new scope (reviewer-feedback style)
  and the user re-approves; pricing is then recalculated. Later phases are marked
  stale in `state.json` until re-approved; nothing approved is discarded.
- **Generated quotations are kept as history** (decided by the user): each
  generation writes to a new version folder, `output/v1/`, `output/v2/`, …, never
  overwriting a previous one. Each version folder holds both DOCX files plus a
  `snapshot.json` (approved draft, tasks, quote inputs, totals) so a past version
  can be compared later. `state.json` lists versions with date and total; a
  `notes.md` decision entry records each generation.
- `--project-name` default becomes the workspace's original name. `--language`,
  `--provider-name`, `--dotenv` keep working. `--output` is removed.
- A bare `uv run quotation` (no subcommand) prints help; it no longer runs the old
  single-shot flow.

### `list` and choosing a workspace

- `uv run quotation list` prints a table of all workspaces (excluding `_profile/`):
  original name, folder slug, current phase, last activity date, and latest
  generated version with its total (if any).
- `uv run quotation resume` with no argument shows the same list numbered and asks
  the user to pick one. With an argument, it accepts the folder slug.
- A folder without a valid `state.json` is listed as "invalid" with the reason,
  never silently hidden.

### `notes.md` format

Append-only, dated sections, written by the program (not free LLM prose for
decisions):

```
## 2026-11-14 — Session 2
### Discovered
- requisitos-v1.pdf: <digest bullets>
### Decided
- Scope approved (6 items). Feedback applied: "remove mobile app".
- Tasks approved: 14 tasks, 86 h.
```

Decisions are rendered deterministically from approved data; only document digests
come from the LLM. The user may edit the file by hand; the program only appends.

### Developer profile (`profile.md`)

Markdown with YAML frontmatter so it is both readable and parseable:

```markdown
---
stack: [Python, FastAPI, React]
tools: [ClickUp, GitHub]
mcps: [github, context7]
team:
  - name: Daniel
    role: fullstack
    # rate_per_hour: reserved, not used yet
project_kinds: [backend, fullstack, ai, n8n]
---
## Conventions
Free text the developer wants the agents to know.
```

- Intake and decomposition prompts include the profile (as context, still delimited
  as data) so tasks reflect the actual stack and tools.
- Invalid frontmatter: clear error naming the file and field.

### Profile agent (`uv run quotation profile`)

Operates on the **base** profile (`_profile/profile.md`) only.

- **Told changes**: the user describes what changed in free text; the agent returns
  structured proposed edits (add/remove/change per field or conventions text). Each
  edit is shown and approved individually; only approved edits are written.
- **Learned suggestions**: the agent reads `notes.md`/digests of workspaces not yet
  listed in `_profile/learned.json`, and proposes technologies and project kinds
  that appear there but not in the profile, with evidence ("seen in 2 quotations:
  a, b"). Approved → written. `learned.json` stores, per workspace, a fingerprint
  (hash) of its `notes.md` at review time and the suggestions already shown. A
  workspace is reviewed again only when its fingerprint changes, and suggestions
  already shown (accepted or rejected) are not repeated.
- Never writes without approval. Project copies are never modified by this agent.

## Decided by the user

- Python CLI only (no Claude Code commands yet).
- Profile is LLM context only; pricing stays in `rates.py` (reserved rate field).
- Persistence as plain files in the workspace.
- Profile agent learns from both user input and past quotations.
- Reopening a phase keeps later approved work as a draft to revise, not discard.
- Generated quotations are versioned (`output/vN/`), never overwritten.
- A `list` command shows all quotation projects.

## Calls made by the designer (correctable)

- Command names `setup`, `resume`, `profile`; workspaces root `quotes/` anchored
  to the package dir, gitignored.
- Bare `uv run quotation` prints help; `--output` removed.
- `resume` without argument offers a numbered pick from the workspace list.
- Changed documents count as new; digest replaced, update logged.
- Profile agent re-reviews a workspace when its `notes.md` fingerprint changes.
- Downstream agents use digests instead of full text (follows "don't re-read").
- `--attachment` removed rather than kept alongside the folder.
- Profile format: Markdown + YAML frontmatter.
- Slug length threshold ~40 chars before LLM summarization.

## Left to the builder

- Exact Pydantic schema of `state.json`, digest fields, and module boundaries.
- Hashing method, slug algorithm details, file-locking (none required).
- How existing `cli.py` phase functions are refactored to accept stored state.
- Test strategy details (existing pytest suite + fake models, as today).
