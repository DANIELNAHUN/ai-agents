from decimal import Decimal

import pytest
from pydantic import ValidationError

from quotation_agents.models import ApprovalState, QuotationDraft, QuotationTask, WorkCategory


def test_draft_requires_client_and_rejects_blank_client() -> None:
    with pytest.raises(ValidationError):
        QuotationDraft(original_request="Build a booking site")
    with pytest.raises(ValidationError, match="client_company must not be blank"):
        QuotationDraft(client_company="  ", original_request="Build a booking site")


def test_draft_preserves_original_request_and_starts_pending() -> None:
    request = "  Build a booking site\nwith payment support.  "

    draft = QuotationDraft(client_company="Example Ltd", original_request=request)

    assert draft.original_request == request
    assert draft.approval_state is ApprovalState.PENDING


def test_scope_and_approval_state_are_editable() -> None:
    draft = QuotationDraft(
        client_company="Example Ltd",
        original_request="Build a booking site",
        inferred_scope=["Booking calendar"],
    )
    draft.inferred_scope.append("Payment integration")
    approved = draft.model_copy(update={"approval_state": ApprovalState.APPROVED})

    assert draft.inferred_scope == ["Booking calendar", "Payment integration"]
    assert approved.approval_state is ApprovalState.APPROVED
    assert draft.approval_state is ApprovalState.PENDING


@pytest.mark.parametrize("category", list(WorkCategory))
def test_tasks_accept_each_work_category(category: WorkCategory) -> None:
    task = QuotationTask(category=category, description="Review requirements")

    assert task.category is category


def test_models_reject_extra_fields_and_blank_task_descriptions() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuotationDraft(
            client_company="Example Ltd",
            original_request="Build a booking site",
            price=Decimal("100.00"),
        )
    with pytest.raises(ValidationError, match="description must not be blank"):
        QuotationTask(category=WorkCategory.BACKEND, description="  ")
