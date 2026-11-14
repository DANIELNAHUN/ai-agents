from decimal import Decimal

import pytest
from pydantic import ValidationError

from quotation_agents import (
    ApprovalState,
    CommercialPolicy,
    DraftApprovalRequiredError,
    ModuleSpec,
    QuotationCalculationError,
    QuotationDraft,
    QuotationTask,
    QuoteInputs,
    WorkCategory,
    calculate_quote,
    create_payment_schedule,
    estimate_effort,
    split_modules,
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
        original_request="Build a website",
        tasks=tasks,
        approval_state=ApprovalState.APPROVED,
    )


def test_fractional_hours_round_calendar_days_and_category_arithmetic() -> None:
    tasks = [
        task(WorkCategory.PLANNING_AND_COORDINATION, "Plan", "0.75"),
        task(WorkCategory.BACKEND, "API", "1.50"),
        task(WorkCategory.FRONTEND, "Page", "1.25"),
        task(WorkCategory.DEVOPS, "Deploy", "1.00"),
    ]

    result = estimate_effort(tasks)

    assert result.total_hours == Decimal("4.50")
    assert result.calendar_days == 2
    assert result.category_hours[WorkCategory.BACKEND] == Decimal("1.50")
    assert result.category_subtotals[WorkCategory.PLANNING_AND_COORDINATION] == Decimal("7.50")
    assert result.category_subtotals[WorkCategory.BACKEND] == Decimal("45.00")
    assert result.category_subtotals[WorkCategory.FRONTEND] == Decimal("25.00")
    assert result.category_subtotals[WorkCategory.DEVOPS] == Decimal("15.00")
    assert result.raw_amount == Decimal("92.50")


def test_wordpress_small_quote_applies_floor_without_losing_raw_amount() -> None:
    result = calculate_quote(
        approved([task(WorkCategory.FRONTEND, "Small WordPress adjustment", "2")])
    )

    assert result.raw_amount == Decimal("40.00")
    assert result.minimum_amount == Decimal("40.00")
    assert result.ideal_amount == Decimal("40.00")
    assert result.selected_amount == Decimal("150.00")
    assert result.floor_applied is True
    assert len(result.payment_schedule.payments) == 1
    assert result.payment_schedule.payments[0].amount == Decimal("150.00")


def test_explicit_inputs_make_ideal_and_maximum_formulas_editable() -> None:
    result = calculate_quote(
        approved([task(WorkCategory.BACKEND, "Build API", "10")]),
        inputs=QuoteInputs(
            complexity_factor=Decimal("1.10"),
            dependency_factor=Decimal("1.20"),
            risk_factor=Decimal("1.25"),
            contingency_rate=Decimal("0.10"),
        ),
    )

    assert result.raw_amount == Decimal("300.00")
    assert result.minimum_amount == Decimal("300.00")
    assert result.ideal_amount == Decimal("396.00")
    assert result.maximum_amount == Decimal("544.50")


def test_medium_quote_is_split_into_modules_and_reconciles_exactly() -> None:
    tasks = [
        task(WorkCategory.BACKEND, "API", "20"),
        task(WorkCategory.FRONTEND, "Screen", "10"),
    ]
    modules = split_modules(tasks, {"Core": [0], "UI": [1]})
    result = calculate_quote(approved(tasks), modules=modules)

    assert result.selected_amount == Decimal("800.00")
    assert [payment.label for payment in result.payment_schedule.payments] == [
        "Advance",
        "Core",
        "UI",
    ]
    assert sum(
        (payment.amount for payment in result.payment_schedule.payments), Decimal("0")
    ) == result.selected_amount
    assert result.payment_schedule.payments[0].amount == Decimal("320.00")


@pytest.mark.parametrize(
    ("amount", "labels"),
    [
        (Decimal("699.99"), ["Full project"]),
        (Decimal("700.00"), ["Advance", "Project completion"]),
    ],
)
def test_payment_threshold_is_inclusive_and_reconciled(
    amount: Decimal, labels: list[str]
) -> None:
    schedule = create_payment_schedule(amount)

    assert [payment.label for payment in schedule.payments] == labels
    assert schedule.total_amount == amount
    assert sum((payment.amount for payment in schedule.payments), Decimal("0")) == amount
    if amount == Decimal("700.00"):
        assert schedule.payments[0].amount == Decimal("280.00")


def test_exact_ceiling_is_valid_and_above_ceiling_is_not_clipped() -> None:
    draft = approved([task(WorkCategory.BACKEND, "Large project", "1")])
    exact = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("10000.00")))
    above = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("10000.01")))

    assert exact.selected_amount == Decimal("10000.00")
    assert exact.ceiling_exceeded is False
    assert above.selected_amount == Decimal("10000.01")
    assert above.ceiling_exceeded is True
    assert above.requires_modularization is True
    assert above.manual_approval_required is True


def test_custom_floor_and_ceiling_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="quote_floor must be less than or equal"):
        QuoteInputs(quote_floor=Decimal("200"), quote_ceiling=Decimal("100"))
    with pytest.raises(ValueError, match="quote_floor must be less than or equal"):
        CommercialPolicy(quote_floor=Decimal("200"), quote_ceiling=Decimal("100"))


@pytest.mark.parametrize(
    "modules",
    [
        {"Core": [0], "Duplicate": [0]},
        {"Core": [0]},
        {"Core": []},
    ],
)
def test_invalid_module_partitions_are_rejected(modules: dict[str, list[int]]) -> None:
    tasks = [task(WorkCategory.BACKEND, "API", "1"), task(WorkCategory.FRONTEND, "Page", "1")]

    with pytest.raises((QuotationCalculationError, ValidationError)):
        split_modules(tasks, modules)


def test_module_specs_preserve_category_and_reject_pending_calculation() -> None:
    tasks = [
        task(WorkCategory.BACKEND, "API", "1"),
        task(WorkCategory.FRONTEND, "Page", "1"),
    ]
    modules = split_modules(
        tasks,
        [
            ModuleSpec(name="Backend", task_indices=[0]),
            ModuleSpec(name="Frontend", task_indices=[1]),
        ],
    )
    assert modules[0].tasks[0].category is WorkCategory.BACKEND

    pending = approved(tasks).model_copy(update={"approval_state": ApprovalState.PENDING})
    with pytest.raises(DraftApprovalRequiredError):
        calculate_quote(pending)


def test_quote_calculation_does_not_mutate_draft_or_tasks() -> None:
    tasks = [task(WorkCategory.BACKEND, "API", "2")]
    draft = approved(tasks)

    calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("200")))

    assert draft.approval_state is ApprovalState.APPROVED
    assert draft.tasks[0].estimated_hours == Decimal("2")


def test_quote_records_a_deterministic_source_draft_fingerprint() -> None:
    draft = approved([task(WorkCategory.BACKEND, "API", "2")])

    first = calculate_quote(draft)
    second = calculate_quote(draft)
    changed = calculate_quote(draft.model_copy(update={"client_company": "Other Ltd"}))

    assert first.source_draft_fingerprint == second.source_draft_fingerprint
    assert first.source_draft_fingerprint != changed.source_draft_fingerprint
