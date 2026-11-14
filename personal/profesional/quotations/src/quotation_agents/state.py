"""Persistent machine state for one quotation workspace (state.json)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import ApprovalState, QuotationDraft
from .pricing import QuoteResult


class StateError(ValueError):
    """Raised when a workspace state file cannot be read or is invalid."""


class Phase(StrEnum):
    """The workflow phase that runs next for a workspace."""

    INTAKE = "intake"
    SCOPE_REVIEW = "scope_review"
    DECOMPOSITION = "decomposition"
    PRICING = "pricing"
    GENERATED = "generated"


PHASE_ORDER = tuple(Phase)


class DocumentDigest(BaseModel):
    """Structured summary of one draft document, produced once."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    """What the workspace knows about one file in documentations/."""

    model_config = ConfigDict(extra="forbid")

    name: str
    sha256: str
    status: Literal["active", "removed", "unreadable"]
    digest: DocumentDigest | None = None
    error: str | None = None
    updated_at: datetime


class GeneratedVersion(BaseModel):
    """One generated quotation kept as history under output/vN."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(gt=0)
    created_at: datetime
    total: Decimal
    path: str


class WorkspaceState(BaseModel):
    """Everything needed to resume a quotation without re-reading documents."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    phase: Phase = Phase.INTAKE
    session_count: int = Field(default=0, ge=0)
    draft: QuotationDraft | None = None
    quote: QuoteResult | None = None
    revise_tasks_for_new_scope: bool = False
    documents: list[DocumentRecord] = Field(default_factory=list)
    versions: list[GeneratedVersion] = Field(default_factory=list)


def is_past(phase: Phase, reference: Phase) -> bool:
    """True when ``phase`` comes after ``reference`` in the workflow."""

    return PHASE_ORDER.index(phase) > PHASE_ORDER.index(reference)


def load_state(path: Path) -> WorkspaceState:
    """Read and validate state.json, naming the file and field on failure."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateError(f"{path}: cannot read state file: {exc.strerror}") from exc
    try:
        return WorkspaceState.model_validate_json(text)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "file"
        raise StateError(f"{path}: {location}: {first['msg']}") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise StateError(f"{path}: invalid JSON: {exc}") from exc


def save_state(path: Path, state: WorkspaceState) -> None:
    """Write state.json atomically so a crash never leaves a half-written file."""

    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)


def reopen(
    state: WorkspaceState,
    phase: Literal[Phase.SCOPE_REVIEW, Phase.DECOMPOSITION, Phase.PRICING],
) -> WorkspaceState:
    """Go back to an earlier phase, keeping later work as a draft to revise."""

    if phase not in (Phase.SCOPE_REVIEW, Phase.DECOMPOSITION, Phase.PRICING):
        raise StateError(f"Cannot reopen phase {phase!r}")
    if state.draft is None:
        raise StateError("Cannot reopen a phase before intake is recorded")

    update: dict[str, object] = {"phase": phase, "quote": None}
    if phase is Phase.SCOPE_REVIEW:
        update["draft"] = state.draft.model_copy(
            update={"approval_state": ApprovalState.PENDING}
        )
        update["revise_tasks_for_new_scope"] = bool(state.draft.tasks)
    return state.model_copy(update=update)
