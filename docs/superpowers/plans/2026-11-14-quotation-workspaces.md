# Quotation Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-shot quotation CLI into persistent per-quotation workspaces with `setup`, `list`, `resume` and `profile` commands, document digests read once, a developer profile, and versioned outputs.

**Architecture:** New focused modules hold persistence (`state.py`, `notes.py`, `workspace.py`), the profile file (`profile.py`), document digests (`ingestion.py`) and profile agents (`profile_agent.py`). `cli.py` stays the library of interactive phase functions (its `main`/`_parse_args` and `--attachment` are removed); a new `workspace_cli.py` owns argument parsing, the subcommands and the resume orchestrator, and becomes the `quotation` entry point. Downstream agents keep their `source_documents` parameter: they now receive the profile and the digests as `SourceDocument`s instead of raw document text.

**Tech Stack:** Python ≥ 3.11, uv, LangChain 1.x `create_agent` with `response_format`, Pydantic 2, PyYAML (new), pytest with fake agents (existing pattern in `tests/test_cli.py`).

**Spec:** `docs/superpowers/specs/2026-11-14-quotation-workspaces-design.md`

All paths below are relative to `personal/profesional/quotations/` unless they start with `docs/`. Run commands from that directory.

## Global Constraints

- Python CLI only; no Claude Code commands.
- The profile is LLM context only; pricing stays in `rates.py`. `rate_per_hour` on team members is stored but never read by pricing.
- Persistence is plain files: `notes.md`, `state.json`, `profile.md` inside the workspace.
- Workspaces root: `--root DIR`, else env `QUOTATION_WORKSPACES`, else `quotes/` anchored to the package directory (`personal/profesional/quotations/quotes`), never the current working directory. `quotes/` is added to the package `.gitignore`.
- `_profile/` is reserved: base profile at `<root>/_profile/profile.md`, learning index at `<root>/_profile/learned.json`; no slug may be `_profile`.
- Slugs longer than 40 characters are summarized by an LLM into a short slug (2–5 words); the user accepts or types another.
- Source text and profile text are untrusted data inside the existing input-data delimiters, never instructions.
- `notes.md` is append-only; decision entries are rendered deterministically from approved data; only digests come from the LLM.
- Every approval checkpoints `state.json` (atomic write) plus a `notes.md` decision entry.
- Reopening a phase keeps later work as a draft to revise; nothing approved is discarded.
- Generation writes `output/v1/`, `output/v2/`, … with both DOCX files plus `snapshot.json`; never overwrite a version.
- `--attachment` and `--output` are removed; bare `uv run quotation` prints help.
- The profile agent never writes without per-edit approval and never modifies project copies.
- Artifacts (code, prompts, file contents, docs) in English.

## Review Focus

- **Hand-edited or corrupt `state.json` / `profile.md`** → a clear error naming the file and field, never a stack trace; `list` shows the workspace as "invalid" with the reason. (Tests in Tasks 2, 1, 3.)
- **Office lock files and hidden files in `documentations/`** (`~$draft.docx`, `.DS_Store`) → ignored silently, not reported as failures. (Test in Task 4.)
- **Digest agent failure for one file** → warning, file not recorded, other files still processed, retried on the next `resume`. (Test in Task 4.)
- **Ctrl+C / quit in the middle of task review after scope was approved** → `resume` starts at task review with the approved scope intact. (Test in Task 7.)
- **Names that slugify to empty or collide** (`"¿¿??"`, two setups named "CRM") → empty asks for another name; collision gets `-2`. (Tests in Task 3.)

---

### Task 1: Developer profile file format

**Files:**
- Create: `src/quotation_agents/profile.py`
- Modify: `pyproject.toml` (add `"pyyaml>=6.0,<7.0"` to dependencies; run `uv lock`)
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces:
  - `class ProfileError(ValueError)`
  - `class TeamMember(BaseModel)`: `name: str`, `role: str`, `rate_per_hour: Decimal | None = None` (extra forbidden)
  - `class DeveloperProfile(BaseModel)`: `stack: list[str]`, `tools: list[str]`, `mcps: list[str]`, `project_kinds: list[str]`, `team: list[TeamMember]`, `conventions: str = ""` (lists default empty, extra forbidden)
  - `PROFILE_FIELDS: tuple[str, ...] = ("stack", "tools", "mcps", "project_kinds", "team", "conventions")`
  - `PROFILE_TEMPLATE: DeveloperProfile` (example: stack `["Python", "React"]`, tools `["GitHub"]`, one team member `"Me"`/`"fullstack"`, conventions placeholder text)
  - `parse_profile(text: str, *, source: str = "profile.md") -> DeveloperProfile`
  - `render_profile(profile: DeveloperProfile) -> str` — `---\n<yaml frontmatter>---\n## Conventions\n<conventions>\n`; `rate_per_hour` omitted when None.
  - `load_profile(path: Path) -> DeveloperProfile`, `save_profile(path: Path, profile: DeveloperProfile) -> None`
  - `profile_source_document(profile: DeveloperProfile) -> SourceDocument` with `name="developer_profile.md"`, `text=render_profile(profile)`
  - `class ProfileEdit(BaseModel)`: `field: Literal["stack","tools","mcps","project_kinds","team","conventions"]`, `action: Literal["add","remove","replace"]`, `value: str`, `reason: str`
  - `apply_edit(profile: DeveloperProfile, edit: ProfileEdit) -> DeveloperProfile` (returns a copy)

- [ ] **Step 1: Write the failing tests** in `tests/test_profile.py`:
  - `test_render_then_parse_round_trips` — `parse_profile(render_profile(p)) == p` for a profile with all fields and a member with `rate_per_hour=Decimal("25")`.
  - `test_parse_reads_conventions_body` — text with frontmatter `stack: [Python]` and body `## Conventions\nUse trunk-based dev.` → `conventions == "Use trunk-based dev."`.
  - `test_parse_without_frontmatter_raises_profile_error` — message contains `"profile.md"`.
  - `test_parse_invalid_field_names_file_and_field` — frontmatter `stack: 5` → `ProfileError` message contains `"profile.md"` and `"stack"`.
  - `test_apply_edit_add_is_case_insensitive_noop_when_present` — adding `"python"` to stack `["Python"]` leaves `["Python"]`.
  - `test_apply_edit_remove_and_replace_list` — remove `"GitHub"` from tools; replace stack with `"Python, Vue"` → `["Python", "Vue"]` (replace splits on commas).
  - `test_apply_edit_team_add_and_remove` — add value `"Ana - frontend"` → `TeamMember(name="Ana", role="frontend")`; remove value `"Ana"` removes by name (case-insensitive).
  - `test_apply_edit_conventions` — add appends a new paragraph (`"\n\n"` separator); replace replaces; remove raises `ProfileError`.
  - `test_profile_source_document_name` — `.name == "developer_profile.md"`.

- [ ] **Step 2: Run** `uv run pytest tests/test_profile.py -v` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `profile.py`. Use `yaml.safe_load`/`yaml.safe_dump(sort_keys=False, allow_unicode=True)`; split frontmatter on the first two `---` lines; wrap `yaml.YAMLError` and `ValidationError` into `ProfileError(f"{source}: {detail}")` where detail includes the failing field (`exc.errors()[0]["loc"]`). Body: text after the `## Conventions` heading, stripped. Add `pyyaml` and run `uv lock`.

- [ ] **Step 4: Run** `uv run pytest tests/test_profile.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/quotation_agents/profile.py tests/test_profile.py
git commit -m "feat(quotations): add developer profile file format"
```

---

### Task 2: Workspace state and notes

**Files:**
- Create: `src/quotation_agents/state.py`, `src/quotation_agents/notes.py`
- Test: `tests/test_state.py`, `tests/test_notes.py`

**Interfaces:**
- Consumes: `QuotationDraft` (`models.py`), `QuoteResult` (`pricing.py`)
- Produces (`state.py`):
  - `class StateError(ValueError)`
  - `class Phase(StrEnum)`: `INTAKE="intake"`, `SCOPE_REVIEW="scope_review"`, `DECOMPOSITION="decomposition"`, `PRICING="pricing"`, `GENERATED="generated"` — the phase that runs next (`GENERATED` = at least one version exists and nothing is pending).
  - `class DocumentDigest(BaseModel)`: `summary: str`, `requirements: list[str]`, `constraints: list[str]`, `open_questions: list[str]`, `technologies: list[str]`
  - `class DocumentRecord(BaseModel)`: `name: str`, `sha256: str`, `status: Literal["active","removed","unreadable"]`, `digest: DocumentDigest | None = None`, `error: str | None = None`, `updated_at: datetime`
  - `class GeneratedVersion(BaseModel)`: `number: int`, `created_at: datetime`, `total: Decimal`, `path: str` (relative to workspace, e.g. `"output/v1"`)
  - `class WorkspaceState(BaseModel)`: `name: str`, `slug: str`, `created_at: datetime`, `updated_at: datetime`, `phase: Phase = Phase.INTAKE`, `session_count: int = 0`, `draft: QuotationDraft | None = None`, `quote: QuoteResult | None = None`, `revise_tasks_for_new_scope: bool = False`, `documents: list[DocumentRecord] = []`, `versions: list[GeneratedVersion] = []`
  - `load_state(path: Path) -> WorkspaceState` — raises `StateError` whose message contains the path (and the first failing field for validation errors).
  - `save_state(path: Path, state: WorkspaceState) -> None` — writes `model_dump_json(indent=2)` to `path.with_suffix(".json.tmp")` then `os.replace`.
  - `reopen(state: WorkspaceState, phase: Literal[Phase.SCOPE_REVIEW, Phase.DECOMPOSITION, Phase.PRICING]) -> WorkspaceState` — returns copy: sets `phase`, `quote=None`; for `SCOPE_REVIEW` sets draft `approval_state` to pending (keeping `draft.tasks`) and `revise_tasks_for_new_scope=True` when the draft has tasks.
- Produces (`notes.py`):
  - `init_notes(path: Path, name: str) -> None` — writes `# Quotation notes — {name}\n`
  - `start_session(path: Path, number: int, today: date) -> None` — appends `\n## {today.isoformat()} — Session {number}\n`
  - `append_section(path: Path, heading: Literal["Discovered", "Decided"], items: Sequence[str]) -> None` — appends `### {heading}\n- item\n…`; no-op for empty items
  - `digest_lines(name: str, digest: DocumentDigest) -> list[str]` — first line `"{name}: {summary}"`, then `"  requirement: …"`, `"  technology: …"` etc.

- [ ] **Step 1: Write the failing tests**
  - `test_state_round_trip` — save then load a state with a draft, a quote from `calculate_quote(approved draft with tasks)`, one document and one version → equal.
  - `test_load_state_invalid_json_names_file` — file content `{` → `StateError`, message contains file name.
  - `test_load_state_invalid_field_names_field` — `"phase": "nope"` → message contains `"phase"`.
  - `test_save_state_leaves_no_tmp_file`.
  - `test_reopen_scope_keeps_tasks_and_clears_quote` — approved draft with 2 tasks + quote → phase `SCOPE_REVIEW`, draft pending, 2 tasks kept, `quote is None`, `revise_tasks_for_new_scope is True`.
  - `test_reopen_decomposition_keeps_scope_approved` — phase `DECOMPOSITION`, `quote is None`, flag False.
  - `test_notes_append_only_sections` — `init_notes`, `start_session(…, 2, date(2026,11,14))`, `append_section(…, "Decided", ["Scope approved (6 items)."])` → file text equals exact expected string; a pre-existing hand edit line stays.
  - `test_append_section_empty_is_noop`.

- [ ] **Step 2: Run** `uv run pytest tests/test_state.py tests/test_notes.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement** `state.py` and `notes.py` per the interfaces (Pydantic `model_validate_json`; wrap `ValidationError`/`ValueError` into `StateError(f"{path}: {loc}: {msg}")`). Notes open files with `"a", encoding="utf-8"`.

- [ ] **Step 4: Run** the same command — Expected: PASS.

- [ ] **Step 5: Commit** `feat(quotations): add workspace state and notes log`.

---

### Task 3: Workspace layout, slugs and listing

**Files:**
- Create: `src/quotation_agents/workspace.py`
- Modify: `.gitignore` (add `quotes/`)
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `WorkspaceState`, `save_state`, `load_state`, `StateError`, `Phase` (Task 2); `init_notes` (Task 2); `DeveloperProfile`, `save_profile`, `load_profile` (Task 1)
- Produces:
  - `class WorkspaceError(ValueError)`
  - `PACKAGE_ROOT = Path(__file__).resolve().parents[2]`; `DEFAULT_ROOT = PACKAGE_ROOT / "quotes"`; `PROFILE_DIR_NAME = "_profile"`; `MAX_SLUG_LENGTH = 40`
  - `resolve_root(cli_root: Path | None, env: Mapping[str, str] | None = None) -> Path` (`env` defaults to `os.environ`, key `QUOTATION_WORKSPACES`)
  - `slugify(name: str) -> str` — NFKD → ASCII, lowercase, runs of non-`[a-z0-9]` → `-`, strip `-`; returns `""` when nothing remains.
  - `unique_slug(root: Path, slug: str) -> str` — `slug`, else `slug-2`, `slug-3`, …
  - `class SlugSuggestion(BaseModel)`: `slug: str`; `create_slug_agent(model: Any) -> Any` (system prompt: "Summarize the quotation name into a short folder name of 2 to 5 words…"); `suggest_slug(name: str, *, agent: Any) -> str` — returns `slugify(response.slug)[:MAX_SLUG_LENGTH].strip("-")`.
  - `@dataclass(frozen=True) class WorkspacePaths`: `root: Path`; properties `documentations`, `profile` (`profile.md`), `notes` (`notes.md`), `state` (`state.json`), `output`.
  - `base_profile_path(root: Path) -> Path`, `learned_index_path(root: Path) -> Path`
  - `create_workspace(root: Path, name: str, slug: str, profile: DeveloperProfile, now: datetime) -> WorkspacePaths` — rejects `_profile` and existing folders with `WorkspaceError`; creates `documentations/`, `output/`, writes profile copy, `notes.md` (via `init_notes`), `state.json` (`phase=INTAKE`).
  - `@dataclass(frozen=True) class WorkspaceSummary`: `slug`, `name: str | None`, `phase: Phase | None`, `last_activity: datetime | None`, `latest_version: int | None`, `latest_total: Decimal | None`, `error: str | None`
  - `list_workspaces(root: Path) -> list[WorkspaceSummary]` — every subfolder except `_profile` and hidden ones, sorted by `last_activity` desc (invalid last); missing/invalid `state.json` → `error` set.
  - `open_workspace(root: Path, slug: str) -> WorkspacePaths` — `WorkspaceError` if missing or no `state.json`.

- [ ] **Step 1: Write the failing tests**
  - `test_resolve_root_precedence` — cli arg beats env beats `DEFAULT_ROOT`; `DEFAULT_ROOT.parent.name == "quotations"`.
  - `test_slugify` — `"Sistema de Campañas Cableclub"` → `"sistema-de-campanas-cableclub"`; `"¿¿??"` → `""`.
  - `test_unique_slug_appends_suffix` — with `crm/` existing → `"crm-2"`; with `crm-2/` too → `"crm-3"`.
  - `test_suggest_slug_uses_agent_and_truncates` — fake agent returning `{"structured_response": {"slug": "CRM Cableclub Campaigns"}}` → `"crm-cableclub-campaigns"`.
  - `test_create_workspace_layout` — folders/files exist; state phase `intake`; notes header; profile copy loads equal.
  - `test_create_workspace_rejects_reserved_and_existing`.
  - `test_list_workspaces_reports_invalid_state` — one valid, one with `state.json` = `"{"`, one with none, plus `_profile/` → 3 summaries, `_profile` excluded, invalid ones have `error` and sort last.
  - `test_gitignore_ignores_quotes` — `(PACKAGE_ROOT / ".gitignore").read_text()` contains a line `quotes/`.

- [ ] **Step 2: Run** `uv run pytest tests/test_workspace.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `workspace.py`; add `quotes/` to `.gitignore`. Slug agent follows the existing `create_agent(model, tools=[], system_prompt=…, response_format=SlugSuggestion)` pattern and the `structured_response` normalization used in `inference.py`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(quotations): add workspace layout, slugs and listing`.

---

### Task 4: Document ingestion with digests, and profile-aware prompts

**Files:**
- Create: `src/quotation_agents/ingestion.py`
- Modify: `src/quotation_agents/inference.py` (`INFERENCE_SYSTEM_PROMPT`), `src/quotation_agents/decomposition.py` (`DECOMPOSITION_SYSTEM_PROMPT`)
- Test: `tests/test_ingestion.py`; extend `tests/test_intake.py`, `tests/test_decomposition.py`

**Interfaces:**
- Consumes: `load_source_document`, `AttachmentError`, `SourceDocument`, `SUPPORTED_ATTACHMENT_SUFFIXES` (`attachments.py`); `WorkspaceState`, `DocumentRecord`, `DocumentDigest` (Task 2); `WorkspacePaths` (Task 3); `DeveloperProfile`, `profile_source_document` (Task 1)
- Produces:
  - `create_digest_agent(model: Any) -> Any`; `digest_document(document: SourceDocument, *, agent: Any) -> DocumentDigest` (raises `IngestionError(ValueError)` on invalid response)
  - `@dataclass class IngestionResult`: `added: list[str]`, `changed: list[str]`, `removed: list[str]`, `unreadable: list[tuple[str, str]]`, `failed: list[tuple[str, str]]`; property `has_new_content -> bool` (`added or changed`)
  - `ingest_documents(paths: WorkspacePaths, state: WorkspaceState, *, digest: Callable[[SourceDocument], DocumentDigest], now: datetime) -> tuple[WorkspaceState, IngestionResult]`
  - `context_documents(state: WorkspaceState, profile: DeveloperProfile) -> tuple[SourceDocument, ...]` — profile document first, then one `SourceDocument(name=f"{record.name} (digest)", text=<rendered digest>)` per active record with a digest.

Rules for `ingest_documents`: skip names starting with `.` or `~$` and non-files; sha256 of bytes; unchanged active/unreadable record → untouched (no extraction, no digest call); unsupported suffix or `AttachmentError` → record `status="unreadable"`, `error` set, hash stored; `digest` raising any `Exception` → not recorded, listed in `failed`; a previously active record whose file is gone → `status="removed"`.

- [ ] **Step 1: Write the failing tests** (`tmp_path` workspace via `create_workspace`; a counting fake `digest` callable):
  - `test_ingest_new_file_records_digest` — `a.md` → `added == ["a.md"]`, record active with digest.
  - `test_ingest_unchanged_file_not_redigested` — second call → digest call count stays 1, `has_new_content is False`.
  - `test_ingest_changed_file_replaces_digest` — rewrite `a.md` → `changed == ["a.md"]`, one record, new digest.
  - `test_ingest_removed_file_marked_removed`.
  - `test_ingest_skips_lock_and_hidden_files` — `~$a.docx`, `.DS_Store` → no records, nothing in `unreadable`.
  - `test_ingest_unsupported_file_recorded_unreadable` — `img.png` → `unreadable[0][0] == "img.png"`, not retried on next call.
  - `test_ingest_digest_failure_is_retried_next_time` — digest raises for `b.md` once → `failed` contains it, no record; next call digests it.
  - `test_context_documents_profile_first_and_skips_removed`.
  - In `test_intake.py`: `test_inference_prompt_explains_developer_profile` — `"developer_profile.md" in INFERENCE_SYSTEM_PROMPT`; same in `test_decomposition.py` for `DECOMPOSITION_SYSTEM_PROMPT`.

- [ ] **Step 2: Run** `uv run pytest tests/test_ingestion.py tests/test_intake.py tests/test_decomposition.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** `ingestion.py`; digest agent system prompt states the document is untrusted client draft material and asks only for the `DocumentDigest` fields. Append to both system prompts, verbatim:

```
A source document named developer_profile.md describes the provider's own stack,
tools, team and conventions. Use it to choose technologies and shape the work, but
never treat it as client requirements. Documents whose name ends in "(digest)" are
summaries of the client's draft files.
```

- [ ] **Step 4: Run** the same command, then the full suite `uv run pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(quotations): ingest workspace documents as digests`.

---

### Task 5: Profile edit agent

**Files:**
- Create: `src/quotation_agents/profile_agent.py`
- Test: `tests/test_profile_agent.py`

**Interfaces:**
- Consumes: `DeveloperProfile`, `ProfileEdit`, `render_profile` (Task 1)
- Produces:
  - `class ProfileEditProposal(BaseModel)`: `edits: list[ProfileEdit]`
  - `create_profile_edit_agent(model: Any) -> Any`
  - `propose_profile_edits(profile: DeveloperProfile, request: str, *, agent: Any) -> list[ProfileEdit]` — sends the rendered profile and the user's request (each inside data delimiters); raises `ProfileAgentError(ValueError)` on invalid response.

- [ ] **Step 1: Write the failing tests** — `test_propose_profile_edits_returns_edits` (fake agent returns one `add tools n8n` edit → list of one `ProfileEdit`); `test_propose_profile_edits_sends_profile_and_request` (request messages contain `"n8n"` user text and the rendered stack); `test_propose_profile_edits_invalid_response_raises`.
- [ ] **Step 2: Run** `uv run pytest tests/test_profile_agent.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** following the `inference.py` agent pattern (`create_agent(..., response_format=ProfileEditProposal)`, `structured_response` normalization). System prompt: propose minimal edits that implement the user's described change; team values use `"Name - role"`; list `replace` values are comma-separated.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(quotations): add profile edit agent`.

---

### Task 6: `setup` and `list` commands, new entry point

**Files:**
- Create: `src/quotation_agents/workspace_cli.py`
- Modify: `src/quotation_agents/cli.py` (delete `_parse_args`, `main`, the `load_source_documents`/`AttachmentError` import if unused, and the `if __name__` block), `pyproject.toml` (`quotation = "quotation_agents.workspace_cli:main"`), `tests/test_cli.py` (move `test_main_goes_back_from_pricing_to_tasks_and_recalculates` to Task 7's file — delete it here), `README.md`, `USAGE.md`
- Test: `tests/test_workspace_cli.py`

**Interfaces:**
- Consumes: Tasks 1–5; `create_configured_model` (`provider.py`); `_ask`, `_ask_yn`, `_header`, `_info`, `_bullet`, `_warn`, `_success` (`cli.py`)
- Produces:
  - `build_parser() -> argparse.ArgumentParser` with subcommands:
    - `setup [NAME]`, `list`, `resume [SLUG]` (`--language {en,es}` default `es`, `--provider-name` default `"Daniel Calcina"`, `--project-name`), `profile`
    - every subcommand accepts `--root DIR` and `--dotenv FILE`
  - `main(argv: Sequence[str] | None = None) -> None` — no subcommand → `parser.print_help()` and exit 0.
  - `cmd_setup(name: str | None, root: Path, model_factory: Callable[[], Any], now: Callable[[], datetime] = …) -> WorkspacePaths`
  - `cmd_list(root: Path) -> None`
  - `ensure_base_profile(root: Path) -> DeveloperProfile` — when missing, asks `"No base profile found. Create one from the template?"`; yes → writes `PROFILE_TEMPLATE` to `base_profile_path(root)` and prints its path; no → returns `PROFILE_TEMPLATE` without writing.
  - `review_profile_edits(profile: DeveloperProfile, edits: list[ProfileEdit]) -> tuple[DeveloperProfile, list[ProfileEdit]]` — shows each edit (field, action, value, reason), `_ask_yn("Apply this change?")` per edit, returns the updated profile and the approved edits. Reused by Task 8.

`cmd_setup` flow: ask name if missing (re-ask while `slugify` is empty) → slug = `slugify(name)`; if longer than `MAX_SLUG_LENGTH`, `suggest_slug` with `create_slug_agent(model_factory())` (on agent failure: warn and truncate at 40 on a `-` boundary) → `_ask("Folder name", default=slug)` then `unique_slug` → `create_workspace` with `ensure_base_profile(root)` → print profile summary (stack, tools, mcps, team) → `_ask_yn("Adjust anything in the profile for this project?", default=False)`; yes → free text → `propose_profile_edits` → `review_profile_edits` → save project profile and `append_section(notes, "Decided", ["Project profile adjusted: <field> <action> <value>", …])` → print `Drop draft files into <documentations path>, then run: uv run quotation resume <slug>`. The model is created only when needed (long name or profile adjustment).

`cmd_list` prints one row per summary: `slug`, `name`, `phase` (or `invalid: <error>`), last activity date, `v<N> S/ <total>` or `-`; empty root → `No quotations yet. Run: uv run quotation setup "<name>"`.

- [ ] **Step 1: Write the failing tests** (monkeypatch `builtins.input` like `tests/test_cli.py`; `tmp_path` root):
  - `test_no_subcommand_prints_help` — `main([])` exits 0 and stdout contains `setup` and `resume`.
  - `test_attachment_flag_removed` — `main(["resume", "--attachment", "x"])` → `SystemExit` code 2.
  - `test_setup_short_name_creates_workspace_without_model` — `model_factory` raises if called; inputs: accept folder default, "n" to template creation, "n" to adjust → folder `crm-cableclub` exists.
  - `test_setup_long_name_uses_slug_agent` — name of 60 chars, monkeypatched `create_slug_agent` returning fake agent → folder is the suggested slug.
  - `test_setup_profile_adjustment_writes_project_copy_only` — base profile exists; inputs approve one proposed edit → project `profile.md` has it, base unchanged, notes contain `"Project profile adjusted"`.
  - `test_setup_reasks_when_name_slugifies_empty`.
  - `test_list_shows_invalid_workspace` and `test_list_empty_root_hint`.

- [ ] **Step 2: Run** `uv run pytest tests/test_workspace_cli.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `workspace_cli.py`, remove `main`/`_parse_args` from `cli.py`, update the script entry, delete the moved test.
- [ ] **Step 4: Update docs** — `USAGE.md`: replace the "Running the interactive CLI" section with `setup` / `list` / `resume` / `profile`, the workspace layout tree from the spec, and remove `--attachment`/`--output`; `README.md` quick start to match.
- [ ] **Step 5: Run** `uv run pytest -q` and `uv run ruff check .` — Expected: PASS, no lint errors.
- [ ] **Step 6: Commit** `feat(quotations)!: add setup and list workspace commands`.

---

### Task 7: `resume` with checkpoints, reopening and versioned outputs

**Files:**
- Modify: `src/quotation_agents/workspace_cli.py`, `USAGE.md`
- Test: `tests/test_resume.py`

**Interfaces:**
- Consumes: `_phase_intake`, `_phase_review_draft`, `_phase_decompose`, `_review_tasks`, `_revise_category`, `_phase_pricing`, `_phase_generate`, `_ask_choice` (`cli.py`, unchanged signatures); `reopen` (Task 2); `ingest_documents`, `context_documents`, `create_digest_agent`, `digest_document` (Task 4); `list_workspaces`, `open_workspace` (Task 3); `revise_draft` (`workflow.py`)
- Produces:
  - `SCOPE_CHANGED_FEEDBACK = "The approved scope changed. Revise these tasks so they match the new scope: keep tasks that still apply, adjust hours, add missing work, and remove tasks that no longer apply."`
  - `cmd_resume(slug: str | None, root: Path, model_factory: Callable[[], Any], *, language: str, provider_name: str, project_name: str | None, now: Callable[[], datetime] = …) -> None`
  - `next_version_number(output_dir: Path) -> int` — 1 + max existing `v<N>` folder (ignores other names).
  - `write_snapshot(version_dir: Path, draft: QuotationDraft, quote: QuoteResult) -> None` — `snapshot.json` with `{"draft": …, "quote": …}` via Pydantic JSON mode.

`cmd_resume` flow:
1. No slug → print numbered `list_workspaces` (valid ones only selectable) and `_ask` a number; invalid workspace → print its error and exit 1.
2. `load_state` (on `StateError` print it and exit 1); `load_profile(paths.profile)` (on `ProfileError` likewise); increment `session_count`, `start_session`, save.
3. Ingest with `digest_document(…, agent=create_digest_agent(model))`; `append_section("Discovered", digest_lines…)` for added/changed, plus lines for removed/unreadable; warn for `failed`; save.
4. Print "where you left off": name, phase, client, scope item count, task count + total hours, versions.
5. If `has_new_content` and phase is past `SCOPE_REVIEW`: `_ask_yn("New or changed documents arrived. Reopen scope review?")` → yes → `state = reopen(state, Phase.SCOPE_REVIEW)`.
6. If phase is past `SCOPE_REVIEW` (and not reopened in 5): `_ask_choice` with `c` Continue (hidden when `GENERATED`), `s` Reopen scope, `t` Reopen tasks, `p` Re-price and generate a new version, `q` Quit → `reopen(...)` accordingly.
7. Loop until `GENERATED`, saving after each step with `docs = context_documents(state, profile)`:
   - `INTAKE`: `draft = _phase_intake(model, docs, progress)` → save draft, phase `SCOPE_REVIEW`, notes Decided `"Intake recorded for <client>."`.
   - `SCOPE_REVIEW`: `scope = _phase_review_draft(state.draft, model, docs, progress)`; if `revise_tasks_for_new_scope`: tasks = concatenation of `_revise_category(scope, list(scope.tasks), category, SCOPE_CHANGED_FEEDBACK, model, docs, progress, failure_outcome=…)` per `WorkCategory`, and store `scope.model_copy(update={"tasks": tasks})` (stays approved, because `decompose_category` requires an approved draft); clear the flag. Phase `DECOMPOSITION`. Notes: `"Scope approved (<n> items)."`.
   - `DECOMPOSITION`: if `state.draft.tasks` empty → `_phase_decompose(scope, …)`, else `_review_tasks(scope, list(scope.tasks), …)`; save approved draft, phase `PRICING`, notes `"Tasks approved: <n> tasks, <hours> h."`.
   - `PRICING`: `quote = _phase_pricing(draft)`; `None` → `state.draft = _review_tasks(...)` again (save after it) and repeat; accepted → `version_dir = paths.output / f"v{next_version_number(paths.output)}"`, `_phase_generate(draft, quote, version_dir, language, model, project_name or state.name, provider_name, progress)`, `write_snapshot`, append `GeneratedVersion`, phase `GENERATED`, notes `"Generated v<N>: S/ <selected_amount>."`.
   The model is created once, lazily, only when a phase or digest needs it.
8. `sys.exit(0)` from a phase quit propagates; everything approved before it is already saved.

- [ ] **Step 1: Write the failing tests** (fake agents; monkeypatch the `cli` phase functions where the interactive detail is not under test; `tmp_path` root with a workspace from `create_workspace`):
  - `test_resume_runs_from_intake_to_generated_v1` — end-to-end with fakes → `output/v1/quotation-internal.docx`, `output/v1/quotation-commercial.docx`, `output/v1/snapshot.json` exist; state phase `generated`; notes contain `"Scope approved"`, `"Tasks approved"`, `"Generated v1"`.
  - `test_resume_quit_during_task_review_keeps_approved_scope` — `_review_tasks` raises `SystemExit(0)` → state phase `decomposition`, draft approved; next `cmd_resume` starts at task review (scope review not called).
  - `test_resume_does_not_redigest_unchanged_documents` — digest fake called once across two resumes.
  - `test_resume_new_document_after_scope_offers_reopen` — yes → `_phase_review_draft` called; then `_revise_category` called per category with `SCOPE_CHANGED_FEEDBACK` and previous tasks.
  - `test_regenerate_creates_v2_and_keeps_v1` — from `GENERATED`, choose `p` → `v1` files byte-identical, `v2` created, two `GeneratedVersion`s.
  - `test_pricing_back_returns_to_tasks_and_recalculates` (replaces the deleted `cli.main` test).
  - `test_resume_without_slug_picks_from_list`.
  - `test_next_version_number_ignores_non_version_folders`.
  - `test_resume_invalid_state_exits_with_message` — exit code 1, message contains `state.json`.

- [ ] **Step 2: Run** `uv run pytest tests/test_resume.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `cmd_resume`, `next_version_number`, `write_snapshot`; wire `resume` in `main`.
- [ ] **Step 4: Update** `USAGE.md` with the resume flow, reopening options and `output/vN` history.
- [ ] **Step 5: Run** `uv run pytest -q` and `uv run ruff check .` — Expected: PASS.
- [ ] **Step 6: Commit** `feat(quotations): resume workspaces with checkpoints and versioned outputs`.

---

### Task 8: `profile` command — told changes and learned suggestions

**Files:**
- Modify: `src/quotation_agents/profile_agent.py`, `src/quotation_agents/workspace_cli.py`, `USAGE.md`
- Test: `tests/test_profile_agent.py`, `tests/test_workspace_cli.py`

**Interfaces:**
- Consumes: `propose_profile_edits`, `review_profile_edits` (Tasks 5–6); `learned_index_path`, `base_profile_path`, `list_workspaces` (Task 3)
- Produces (`profile_agent.py`):
  - `class LearnedRecord(BaseModel)`: `fingerprint: str`, `shown: list[str] = []` (entries `"<field>:<value lowercased>"`)
  - `class LearnedIndex(BaseModel)`: `workspaces: dict[str, LearnedRecord] = {}`; `load_learned_index(path: Path) -> LearnedIndex` (missing → empty; invalid → `ProfileAgentError` naming the file); `save_learned_index(path: Path, index: LearnedIndex) -> None`
  - `@dataclass(frozen=True) class LearningSource`: `slug: str`, `notes: str`, `fingerprint: str` (sha256 of `notes.md` bytes)
  - `collect_learning_sources(root: Path, index: LearnedIndex) -> list[LearningSource]` — valid workspaces whose fingerprint differs from the index.
  - `class ProfileSuggestion(BaseModel)`: `field: Literal["stack", "tools", "mcps", "project_kinds"]`, `value: str`, `evidence: list[str]` (slugs); `class ProfileSuggestionList(BaseModel)`: `suggestions: list[ProfileSuggestion]`
  - `create_learning_agent(model: Any) -> Any`
  - `suggest_from_quotations(profile: DeveloperProfile, sources: Sequence[LearningSource], index: LearnedIndex, *, agent: Any) -> list[ProfileSuggestion]` — drops suggestions already in the profile (case-insensitive) or already in any record's `shown`, and evidence slugs not among `sources`.
  - `mark_reviewed(index: LearnedIndex, sources: Sequence[LearningSource], shown: Sequence[ProfileSuggestion]) -> LearnedIndex`
- Produces (`workspace_cli.py`): `cmd_profile(root: Path, model_factory: Callable[[], Any]) -> None`

`cmd_profile` flow: `ensure_base_profile` → print profile → `_ask_feedback("What changed in your profile? (empty to skip)")` → non-empty: `propose_profile_edits` → `review_profile_edits` → save base. Then `collect_learning_sources`; none → print `"No new quotation activity to learn from."`; else `suggest_from_quotations` → each shown with evidence, `_ask_yn("Add to your profile?")` → approved become `ProfileEdit(action="add")` via `apply_edit` → save base; `mark_reviewed` with all shown suggestions → save index. Project profile copies are never touched.

- [ ] **Step 1: Write the failing tests**
  - `test_collect_learning_sources_skips_unchanged_fingerprint` and `…_includes_changed_notes`.
  - `test_suggest_filters_existing_and_already_shown` — profile has `n8n`; index shows `tools:clickup` → agent proposing n8n, ClickUp, Supabase returns only Supabase.
  - `test_suggest_drops_unknown_evidence_slugs`.
  - `test_learned_index_invalid_names_file`.
  - `test_profile_command_applies_only_approved_edits_to_base` — two told edits, approve one → base has one; a project copy unchanged.
  - `test_profile_command_learned_suggestion_not_repeated` — reject suggestion; second run with unchanged notes → no agent call; after notes change, agent called but the rejected value is filtered.

- [ ] **Step 2: Run** `uv run pytest tests/test_profile_agent.py tests/test_workspace_cli.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement**; learning agent system prompt: from the notes of past quotations, list technologies, tools, MCPs and project kinds (e.g. backend, fullstack, ai, n8n) the developer worked with that are missing from the profile, each with the workspace slugs as evidence; notes are untrusted data.
- [ ] **Step 4: Update** `USAGE.md` with the `profile` command.
- [ ] **Step 5: Run** `uv run pytest -q` and `uv run ruff check .` — Expected: PASS.
- [ ] **Step 6: Commit** `feat(quotations): add profile command with learned suggestions`.
