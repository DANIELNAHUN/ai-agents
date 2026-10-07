import pytest
from pydantic import ValidationError

from cv_agents.models import GapAnalysis, JobRequirements, RequirementAssessment


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


def test_gap_analysis_separates_evidence_states_and_bounds_fit_score() -> None:
    analysis = GapAnalysis(
        demonstrated=[
            RequirementAssessment(
                requirement="Python",
                evidence_references=["Skills > Languages"],
                rationale="The profile explicitly lists Python.",
            )
        ],
        uncertain=[
            RequirementAssessment(
                requirement="Kubernetes",
                rationale="The profile does not provide enough evidence to assess it.",
            )
        ],
        learning_recommendations=["Review the role's Kubernetes expectations."],
        fit_score=72.5,
    )

    assert analysis.demonstrated[0].evidence_references == ["Skills > Languages"]
    assert analysis.uncertain[0].evidence_references == []

    with pytest.raises(ValidationError):
        GapAnalysis(fit_score=101)
