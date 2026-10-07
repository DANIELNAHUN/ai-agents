"""Pydantic schemas used by the CV analysis boundaries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobRequirements(BaseModel):
    """Validated requirements extracted from one job description."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, description="Job title when stated")
    company: str | None = Field(default=None, description="Company when stated")
    summary: str = Field(description="Concise factual summary of the role")
    responsibilities: list[str] = Field(
        default_factory=list,
        description="Concrete responsibilities explicitly stated in the description",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description="Skills or technologies explicitly required for the role",
    )
    preferred_skills: list[str] = Field(
        default_factory=list,
        description="Skills or technologies described as preferred or nice to have",
    )
    qualifications: list[str] = Field(
        default_factory=list,
        description="Education, certifications, or experience requirements",
    )
    seniority: str | None = Field(default=None, description="Seniority level when stated")
    location: str | None = Field(default=None, description="Work location or remote status")
    employment_type: str | None = Field(default=None, description="Employment type when stated")


GapStatus = Literal["demonstrated", "partial", "missing", "uncertain"]


class RequirementAssessment(BaseModel):
    """Evidence-backed assessment of one job requirement.

    ``missing`` means that the profile contains explicit negative evidence. A
    profile that simply does not mention a requirement must be classified as
    ``uncertain`` instead.
    """

    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, description="Requirement being assessed")
    evidence_references: list[str] = Field(
        default_factory=list,
        description="Short quotes or Markdown section references from the profile",
    )
    rationale: str = Field(min_length=1, description="Factual reason for the assessment")


class GapAnalysis(BaseModel):
    """Validated, bounded skills-gap analysis for one job description."""

    model_config = ConfigDict(extra="forbid")

    demonstrated: list[RequirementAssessment] = Field(
        default_factory=list,
        description="Requirements directly supported by profile evidence",
    )
    partial: list[RequirementAssessment] = Field(
        default_factory=list,
        description="Requirements supported by incomplete or adjacent evidence",
    )
    missing: list[RequirementAssessment] = Field(
        default_factory=list,
        description="Requirements contradicted by explicit profile evidence",
    )
    uncertain: list[RequirementAssessment] = Field(
        default_factory=list,
        description="Requirements for which the profile has insufficient evidence",
    )
    learning_recommendations: list[str] = Field(
        default_factory=list,
        description="Specific, factual recommendations for closing identified gaps",
    )
    fit_score: float = Field(
        ge=0,
        le=100,
        description="Overall fit score on a 0-100 scale; not a hiring probability",
    )
