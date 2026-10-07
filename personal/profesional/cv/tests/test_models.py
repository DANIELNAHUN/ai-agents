import pytest
from pydantic import ValidationError

from cv_agents.models import JobRequirements


def test_job_requirements_accepts_structured_fields() -> None:
    requirements = JobRequirements(
        title="Senior Python Engineer",
        summary="Build and operate backend services.",
        responsibilities=["Design APIs"],
        required_skills=["Python", "PostgreSQL"],
        preferred_skills=["AWS"],
        qualifications=["Five years of backend experience"],
        seniority="Senior",
        location="Remote",
    )

    assert requirements.required_skills == ["Python", "PostgreSQL"]


def test_job_requirements_requires_summary_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobRequirements(title="Missing summary", unexpected="not allowed")
