"""Reusable building blocks for the CV agent pipeline."""

from .analyzer import (
    GAP_ANALYSIS_SYSTEM_PROMPT,
    analyze_gaps,
    create_gap_analysis_analyzer,
    create_gap_analyzer,
)
from .config import ConfigurationError, CVConfig, load_config
from .extractor import create_job_requirements_extractor, extract_job_requirements
from .job_description import (
    DEFAULT_USER_AGENT,
    JobDescriptionError,
    extract_job_description,
    fetch_job_description,
    html_to_text,
)
from .models import GapAnalysis, GapStatus, JobRequirements, RequirementAssessment
from .pipeline import run_fast_analysis
from .profile import ProfileLoadError, load_profile
from .provider import ProviderError, create_openai_model
from .repository import (
    ApplicationRecord,
    ApplicationRepository,
    SQLiteApplicationRepository,
    deterministic_application_id,
)

__all__ = [
    "CVConfig",
    "ConfigurationError",
    "DEFAULT_USER_AGENT",
    "GAP_ANALYSIS_SYSTEM_PROMPT",
    "GapAnalysis",
    "GapStatus",
    "JobDescriptionError",
    "JobRequirements",
    "ApplicationRecord",
    "ApplicationRepository",
    "ProfileLoadError",
    "ProviderError",
    "RequirementAssessment",
    "SQLiteApplicationRepository",
    "analyze_gaps",
    "create_job_requirements_extractor",
    "create_gap_analysis_analyzer",
    "create_gap_analyzer",
    "create_openai_model",
    "deterministic_application_id",
    "extract_job_description",
    "extract_job_requirements",
    "fetch_job_description",
    "html_to_text",
    "load_config",
    "load_profile",
    "run_fast_analysis",
]
