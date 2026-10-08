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
- [x] QA-002 — Implement client intake, requirement inference, assumptions, and human approval boundaries.
- [x] QA-003 — Implement planning, Backend, Frontend, and DevOps decomposition agents with structured task outputs.
- [x] QA-004 — Implement effort estimation, PEN pricing, flexible floor/ceiling handling, module splitting, and payment schedules.
- [x] QA-005 — Implement professional proposal generation in DOCX/PDF with scope, estimates, payments, validity, assumptions, and exclusions.
- [x] QA-006 — Implement quotation review, representative test scenarios, operational documentation, and end-to-end verification.

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
| QA-001 | verified | `uv run pytest` (27 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); native risk assessment: medium; native review blocked by intended-untracked selection contract | `5a8391e` |
| QA-002 | verified | `uv run pytest` (41 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); native risk assessment: medium; native review blocked by intended-untracked selection contract | `433306f` |
| QA-003 | verified | `uv run pytest` (56 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); native review preflight blocked by intended-untracked-selection schema | `d19a127` |
| QA-004 | verified | `uv run pytest` (69 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); native risk assessment: medium; native review approved with 3 non-blocking reliability findings | `0a8b65e` |
| QA-005 | verified | `uv run pytest` (80 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); focused document/pricing tests (24 passed); native risk assessment: high; native review blocked by unrelated intended-untracked selection; independent verification passed | `fe2b9af`, `0d16ab8` |
| QA-006 | verified | `uv run pytest` (96 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed); focused review/document tests (26 passed); independent verification passed; native assessment high and review blocked by unrelated intended-untracked selection | `9f0797c`, `11916e7` |

## Resume protocol

Before continuing, read this task card, reconcile its requirements with the current code and user-approved changes, and inspect the Engram mirror at `odd/quotation-agents/tasks`. Continue only with the first unfinished task. After each task, update this file and its mirror with observed verification evidence and the work-unit commit identity.

## Next step

All planned quotation-agent tasks are complete. Follow-up work can add persistence, CLI behavior,
or provider construction as a separately authorized feature.

## QA-001 Evidence

- Created `personal/profesional/quotations/` as an independent `quotation_agents` package with its own Hatchling project, lockfile, dotenv example, local ignore rules, README, configuration, commercial policy/rates, editable quotation state, provider boundary, and focused tests.
- Preserved the original request and required client/company, modeled editable inferred scope/assumptions/questions/risks, and kept approval pending by default.
- Centralized PEN rates and commercial policy with `Decimal`, two-decimal `ROUND_HALF_UP` money rounding, three hours per day, floor/ceiling, payment threshold, advance rate, validity, and IGV exclusion. Pricing, payment schedules, document generation, and ideal-price formulas remain deferred.
- Writer verification: `uv run pytest` — 27 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator spot-check: `uv run pytest` — 27 passed.
- `gentle-ai review assess` classified the selected package files as `medium`. Native review STATUS could not accept the provider-issued intended-untracked selection, so no review receipt or approval was produced. No GitHub operation was performed.
- Work-unit commit: `5a8391e` (`feat(quotations): bootstrap standalone quotation domain`). Rollback boundary: remove `personal/profesional/quotations/` as one unit.

## QA-002 Evidence

- Added `RequirementInference` as a provider response model that accepts only inferred scope, assumptions, questions, and risks; unknown fields such as approval state are rejected.
- Added provider-injected LangChain inference in `inference.py`, with untrusted input delimiters, explicit structured-response validation, and no implicit provider construction or live calls.
- Added `intake_draft`, explicit `approve_draft`, editable `revise_draft`, and `require_approved_draft` workflow boundaries. Intake is always pending, revision preserves the original request and resets approval, and downstream use rejects pending drafts.
- Writer verification: `uv run pytest` — 41 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator spot-check repeated the same three commands successfully.
- `gentle-ai review mode status` reported receipt-driven development enabled globally. The committed QA-002 candidate (`--base-ref 5a8391e --committed-only`) was assessed as medium (7 paths, 494 changed lines), but native STATUS could not accept its provider-issued intended-untracked-selection contract. No review receipt or approval was produced; no GitHub operation was performed.
- Work-unit commit: `433306f` (`feat(quotations): add intake and approval workflow`). Rollback boundary: revert `433306f` or remove the QA-002 inference/workflow files and their README/tests changes.

## QA-003 Evidence

- Added `TaskDecomposition` as a strict structured response model and a parameterized `decompose_category` boundary for Planning and coordination, Backend, Frontend, and DevOps. Provider output is rejected when malformed, contains unknown fields, or assigns a task to a different requested category.
- Decomposition requires an approved draft before provider invocation, preserves the client/company, original request, and editable intake analysis inside untrusted-data delimiters, and never mutates or approves the input draft. Applying results through `revise_draft` intentionally resets approval for human re-review.
- Preserved callable, model, and prebuilt-agent injection without implicit provider construction. Empty category output is valid and effort estimates remain deferred to QA-004.
- Writer verification: focused decomposition tests — 15 passed; `uv run pytest` — 56 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator repeated all three commands successfully.
- `gentle-ai review mode status` reported receipt-driven development enabled globally. Native STATUS required an intended-untracked selection for unrelated `personal/profesional/cv/files/` templates; the provider-issued selection payload was rejected as invalid, so no review receipt or approval was produced. No GitHub operation was performed.
- Work-unit commit: `d19a127` (`feat(quotations): add task decomposition agents`). Rollback boundary: revert `d19a127` to remove only QA-003 decomposition behavior, tests, and package documentation.

## QA-004 Evidence

- Added pure Decimal-based effort and quote calculations in `pricing.py`: category hours/subtotals, three-hour calendar days, editable complexity/dependency/risk factors, explicit contingency, minimum/ideal/maximum bands, and selected/custom amounts.
- Applied the S/150 floor without discarding the raw amount; exact S/10,000 remains valid and values above the ceiling are preserved and flagged for modularization/manual approval instead of clipped. `CommercialPolicy` now rejects an invalid floor/ceiling ordering.
- Added deterministic module partitioning and threshold payment schedules. Quotes below S/700 use one full-project payment; quotes at or above S/700 use a 40% advance plus module/progress payments with exact cent reconciliation.
- Calculations require an approved draft, do not mutate draft state, and preserve existing provider and human-approval boundaries. README documents formulas, assumptions, exclusions from this task, and current limits.
- Writer verification: focused pricing tests — 13 passed; `uv run pytest` — 69 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator spot-check: `uv run pytest` — 69 passed.
- `gentle-ai review assess` classified the committed package candidate as `medium` (5 paths, 713 changed lines). Native review lineage `review-8fb116e8d93bf91e` was approved and acknowledged; authority was burned. Findings were non-blocking: non-positive task-hour boundary coverage, residual-cent allocation coverage, and rounded module percentage semantics. No correction was opened and no GitHub operation was performed.
- Work-unit commit: `0a8b65e` (`feat(quotations): add pricing and payment calculations`). Rollback boundary: revert `0a8b65e` to remove QA-004 pricing, module, payment, tests, and documentation behavior without touching the unrelated CV files.

## QA-005 Evidence

- Added `documents.py` with deterministic, approval-gated DOCX proposal generation, optional injectable PDF conversion, structural DOCX/PDF validation, safe output naming, and overwrite protection. The public entry point is exported as `generate_proposal_documents`.
- Proposals preserve the approved client/company, original request, scope, categorized tasks, effort and three-hour calendar days, category rates/subtotals, quote bands, selected amount, payment schedule, assumptions, risks, questions, IGV exclusion, 14-day validity, and separate-charge exclusions. English and Spanish client-facing labels are supported.
- Amounts above S/10,000 remain visible and disclose modularization/manual approval; below-S/700 quotes render one full-project payment, while quotes at or above S/700 render the 40% advance and remaining milestones. PDF generation stays offline by default and requires an injected converter or explicit LibreOffice converter.
- Added a deterministic SHA-256 draft fingerprint to `QuoteResult`; document generation rejects a missing or mismatched quote/draft association without recalculating pricing. Path-like and drive-relative output names are rejected across platforms.
- Writer verification: focused document/pricing tests — 24 passed; `uv run pytest` — 80 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed. Coordinator spot-check repeated the focused tests successfully. Independent verification passed with additional approval, fingerprint, filename, content, PDF-injection, and overwrite probes.
- `gentle-ai review mode status` was enabled globally, but native review preflight required selection of unrelated untracked CV template files and could not produce a review receipt. Risk assessment classified the committed candidate as high because of the shell-process boundary. No GitHub operation was performed; unrelated untracked files were untouched.
- Work-unit commits: `fe2b9af` (`feat(quotations): generate proposal documents`) and `0d16ab8` (`fix(quotations): bind proposal documents to quote drafts`). Rollback boundary: revert both commits to remove QA-005 document generation and its bounded integrity correction without touching prior quotation pricing or unrelated CV files. Real LibreOffice conversion remains an environment-dependent limitation because `soffice` is unavailable on PATH.

## QA-006 Evidence

- Added deterministic `review_quote` checks for approved-draft binding, scope notes, task/effort arithmetic, monetary cent precision, quote bands and limits, payment reconciliation, threshold milestone shape, and manual-approval warnings for amounts above S/10,000. Review remains provider-free and does not recalculate or mutate the quote.
- Enforced the review gate in `generate_proposal_documents`: error findings prevent any output from being written, while over-ceiling quotes remain renderable as explicit modularization/manual-approval requests without clipping the amount.
- Added representative scenarios for a WordPress adjustment, a below-S/700 quote, a medium modular quote, the S/700 threshold, an over-ceiling quote, and an end-to-end injected decomposition/pricing/review/DOCX path. README documents the operational order and review behavior.
- Added regression coverage for malformed reconciled payment schedules, non-cent monetary values, and proposal generation from a quote with review errors. No live provider calls are used.
- Writer verification: `uv run pytest` — 96 passed; `python -m compileall src tests` — passed; `uv run ruff check src tests` — all checks passed; focused review/document tests — 26 passed. Final independent verification — PASS; import smoke test and `git diff --check` — passed.
- Receipt-driven development was enabled globally. Native status required selection of unrelated untracked CV templates; the committed candidate was assessed as `high` because of the existing shell-process boundary, but no native review receipt was produced. No GitHub operation was performed and `personal/profesional/cv/files/` remained untouched.
- Work-unit commits: `9f0797c` (`feat(quotations): add quote review scenarios`) and `11916e7` (`fix(quotations): enforce review before proposals`). Rollback boundary: revert both commits to remove QA-006 review, scenarios, documentation, and bounded review-gate corrections without touching QA-001 through QA-005 behavior.
