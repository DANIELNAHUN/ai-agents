from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from quotation_agents import (
    ApprovalState,
    DraftApprovalRequiredError,
    ProposalDocumentError,
    QuotationDraft,
    QuotationTask,
    QuoteInputs,
    WorkCategory,
    calculate_quote,
    generate_proposal_documents,
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
        original_request="Build a booking website",
        inferred_scope=["Booking flow"],
        assumptions=["Client provides hosting credentials"],
        risks=["Third-party API limits may change"],
        questions=["Which payment provider should be used?"],
        tasks=tasks,
        approval_state=ApprovalState.APPROVED,
    )


def docx_text(path) -> str:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "\n".join(text for text in root.itertext() if text)


def fake_pdf_converter(docx_path, pdf_path) -> None:
    assert docx_path.exists()
    pdf_path.write_bytes(b"%PDF-1.7\n1 0 obj\nendobj\n%%EOF\n")


def test_proposal_requires_explicitly_approved_draft(tmp_path) -> None:
    tasks = [task(WorkCategory.FRONTEND, "Adjust WordPress header", "2")]
    pending = approved(tasks).model_copy(update={"approval_state": ApprovalState.PENDING})
    quote = calculate_quote(approved(tasks))

    with pytest.raises(DraftApprovalRequiredError):
        generate_proposal_documents(pending, quote, tmp_path)


def test_wordpress_adjustment_below_floor_is_rendered_in_word_and_pdf(tmp_path) -> None:
    draft = approved([task(WorkCategory.FRONTEND, "Small WordPress adjustment", "2")])
    result = generate_proposal_documents(
        draft,
        calculate_quote(draft),
        tmp_path,
        pdf_converter=fake_pdf_converter,
    )
    content = docx_text(result.docx_path)

    assert "Example Ltd" in content
    assert "Build a booking website" in content
    assert "Small WordPress adjustment (2 hours)" in content
    assert "Frontend" in content
    assert "S/ 20.00" in content
    assert "S/ 150.00" in content
    assert "Full project" in content
    assert result.docx_validation.valid is True
    assert result.pdf_validation is not None and result.pdf_validation.valid is True


def test_medium_multicategory_modules_render_category_rates_and_payments(tmp_path) -> None:
    tasks = [
        task(WorkCategory.BACKEND, "Build booking API", "20"),
        task(WorkCategory.FRONTEND, "Build booking screen", "10"),
    ]
    draft = approved(tasks)
    modules = split_modules(tasks, {"Core API": [0], "Booking UI": [1]})
    result = generate_proposal_documents(
        draft,
        calculate_quote(draft, modules=modules),
        tmp_path,
    )
    content = docx_text(result.docx_path)

    assert "Backend" in content and "Frontend" in content
    assert "S/ 30.00" in content and "S/ 20.00" in content
    assert "Core API" in content and "Booking UI" in content
    assert "Advance" in content and "S/ 320.00" in content
    assert "Calendar days (3 hours/day): 10" in content


def test_quote_below_700_uses_full_project_payment(tmp_path) -> None:
    draft = approved([task(WorkCategory.BACKEND, "Small endpoint", "1")])
    result = generate_proposal_documents(
        draft,
        calculate_quote(draft),
        tmp_path,
    )
    content = docx_text(result.docx_path)

    assert "Full project" in content
    assert "Advance" not in content


def test_quote_at_700_uses_advance_and_completion_payments(tmp_path) -> None:
    draft = approved([task(WorkCategory.BACKEND, "Small endpoint", "1")])
    quote = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("700.00")))
    result = generate_proposal_documents(draft, quote, tmp_path)
    content = docx_text(result.docx_path)

    assert "Advance" in content
    assert "Project completion" in content
    assert "S/ 280.00" in content


def test_amount_over_10000_is_retained_and_disclosed(tmp_path) -> None:
    draft = approved([task(WorkCategory.BACKEND, "Large platform", "1")])
    quote = calculate_quote(draft, inputs=QuoteInputs(custom_amount=Decimal("10000.01")))
    result = generate_proposal_documents(draft, quote, tmp_path)
    content = docx_text(result.docx_path)

    assert "S/ 10000.01" in content
    assert "exceeds S/ 10,000" in content
    assert "overage is retained" in content
    assert "modularization and manual approval" in content


def test_existing_output_is_not_overwritten_without_explicit_policy(tmp_path) -> None:
    draft = approved([task(WorkCategory.FRONTEND, "Small page", "2")])
    quote = calculate_quote(draft)
    generate_proposal_documents(draft, quote, tmp_path, filename="protected")

    with pytest.raises(ProposalDocumentError, match="overwrite"):
        generate_proposal_documents(draft, quote, tmp_path, filename="protected")


def test_drive_relative_filename_is_rejected(tmp_path) -> None:
    draft = approved([task(WorkCategory.FRONTEND, "Small page", "2")])

    with pytest.raises(ProposalDocumentError, match="simple output name"):
        generate_proposal_documents(draft, calculate_quote(draft), tmp_path, filename="C:escape")


def test_proposal_rejects_a_quote_calculated_from_another_approved_draft(tmp_path) -> None:
    source = approved([task(WorkCategory.BACKEND, "Build API", "2")])
    supplied = approved([task(WorkCategory.BACKEND, "Build API", "3")])

    with pytest.raises(ProposalDocumentError, match="does not belong"):
        generate_proposal_documents(supplied, calculate_quote(source), tmp_path)


def test_proposal_rejects_a_quote_without_a_source_association(tmp_path) -> None:
    draft = approved([task(WorkCategory.BACKEND, "Build API", "2")])
    quote = calculate_quote(draft).model_copy(update={"source_draft_fingerprint": None})

    with pytest.raises(ProposalDocumentError, match="does not belong"):
        generate_proposal_documents(draft, quote, tmp_path)
