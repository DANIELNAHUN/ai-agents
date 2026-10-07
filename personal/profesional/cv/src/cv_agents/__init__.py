"""Reusable building blocks for the CV agent pipeline."""

from .analyzer import (
    GAP_ANALYSIS_SYSTEM_PROMPT,
    analyze_gaps,
    create_gap_analysis_analyzer,
    create_gap_analyzer,
)
from .config import ConfigurationError, CVConfig, load_config
from .documents import (
    DocumentValidationError,
    DOCXValidation,
    PDFConversionError,
    PDFValidation,
    convert_docx_to_pdf,
    validate_docx,
    validate_pdf,
)
from .extractor import create_job_requirements_extractor, extract_job_requirements
from .generator import (
    TAILORED_CV_SYSTEM_PROMPT,
    create_tailored_cv_generator,
    generate_tailored_cv_content,
)
from .job_description import (
    DEFAULT_USER_AGENT,
    JobDescriptionError,
    extract_job_description,
    fetch_job_description,
    html_to_text,
)
from .models import (
    GapAnalysis,
    GapStatus,
    JobRequirements,
    RequirementAssessment,
    TailoredCVContent,
    TailoredExperience,
)
from .pipeline import GeneratedDocumentPaths, generate_application_documents, run_fast_analysis
from .profile import ProfileLoadError, load_profile
from .provider import ProviderError, create_openai_model
from .rendering import REQUIRED_MARKERS, TemplateRenderError, render_tailored_cv
from .repository import (
    ApplicationRecord,
    ApplicationRepository,
    SQLiteApplicationRepository,
    deterministic_application_id,
)

__all__ = [
    "CVConfig",
    "ConfigurationError",
    "DOCXValidation",
    "DEFAULT_USER_AGENT",
    "DocumentValidationError",
    "GAP_ANALYSIS_SYSTEM_PROMPT",
    "GapAnalysis",
    "GapStatus",
    "JobDescriptionError",
    "JobRequirements",
    "PDFConversionError",
    "PDFValidation",
    "ApplicationRecord",
    "ApplicationRepository",
    "ProfileLoadError",
    "ProviderError",
    "RequirementAssessment",
    "REQUIRED_MARKERS",
    "SQLiteApplicationRepository",
    "TAILORED_CV_SYSTEM_PROMPT",
    "TailoredCVContent",
    "TailoredExperience",
    "TemplateRenderError",
    "analyze_gaps",
    "create_job_requirements_extractor",
    "create_gap_analysis_analyzer",
    "create_gap_analyzer",
    "create_openai_model",
    "create_tailored_cv_generator",
    "deterministic_application_id",
    "extract_job_description",
    "extract_job_requirements",
    "fetch_job_description",
    "generate_application_documents",
    "generate_tailored_cv_content",
    "html_to_text",
    "load_config",
    "load_profile",
    "convert_docx_to_pdf",
    "render_tailored_cv",
    "run_fast_analysis",
    "validate_docx",
    "validate_pdf",
    "GeneratedDocumentPaths",
]
