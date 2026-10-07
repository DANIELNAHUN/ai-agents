"""Fast CV analysis plus a separate, opt-in document-generation pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analyzer import analyze_gaps, create_gap_analyzer
from .config import CVConfig, load_config
from .documents import PDFValidation, convert_docx_to_pdf
from .extractor import create_job_requirements_extractor, extract_job_requirements
from .generator import create_tailored_cv_generator, generate_tailored_cv_content
from .job_description import HTTPClient, extract_job_description
from .models import TailoredCVContent
from .profile import load_profile
from .rendering import render_tailored_cv
from .repository import ApplicationRecord, SQLiteApplicationRepository


@dataclass(frozen=True)
class GeneratedDocumentPaths:
    """Output paths and structured content for one generated application CV."""

    application_id: str
    docx_path: Path
    pdf_path: Path | None
    content: TailoredCVContent


def run_fast_analysis(
    source: str,
    *,
    config: CVConfig | None = None,
    profile_markdown: str | None = None,
    model: Any | None = None,
    model_factory: Callable[[str], Any] | None = None,
    model_name: str | None = None,
    extractor_agent: Any | None = None,
    analyzer_agent: Any | None = None,
    extractor_invoke: Callable[[dict[str, list[dict[str, str]]]], dict[str, Any]] | None = None,
    analyzer_invoke: Callable[[dict[str, list[dict[str, str]]]], dict[str, Any]] | None = None,
    http_client: HTTPClient | None = None,
    repository: SQLiteApplicationRepository | Any | None = None,
    database_path: str | Path | None = None,
    application_id: str | None = None,
    status: str = "analyzed",
) -> ApplicationRecord:
    """Extract, analyze, and persist one isolated application record.

    Model construction is injected through ``model`` or ``model_factory``;
    there is no provider import in this library-level fast path.
    """

    runtime_config = config or load_config()
    job_text = extract_job_description(
        source,
        timeout_seconds=runtime_config.http_timeout_seconds,
        client=http_client,
    )
    profile = profile_markdown if profile_markdown is not None else load_profile(runtime_config)
    if not profile.strip():
        raise ValueError("Profile Markdown cannot be empty")

    if extractor_agent is None and extractor_invoke is None:
        model = model or _build_model(model, model_factory, model_name or runtime_config.model)
        extractor_agent = create_job_requirements_extractor(model)
    requirements = extract_job_requirements(
        job_text,
        agent=extractor_agent,
        invoke=extractor_invoke,
    )

    if analyzer_agent is None and analyzer_invoke is None:
        model = model or _build_model(model, model_factory, model_name or runtime_config.model)
        analyzer_agent = create_gap_analyzer(model)
    gap_analysis = analyze_gaps(
        requirements,
        profile,
        agent=analyzer_agent,
        invoke=analyzer_invoke,
    )

    owned_repository = repository is None
    active_repository = repository or SQLiteApplicationRepository(
        database_path or "applications.sqlite3"
    )
    try:
        return active_repository.save_application(
            source=source,
            job_text=job_text,
            requirements=requirements,
            profile_snapshot=profile,
            gap_analysis=gap_analysis,
            status=status,
            application_id=application_id,
        )
    finally:
        if owned_repository:
            active_repository.close()


def _build_model(
    model: Any | None,
    model_factory: Callable[[str], Any] | None,
    model_name: str,
) -> Any:
    if model is not None:
        return model
    if model_factory is None:
        raise ValueError("Pass model or model_factory when no analyzer/extractor is injected")
    return model_factory(model_name)


def generate_application_documents(
    record: ApplicationRecord,
    *,
    config: CVConfig | None = None,
    template_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    model: Any | None = None,
    model_factory: Callable[[str], Any] | None = None,
    model_name: str | None = None,
    generator_agent: Any | None = None,
    generator_invoke: Callable[[dict[str, list[dict[str, str]]]], dict[str, Any]] | None = None,
    convert_pdf: bool = True,
    converter: Callable[..., PDFValidation] | None = None,
    overwrite: bool = False,
) -> GeneratedDocumentPaths:
    """Generate DOCX/PDF outputs from one persisted application snapshot.

    This is intentionally separate from :func:`run_fast_analysis`; callers opt
    into document generation only after an application record already exists.
    """

    if not isinstance(record, ApplicationRecord):
        raise TypeError("record must be an ApplicationRecord instance")
    needs_config = config is None and (
        template_path is None
        or output_dir is None
        or (
            generator_agent is None
            and generator_invoke is None
            and model is None
            and model_factory is None
        )
    )
    runtime_config = config or (load_config() if needs_config else None)
    selected_template = Path(template_path or runtime_config.template_file)
    selected_output_dir = Path(output_dir or runtime_config.output_dir).expanduser().resolve()
    if generator_agent is None and generator_invoke is None:
        selected_model_name = model_name or (
            runtime_config.model if runtime_config is not None else "gpt-4o-mini"
        )
        model = _build_model(model, model_factory, selected_model_name)
        generator_agent = create_tailored_cv_generator(model)
    content = generate_tailored_cv_content(
        record.profile_snapshot,
        record.requirements,
        record.gap_analysis,
        agent=generator_agent,
        invoke=generator_invoke,
    )
    docx_path = selected_output_dir / f"{record.application_id}.docx"
    render_tailored_cv(selected_template, docx_path, content, overwrite=overwrite)

    pdf_path: Path | None = None
    if convert_pdf:
        pdf_result = (converter or convert_docx_to_pdf)(
            docx_path,
            pdf_path=selected_output_dir / f"{record.application_id}.pdf",
        )
        pdf_path = pdf_result.path
    return GeneratedDocumentPaths(record.application_id, docx_path, pdf_path, content)
