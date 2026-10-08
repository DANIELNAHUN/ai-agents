"""Human-gated workflow operations for quotation drafts."""

from __future__ import annotations

from typing import Any

from .inference import infer_requirements
from .models import ApprovalState, QuotationDraft
from .provider import Invocation


class QuotationWorkflowError(ValueError):
    """Base error for invalid quotation workflow transitions."""


class DraftApprovalRequiredError(QuotationWorkflowError):
    """Raised when downstream work receives a draft without human approval."""


def intake_draft(
    client_company: str,
    original_request: str,
    *,
    invoke: Invocation | None = None,
    model: Any | None = None,
    agent: Any | None = None,
) -> QuotationDraft:
    """Create a pending draft from validated intake and injected inference."""

    inference = infer_requirements(
        client_company,
        original_request,
        invoke=invoke,
        model=model,
        agent=agent,
    )
    return QuotationDraft(
        client_company=client_company,
        original_request=original_request,
        inferred_scope=inference.inferred_scope,
        assumptions=inference.assumptions,
        questions=inference.questions,
        risks=inference.risks,
        approval_state=ApprovalState.PENDING,
    )


create_pending_draft = intake_draft


def approve_draft(draft: QuotationDraft) -> QuotationDraft:
    """Return a copy explicitly marked approved by a human workflow step."""

    return draft.model_copy(update={"approval_state": ApprovalState.APPROVED})


def revise_draft(draft: QuotationDraft, **changes: Any) -> QuotationDraft:
    """Return an edited draft with approval reset to pending.

    The original request is the immutable source of the intake and cannot be
    changed by a revision.
    """

    if "original_request" in changes:
        raise QuotationWorkflowError("original_request cannot be changed during revision")

    revised_data = draft.model_dump()
    revised_data.update(changes)
    revised_data["approval_state"] = ApprovalState.PENDING
    return QuotationDraft.model_validate(revised_data)


edit_draft = revise_draft


def require_approved_draft(draft: QuotationDraft) -> QuotationDraft:
    """Guard downstream proposal generation against unapproved drafts."""

    if draft.approval_state is not ApprovalState.APPROVED:
        raise DraftApprovalRequiredError(
            "Quotation draft must be approved before downstream proposal generation"
        )
    return draft
