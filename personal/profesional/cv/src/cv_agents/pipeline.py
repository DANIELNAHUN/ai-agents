"""Fast, document-generation-independent CV analysis pipeline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analyzer import analyze_gaps, create_gap_analyzer
from .config import CVConfig, load_config
from .extractor import create_job_requirements_extractor, extract_job_requirements
from .job_description import HTTPClient, extract_job_description
from .profile import load_profile
from .repository import ApplicationRecord, SQLiteApplicationRepository


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
