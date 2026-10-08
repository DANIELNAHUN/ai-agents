from decimal import Decimal

import pytest

from quotation_agents import (
    ApprovalState,
    DraftApprovalRequiredError,
    Payment,
    QuotationDraft,
    QuotationReviewError,
    QuotationTask,
    QuoteInputs,
    QuoteResult,
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


def _threshold_quote() -> tuple[QuotationDraft, QuoteResult]:
    draft = approved([task(WorkCategory.BACKEND, "Threshold endpoint", "1")])
    quote = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("700.00")))
    return draft, quote


@pytest.mark.parametrize(
    ("milestones", "expected_code"),
    [
        ((Payment(label="Bogus", amount=Decimal("420.00")),), "payment_module_identity"),
        (
            (
                Payment(label="Module A", module_name="Module A", amount=Decimal("210.00")),
                Payment(label="Module A", module_name="Module A", amount=Decimal("210.00")),
            ),
            "payment_module_duplicate",
        ),
        (
            (Payment(label="Module A", module_name="Module B", amount=Decimal("420.00")),),
            "payment_label_mismatch",
        ),
        (
            (Payment(label="Module A", module_name=" ", amount=Decimal("420.00")),),
            "payment_module_identity",
        ),
        (
            (
                Payment(
                    label="Project completion",
                    module_name="Module A",
                    amount=Decimal("420.00"),
                ),
            ),
            "payment_milestone_shape",
        ),
        (
            (
                Payment(label="Project completion", amount=Decimal("210.00")),
                Payment(label="Module A", module_name="Module A", amount=Decimal("210.00")),
            ),
            "payment_milestone_shape",
        ),
    ],
)
def test_review_rejects_reconciled_malformed_threshold_schedules(
    milestones: tuple[Payment, ...], expected_code: str
) -> None:
    draft, quote = _threshold_quote()
    schedule = quote.payment_schedule.model_copy(
        update={"payments": (quote.payment_schedule.payments[0], *milestones)}
    )
    result = review_quote(draft, quote.model_copy(update={"payment_schedule": schedule}))

    assert result.passed is False
    assert expected_code in {issue.code for issue in result.errors}


def test_review_rejects_non_cent_monetary_values() -> None:
    draft, quote = _threshold_quote()
    mutated = quote.model_copy(update={"selected_amount": Decimal("700.001")})

    result = review_quote(draft, mutated)

    assert result.passed is False
    assert "money_precision" in {issue.code for issue in result.errors}
