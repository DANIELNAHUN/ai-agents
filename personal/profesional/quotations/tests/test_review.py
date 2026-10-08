from decimal import Decimal

import pytest

from quotation_agents import (
    ApprovalState,
    DraftApprovalRequiredError,
    QuotationDraft,
    QuotationReviewError,
    QuotationTask,
    QuoteInputs,
    WorkCategory,
    calculate_quote,
    review_quote,
)


def task(category: WorkCategory, description: str, hours: str) -> QuotationTask:
    return QuotationTask(
        category=category,
        description=description,
        estimated_hours=Decimal(hours),
    )


def approved(tasks: list[QuotationTask]) -> QuotationDraft:
    return QuotationDraft(
        client_company="Example Ltd",
        original_request="Build a booking website",
        inferred_scope=["Booking flow"],
        assumptions=["Client provides hosting credentials"],
        tasks=tasks,
        approval_state=ApprovalState.APPROVED,
    )


def test_review_accepts_a_consistent_quote() -> None:
    draft = approved([task(WorkCategory.FRONTEND, "Adjust WordPress header", "2")])
    quote = calculate_quote(draft)

    result = review_quote(draft, quote)

    assert result.passed is True
    assert result.ready_for_document is True
    assert result.errors == ()


def test_review_reports_arithmetic_inconsistency_without_recalculating_the_quote() -> None:
    draft = approved([task(WorkCategory.BACKEND, "Build API", "10")])
    quote = calculate_quote(draft).model_copy(update={"raw_amount": Decimal("301.00")})

    result = review_quote(draft, quote)

    assert result.passed is False
    assert "raw_amount_mismatch" in {issue.code for issue in result.errors}


def test_review_checks_scope_notes_for_blank_assumptions() -> None:
    draft = approved([task(WorkCategory.BACKEND, "Build API", "2")]).model_copy(
        update={"assumptions": [" "]}
    )
    quote = calculate_quote(draft)

    result = review_quote(draft, quote)

    assert result.passed is False
    assert any(issue.code == "blank_scope_note" for issue in result.errors)


def test_review_rejects_pending_draft_before_quote_checks() -> None:
    approved_draft = approved([task(WorkCategory.BACKEND, "Build API", "2")])
    pending = approved_draft.model_copy(update={"approval_state": ApprovalState.PENDING})

    with pytest.raises(DraftApprovalRequiredError):
        review_quote(pending, calculate_quote(approved_draft))


def test_review_rejects_a_quote_from_another_approved_draft() -> None:
    source = approved([task(WorkCategory.BACKEND, "Build API", "2")])
    supplied = approved([task(WorkCategory.BACKEND, "Build API", "3")])

    with pytest.raises(QuotationReviewError, match="does not belong"):
        review_quote(supplied, calculate_quote(source))


def test_review_requires_manual_approval_but_preserves_an_over_ceiling_quote() -> None:
    draft = approved([task(WorkCategory.BACKEND, "Large platform", "2")])
    quote = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("10000.01")))

    result = review_quote(draft, quote)

    assert result.passed is True
    assert result.ready_for_document is False
    assert result.requires_manual_approval is True
    assert quote.selected_amount == Decimal("10000.01")
    assert any(issue.code == "manual_approval_required" for issue in result.warnings)
