# CV Agent Pipeline

## Objective

Build a local, reusable LangChain workflow that reads the canonical professional profile from an Obsidian vault, analyzes job postings quickly, preserves isolated application history, and later generates tailored DOCX/PDF resumes from the real template.

## Problem

The CV workspace currently contains only reference DOCX files. The system needs a persistent profile source, a fast job-fit analysis path, isolated application records, and a document-generation path that can be invoked only when useful.

## Why

Fast gap analysis should not require running CV generation and document validation for every partially matching position. Cross-session facts must come from a durable source rather than transient agent memory.

## Scope

- Read the professional profile from a locally synced Obsidian vault configured through `.env`.
- Extract job-description text from a URL with a text fallback.
- Produce validated structured job requirements and a factual skills-gap analysis.
- Persist each application independently with a stable identifier and source snapshots.
- Generate a tailored CV using `files/templates/Template CV.docx` in a later pipeline stage.
- Convert the generated DOCX to PDF and validate basic output integrity.
- Document setup, configuration, commands, and operational limitations in README.

## Constraints

- `files/templates/Template CV.docx` is the output template.
- `files/templates/Daniel_Nahun_CV.docx` is a reference for content and style expectations only.
- The Markdown profile in Obsidian is the factual source of truth once supplied.
- Do not invent skills, dates, employers, achievements, or technologies.
- Do not store professional content or secrets in `.env`.
- Keep application histories isolated; never merge unrelated job contexts automatically.
- Generated technical artifacts use English.
- TDD mode is not configured in the repository; use standard verification and add focused tests with each behavior.

## Planned tasks

- [x] CV-001 — Bootstrap the standalone CV package, configuration, profile loader, and test harness.
- [x] CV-002 — Implement URL retrieval, HTML/text extraction, and structured job requirements.
- [ ] CV-003 — Implement the fast gap-analysis flow, isolated application persistence, and CLI entry points.
- [ ] CV-004 — Implement tailored CV content generation and render it through `Template CV.docx`.
- [ ] CV-005 — Convert and validate DOCX/PDF outputs without corrupting the source template.
- [ ] CV-006 — Complete README setup and step-by-step usage documentation.

## Authorized scope and route

- Repository: `personal/profesional/cv/`
- Supporting task document: `odd/tasks/cv-agents.md`
- Route: delegated direct implementation for multi-file behavior; one writer per work unit.
- Branch: `feature/cv-agent-pipeline`
- Delivery strategy: `ask-on-risk` until a line-count or PR slicing decision is required.

## Acceptance criteria

- A new checkout can configure the Obsidian vault without embedding machine-specific paths in source files.
- The fast command accepts a job URL or saved text and returns structured requirements plus gaps.
- A failed or blocked URL can fall back to manually supplied text.
- Application records are persistent and isolated by application identifier.
- Missing evidence is reported as missing or uncertain, never fabricated.
- DOCX generation uses `Template CV.docx`; the current CV remains read-only reference input.
- PDF output is produced only when the required converter is available and failures are explicit.
- Focused tests and the documented verification commands pass.

## Applicable checks

- `python -m pytest`
- `python -m compileall src tests`
- CLI smoke tests using mocked HTTP and model boundaries
- DOCX/PDF structural checks when document generation is implemented

## Progress

| Task | Status | Verification | Commit |
| --- | --- | --- | --- |
| CV-001 | complete | `uv run pytest` (15 passed); compileall; Ruff | `d87fc45` |
| CV-002 | complete | `uv run pytest` (15 passed); compileall; Ruff | `d87fc45` |
| CV-003 | complete | `uv run pytest` (23 passed); compileall; Ruff | pending |
| CV-004 | pending | pending | pending |
| CV-005 | pending | pending | pending |
| CV-006 | pending | pending | pending |

## Next step

CV-003 is implemented and verified without creating a commit. The next work unit is CV-004: tailored CV content generation through `Template CV.docx`.
