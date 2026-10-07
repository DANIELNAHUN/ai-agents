# CV Agent Pipeline

This package analyzes a job description against the canonical Markdown profile in
an Obsidian vault and stores one isolated application snapshot in SQLite. The
fast analysis path is the normal workflow. Tailored DOCX/PDF generation is an
explicit, opt-in Python API stage.

## Quick path

From the repository root:

```bash
cd personal/profesional/cv
uv sync
```

Create `.env` in `personal/profesional/cv/` with configuration values only:

```dotenv
CV_VAULT_ROOT=/path/to/your/obsidian-vault
CV_PROFILE_PATH=profile/professional.md
CV_HTTP_TIMEOUT_SECONDS=15
CV_MODEL=gpt-4o-mini
CV_TEMPLATE_PATH=files/templates/Template CV.docx
CV_OUTPUT_DIR=files/generated
```

The vault root must already exist. `CV_PROFILE_PATH` must be an existing
Markdown file path relative to that vault. Do not put API keys, profile text, or
other professional content in `.env`; provide the provider secret through the
process environment or an external secret manager:

```bash
export OPENAI_API_KEY="..."
```

Run the fast path with either a URL or manually supplied text:

```bash
uv run cv-analyze --url "https://example.com/jobs/backend-engineer" \
  --db-path applications.sqlite3

uv run cv-analyze --text "Build APIs with Python and maintain production services." \
  --db-path applications.sqlite3
```

The command prints JSON containing the application ID, structured job
requirements, and evidence-based gap analysis. It does not generate a DOCX or
PDF.

## Prerequisites and installation

- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/) installed and available on `PATH`.
- A locally synced Obsidian vault containing the canonical professional profile.
- An OpenAI API key in the process environment for the default provider path.
- LibreOffice with `soffice` on `PATH` only when PDF conversion is requested.

Install the locked project and development dependencies from this directory:

```bash
uv sync
```

Run commands from `personal/profesional/cv/`. The CLI loads `.env` from the
current working directory; it does not accept a `.env` path argument.

## Obsidian profile requirements

The profile is the factual source of truth for analysis and document content.
Configure it with:

| Setting | Requirement |
| --- | --- |
| `CV_VAULT_ROOT` | Existing directory for the local Obsidian vault. |
| `CV_PROFILE_PATH` | Non-absolute `.md` path relative to `CV_VAULT_ROOT`; it must not escape the vault. |

The configuration loader validates the vault and path. The profile loader then
requires the file to exist, be a regular file, and be readable as UTF-8
Markdown. Keep factual updates in that profile rather than relying on transient
agent context.

## Fast analysis workflow

1. Configure the vault and profile in `.env`.
2. Export `OPENAI_API_KEY` and optionally set `CV_MODEL`.
3. Submit one job URL or one text value.
4. Review the JSON requirements and gap categories.
5. Keep the returned `application_id` for any later document-generation step.

The CLI accepts exactly one of these source forms:

| Form | Example |
| --- | --- |
| Positional URL or text | `uv run cv-analyze "https://example.com/jobs/1"` |
| `--url` | `uv run cv-analyze --url "https://example.com/jobs/1"` |
| `--text` | `uv run cv-analyze --text "Job description text"` |

URLs must use `http://` or `https://`. HTML is reduced to visible text; scripts,
styles, templates, and `noscript` content are discarded. A blocked or
unavailable URL can be handled by resubmitting the saved description with
`--text`.

Useful supported options:

```text
--db-path PATH          SQLite file; defaults to CV_DATABASE_PATH or applications.sqlite3
--application-id ID     Explicit stable ID for the application
--status STATUS          Initial status; defaults to analyzed
--model MODEL            Per-invocation override for CV_MODEL
```

## Database and application isolation

Each SQLite file is an independent application history. Use a separate
`--db-path` when histories must not share records. Within one database:

- Omit `--application-id` to receive a deterministic `app-...` ID derived from
  the source, job text, and extracted requirements.
- Repeating the same snapshot reuses that ID and updates the existing record.
- A different source or job snapshot produces a different deterministic ID.
- Use an explicit `--application-id` when an external workflow owns the
  identity, but do not reuse it for unrelated applications.

The record stores the source, retrieved/manual job text, requirements, profile
snapshot, gap analysis, status, and timestamps. The CLI's `--db-path` is the
most explicit way to select a database; `CV_DATABASE_PATH` is read by the CLI
from the process environment, not from the values parsed by the `.env`
configuration loader.

## Optional document generation

There is **no document-generation CLI command**. Call the Python API only after
the fast path has persisted an application record:

```python
from cv_agents import SQLiteApplicationRepository, generate_application_documents

with SQLiteApplicationRepository("applications.sqlite3") as repository:
    record = repository.get_application("app-REPLACE_WITH_THE_RECORDED_ID")
    if record is None:
        raise SystemExit("Application record not found")

    result = generate_application_documents(
        record,
        convert_pdf=False,  # Set True after installing and verifying LibreOffice.
    )

print(result.docx_path)
print(result.pdf_path)  # None when convert_pdf=False
```

`generate_application_documents` uses the persisted profile and analysis
snapshot, calls the tailored-content model, renders the result into
`CV_TEMPLATE_PATH`, and writes `<application_id>.docx` under `CV_OUTPUT_DIR`.
Set `convert_pdf=True` to additionally write the matching PDF. The function
also accepts `template_path`, `output_dir`, `model`/`model_factory`, and an
injected `converter` for controlled integrations or tests.

## DOCX/PDF prerequisites and limitations

- The output template is `files/templates/Template CV.docx`. It is distinct
  from `files/templates/Daniel_Nahun_CV.docx`, which is reference input only and
  must not be configured as `CV_TEMPLATE_PATH`.
- The output template must contain each required marker exactly once. Missing,
  duplicated, or unknown markers fail rendering.
- Rendering writes a separate output file and does not modify the source
  template. Existing DOCX output is not overwritten unless the API is called
  with `overwrite=True`.
- PDF conversion invokes `soffice --headless --convert-to pdf --outdir ...`.
  Install LibreOffice and put `soffice` on `PATH`. If an absolute command path
  is required, supply a custom `converter` that calls
  `convert_docx_to_pdf(..., soffice_command=...)`.
- Structural validation checks that the DOCX is readable and that the PDF has
  at least one page; optional PDF text extraction is not a visual-layout check.
- The automated conversion tests mock the LibreOffice runner. They do not prove
  that a real local conversion succeeded. After real generation, a human must
  open and visually review every DOCX/PDF and the template layout.

For the template marker contract and conversion details, see
[`DOCUMENT_GENERATION.md`](DOCUMENT_GENERATION.md).

## Verification

Run the package checks from `personal/profesional/cv/`:

```bash
uv run pytest
uv run python -m compileall src tests
uv run ruff check src tests
uv run cv-analyze --help
```

The test suite includes mocked provider boundaries, isolated SQLite checks,
template-rendering checks, and mocked `soffice` conversion checks. It does not
replace a real document generation run or the required human visual review.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `CV_VAULT_ROOT is required` | Run from `personal/profesional/cv/` and create `.env` there, or export the required variables. |
| Vault or profile validation fails | Confirm the vault exists and `CV_PROFILE_PATH` is a relative `.md` path inside it. |
| Provider/API error | Confirm dependencies are installed with `uv sync`, `OPENAI_API_KEY` is exported, and `CV_MODEL` names an available model. |
| URL retrieval fails | Verify the URL is HTTP(S), then use `--text` with a saved copy of the job description. |
| Unexpected record replacement | Use a distinct `--application-id` or a separate `--db-path` for unrelated applications. |
| Template marker error | Use `files/templates/Template CV.docx`; verify every required marker occurs exactly once. |
| PDF conversion cannot find `soffice` | Install LibreOffice, add `soffice` to `PATH`, or use the API's custom converter hook. |
| Existing output is rejected | Choose a new output directory or pass `overwrite=True` deliberately through the Python API. |
