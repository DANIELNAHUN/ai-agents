from decimal import Decimal

from quotation_agents import (
    ApprovalState,
    QuotationDraft,
    QuotationTask,
    QuoteInputs,
    WorkCategory,
    approve_draft,
    calculate_quote,
    decompose_category,
    generate_proposal_documents,
    review_quote,
    revise_draft,
    split_modules,
)


def task(category: WorkCategory, description: str, hours: str) -> QuotationTask:
    return QuotationTask(
        category=category,
        description=description,
        estimated_hours=Decimal(hours),
    )


def approved(tasks: list[QuotationTask], *, scope: str = "Approved scope") -> QuotationDraft:
    return QuotationDraft(
        client_company="Scenario Client",
        original_request="Deliver the approved software change",
        inferred_scope=[scope],
        assumptions=["Existing hosting remains available"],
        tasks=tasks,
        approval_state=ApprovalState.APPROVED,
    )


def test_representative_commercial_scenarios() -> None:
    wordpress = approved([task(WorkCategory.FRONTEND, "Adjust WordPress header", "2")])
    wordpress_quote = calculate_quote(wordpress)
    assert wordpress_quote.selected_amount == Decimal("150.00")
    assert [payment.label for payment in wordpress_quote.payment_schedule.payments] == [
        "Full project"
    ]

    small = approved([task(WorkCategory.BACKEND, "Add a small endpoint", "10")])
    small_quote = calculate_quote(small)
    assert small_quote.selected_amount == Decimal("300.00")
    assert [payment.label for payment in small_quote.payment_schedule.payments] == ["Full project"]

    medium_tasks = [
        task(WorkCategory.BACKEND, "Build module API", "20"),
        task(WorkCategory.FRONTEND, "Build module screen", "10"),
    ]
    medium = approved(medium_tasks)
    modules = split_modules(medium_tasks, {"Core API": [0], "Module UI": [1]})
    medium_quote = calculate_quote(medium, modules=modules)
    assert medium_quote.selected_amount == Decimal("800.00")
    assert medium_quote.payment_schedule.payments[0].amount == Decimal("320.00")
    assert [payment.label for payment in medium_quote.payment_schedule.payments] == [
        "Advance",
        "Core API",
        "Module UI",
    ]

    threshold = approved([task(WorkCategory.BACKEND, "Threshold endpoint", "1")])
    threshold_quote = calculate_quote(
        threshold,
        inputs=QuoteInputs(custom_amount=Decimal("700.00")),
    )
    assert [payment.label for payment in threshold_quote.payment_schedule.payments] == [
        "Advance",
        "Project completion",
    ]
    assert threshold_quote.payment_schedule.payments[0].amount == Decimal("280.00")

    large = approved(
        [
            task(WorkCategory.BACKEND, "Large platform API", "20"),
            task(WorkCategory.FRONTEND, "Large platform UI", "10"),
        ],
        scope="Modular large platform delivery",
    )
    large_modules = split_modules(
        large.tasks,
        {"Platform API": [0], "Platform UI": [1]},
    )
    large_quote = calculate_quote(
        large,
        inputs=QuoteInputs(custom_amount=Decimal("10000.01")),
        modules=large_modules,
    )
    assert large_quote.selected_amount == Decimal("10000.01")
    assert large_quote.requires_modularization is True
    assert large_quote.manual_approval_required is True

    for draft, quote in (
        (wordpress, wordpress_quote),
        (small, small_quote),
        (medium, medium_quote),
        (threshold, threshold_quote),
        (large, large_quote),
    ):
        assert review_quote(draft, quote).passed is True


def test_end_to_end_decomposition_pricing_review_and_docx_generation(tmp_path) -> None:
    draft = approved([], scope="WordPress booking adjustment")

    decomposition = decompose_category(
        draft,
        WorkCategory.FRONTEND,
        invoke=lambda _: {
            "structured_response": {
                "tasks": [
                    {
                        "category": WorkCategory.FRONTEND,
                        "description": "Adjust WordPress booking form",
                        "estimated_hours": "2",
                    }
                ]
            }
        },
    )
    revised = revise_draft(draft, tasks=decomposition.tasks)
    final_draft = approve_draft(revised)
    quote = calculate_quote(final_draft)
    review = review_quote(final_draft, quote)
    documents = generate_proposal_documents(final_draft, quote, tmp_path, filename="smoke")

    assert review.passed is True
    assert review.ready_for_document is True
    assert documents.docx_validation.valid is True
    assert documents.pdf_path is None
