# Development Quotation Agents

## Objective

Build a local, reusable LangChain workflow that reads software-development requirements, decomposes the work into planning, Backend, Frontend, and DevOps tasks, estimates delivery time at three hours per day, calculates a commercial quote in Peruvian soles, and generates a presentable DOCX/PDF proposal after human approval.

## Problem

Development requests range from small WordPress adjustments to complete modules. The quotation process needs a repeatable technical breakdown, transparent hourly estimates, modular payments, and a professional client-facing document without inventing requirements or silently choosing commercial assumptions.

## Why

The user wants to divide project payments by progress and modules instead of requesting one large payment, while preserving control over the inferred scope, ideal price, assumptions, and final proposal.

## Scope

- Create a separate LangChain-based quotation package; do not mix its domain models with `personal/profesional/cv/`.
- Reuse the existing project's LangChain 1.x, Pydantic, configuration, provider-injection, testing, and pipeline conventions where appropriate.
- Ask for the client or requesting company on every quotation.
- Infer the remaining project fields from the supplied request and present them for user approval or adjustment.
- Decompose the request into planning/coordinating, Backend, Frontend, and DevOps work.
- Estimate effort in hours and calendar days using three available hours per day.
- Calculate minimum, maximum, and recommended/ideal amounts in PEN.
- Split the work and payments by modules or milestones.
- Generate a professional proposal only after the user approves the interpreted scope and estimate.
- Review the final quote for scope, arithmetic, assumptions, and commercial consistency.

## Commercial rules

| Work category | Hourly rate |
| --- | ---: |
| Planning and coordination | S/10 |
| Backend | S/30 |
| Frontend | S/20 |
| DevOps | S/15 |

- Currency: Peruvian soles (PEN).
- IGV: excluded; do not add or calculate it.
- Availability: three development hours per day.
- General quote floor: S/150.
- General quote ceiling: S/10,000 per proposal or module.
- Projects at or above S/700: first payment is a 40% advance; the remaining amount is divided by modules or progress.
- Projects below S/700: one payment for the complete project.
- Quote validity: two weeks (14 calendar days).
- Module adjustments, new functionality outside the approved requirements, and server migrations are out of scope and must be quoted separately.
- If a quote exceeds S/10,000, do not reduce the scope artificially. Propose modular delivery or request manual approval for an exception.
- The ideal amount must be derived from effort, category rates, complexity, dependencies, risk, and explicit contingency rules; it must not be invented without evidence.

## Constraints

- The client/company is the only mandatory question before inference begins.
- Inferred requirements, assumptions, exclusions, estimates, and the recommended amount must remain editable by the user.
- No final proposal may be generated before explicit user approval of the estimate.
- Missing or ambiguous requirements must be reported as assumptions, questions, or risks; never fabricated as facts.
- Technical artifacts and generated proposal templates use English unless the user explicitly requests another artifact language. Client-facing proposal language should follow the user's selected language.
- Keep the quotation domain independent from the existing CV agent and its application records.
- Preserve injected model/provider boundaries so tests do not require live model calls.

## Planned tasks

- [x] QA-001 — Bootstrap the standalone quotation package, configuration, rates, structured state models, and test harness.
- [ ] QA-002 — Implement client intake, requirement inference, assumptions, and human approval boundaries.
- [ ] QA-003 — Implement planning, Backend, Frontend, and DevOps decomposition agents with structured task outputs.
- [ ] QA-004 — Implement effort estimation, PEN pricing, flexible floor/ceiling handling, module splitting, and payment schedules.
- [ ] QA-005 — Implement professional proposal generation in DOCX/PDF with scope, estimates, payments, validity, assumptions, and exclusions.
- [ ] QA-006 — Implement quotation review, representative test scenarios, operational documentation, and end-to-end verification.

## Authorized scope and route

- Repository: `ai-agents`.
- New package: provisionally `personal/profesional/quotations/`; confirm the final package path during QA-001 without changing the separate-domain constraint.
- Existing reference package: `personal/profesional/cv/`.
- Route: delegated direct implementation for multi-file behavior; one writer per work unit.
- Each task must include focused tests and documentation for the behavior it introduces.
- Delivery strategy: `ask-on-risk` until a line-count or PR slicing decision is required.
- Chain strategy selected for this feature: `stacked-to-main` because the authored change forecast exceeds the approximate 400-line review budget; each work unit remains independently reviewable.
- The feature branch must be created before the first implementation commit if work starts on the default branch.

## Acceptance criteria

- A quotation always records the client/company and preserves the original request.
- The workflow produces structured, editable tasks grouped by Planning, Backend, Frontend, and DevOps.
- The workflow calculates hours, three-hour workdays, category subtotals, and total PEN amounts deterministically from the approved task estimates.
- A simple WordPress adjustment can be quoted without forcing a large-project structure.
- A complete module can be quoted with milestone-based payments.
- A quote below S/700 produces one payment; a quote at or above S/700 produces a 40% advance and a modular balance.
- The quote excludes IGV and clearly states the 14-day validity.
- Adjustments, new unestimated features, and server migrations appear as separate-charge exclusions.
- The ideal amount stays between S/150 and S/10,000 unless the workflow explicitly requests modularization or manual approval.
- A quote above S/10,000 is not silently clipped and retains the full scope in the proposal or approval request.
- The user can approve or modify inferred requirements, estimates, modules, and price before document generation.
- Generated DOCX/PDF output is readable, professional, and consistent with the approved structured quote.
- Tests cover at least: a WordPress adjustment, a medium module, a quote below S/700, a quote at or above S/700, and a quote exceeding S/10,000.
- No live provider call is required for the automated test suite.

## Applicable checks

- `uv run pytest`
- `python -m compileall src tests`
- Ruff checks using the package configuration.
- Structured model tests for rates, hours, rounding, limits, and payment rules.
- LangChain boundary tests using injected fake models/invocations.
- DOCX/PDF structural checks when document generation is implemented.
- CLI or API smoke tests using representative quotation fixtures.

## Progress

| Task | Status | Verification | Commit |
| --- | --- | --- | --- |
| QA-001 | verified; commit pending | `uv run pytest` (27 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); native risk assessment: medium; native review blocked by intended-untracked selection contract | — |
| QA-002 | pending | — | — |
| QA-003 | pending | — | — |
| QA-004 | pending | — | — |
| QA-005 | pending | — | — |
| QA-006 | pending | — | — |

## Resume protocol

Before continuing, read this task card, reconcile its requirements with the current code and user-approved changes, and inspect the Engram mirror at `odd/quotation-agents/tasks`. Continue only with the first unfinished task. After each task, update this file and its mirror with observed verification evidence and the work-unit commit identity.

## Next step

QA-002: implement client intake, requirement inference, assumptions, and explicit human approval boundaries on top of the standalone quotation domain.

## QA-001 Evidence

- Created `personal/profesional/quotations/` as an independent `quotation_agents` package with its own Hatchling project, lockfile, dotenv example, local ignore rules, README, configuration, commercial policy/rates, editable quotation state, provider boundary, and focused tests.
- Preserved the original request and required client/company, modeled editable inferred scope/assumptions/questions/risks, and kept approval pending by default.
- Centralized PEN rates and commercial policy with `Decimal`, two-decimal `ROUND_HALF_UP` money rounding, three hours per day, floor/ceiling, payment threshold, advance rate, validity, and IGV exclusion. Pricing, payment schedules, document generation, and ideal-price formulas remain deferred.
- Writer verification: `uv run pytest` — 27 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator spot-check: `uv run pytest` — 27 passed.
- `gentle-ai review assess` classified the selected package files as `medium`. Native review STATUS could not accept the provider-issued intended-untracked selection, so no review receipt or approval was produced. No GitHub operation was performed.
- Commit identity remains pending until the delivery slicing decision is resolved. Rollback boundary: remove `personal/profesional/quotations/` as one unit.
