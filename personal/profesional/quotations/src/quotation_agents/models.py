"""Structured editable state for a software quotation."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkCategory(StrEnum):
    """The work categories used by the quotation workflow."""

    PLANNING_AND_COORDINATION = "planning_and_coordination"
    BACKEND = "backend"
    FRONTEND = "frontend"
    DEVOPS = "devops"


class ApprovalState(StrEnum):
    """Human approval state for an editable quotation draft."""

    PENDING = "pending"
    APPROVED = "approved"


class QuotationTask(BaseModel):
    """One editable task assigned to a quotation work category."""

    model_config = ConfigDict(extra="forbid")

    category: WorkCategory
    description: str = Field(min_length=1)
    estimated_hours: Decimal | None = Field(default=None, gt=0)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value


class QuotationDraft(BaseModel):
    """Editable quotation intake and scope awaiting human review."""

    model_config = ConfigDict(extra="forbid")

    client_company: str = Field(min_length=1)
    original_request: str = Field(min_length=1)
    inferred_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tasks: list[QuotationTask] = Field(default_factory=list)
    approval_state: ApprovalState = ApprovalState.PENDING

    @field_validator("client_company")
    @classmethod
    def validate_client_company(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("client_company must not be blank")
        return value

    @field_validator("original_request")
    @classmethod
    def validate_original_request(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_request must not be blank")
        return value
