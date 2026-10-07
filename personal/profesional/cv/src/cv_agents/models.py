"""Pydantic schemas used at the job-description boundary."""

from __future__ import annotations

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
