"""Deterministic review checks for approved quotation results."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import QuotationDraft
from .pricing import (
    QuotationCalculationError,
    QuoteResult,
    _draft_fingerprint,
    estimate_effort,
)
from .rates import COMMERCIAL_POLICY, CommercialPolicy, quantize_money
from .workflow import require_approved_draft


class QuotationReviewError(ValueError):
    """Raised when a quotation cannot enter the review boundary."""


class ReviewIssue(BaseModel):
    """One deterministic review finding."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["error", "warning"]


class QuotationReview(BaseModel):
    """Review outcome and findings for one approved draft and quote pair."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    ready_for_document: bool
    requires_manual_approval: bool
    issues: tuple[ReviewIssue, ...] = ()

    @property
    def errors(self) -> tuple[ReviewIssue, ...]:
        """Return findings that make the deterministic review fail."""

        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ReviewIssue, ...]:
        """Return findings that require human attention but do not fail arithmetic."""

        return tuple(issue for issue in self.issues if issue.severity == "warning")


def _add_issue(
    issues: list[ReviewIssue], code: str, message: str, severity: Literal["error", "warning"]
) -> None:
    issues.append(ReviewIssue(code=code, message=message, severity=severity))


def _check_text_lists(
    draft: QuotationDraft,
    issues: list[ReviewIssue],
) -> None:
    for field_name in ("inferred_scope", "assumptions", "questions", "risks"):
        values = getattr(draft, field_name, None)
        if not isinstance(values, list):
            _add_issue(issues, "invalid_scope", f"{field_name} must be a list of text", "error")
            continue
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                _add_issue(
                    issues,
                    "blank_scope_note",
                    f"{field_name}[{index}] must not be blank",
                    "error",
                )


def _check_scope(draft: QuotationDraft, issues: list[ReviewIssue]) -> None:
    if not isinstance(draft.client_company, str) or not draft.client_company.strip():
        _add_issue(issues, "invalid_scope", "client/company must not be blank", "error")
    if not isinstance(draft.original_request, str) or not draft.original_request.strip():
        _add_issue(issues, "invalid_scope", "original request must not be blank", "error")
    _check_text_lists(draft, issues)
    if not draft.inferred_scope:
        _add_issue(
            issues,
            "missing_scope",
            "at least one interpreted scope item is required",
            "error",
        )
    if not draft.tasks:
        _add_issue(issues, "missing_tasks", "at least one quotation task is required", "error")
    for index, task in enumerate(draft.tasks):
        if not isinstance(task.description, str) or not task.description.strip():
            _add_issue(issues, "blank_task", f"tasks[{index}] must have a description", "error")
        if not isinstance(task.estimated_hours, Decimal) or task.estimated_hours <= 0:
            _add_issue(
                issues,
                "invalid_hours",
                f"tasks[{index}] must have positive estimated hours",
                "error",
            )


def _check_effort_and_amounts(
    draft: QuotationDraft,
    quote: QuoteResult,
    policy: CommercialPolicy,
    issues: list[ReviewIssue],
) -> None:
    try:
        expected_effort = estimate_effort(draft, policy=policy)
    except (ArithmeticError, KeyError, QuotationCalculationError, TypeError, ValueError) as exc:
        _add_issue(issues, "scope_arithmetic_unavailable", str(exc), "error")
        expected_effort = None

    if expected_effort is not None and quote.effort != expected_effort:
        _add_issue(
            issues,
            "scope_arithmetic_mismatch",
            "quote effort does not match the approved task scope",
            "error",
        )
    if quote.raw_amount != quote.effort.raw_amount:
        _add_issue(issues, "raw_amount_mismatch", "raw amount does not match effort", "error")
    if quote.minimum_amount != quote.raw_amount:
        _add_issue(
            issues,
            "minimum_amount_mismatch",
            "minimum amount must equal raw amount",
            "error",
        )
    if quote.ideal_amount < quote.minimum_amount:
        _add_issue(issues, "ideal_below_minimum", "ideal amount must not be below minimum", "error")
    if quote.maximum_amount < quote.ideal_amount:
        _add_issue(issues, "maximum_below_ideal", "maximum amount must not be below ideal", "error")
    if quote.selected_amount <= 0:
        _add_issue(issues, "invalid_selected_amount", "selected amount must be positive", "error")


def _is_cent_value(value: object) -> bool:
    if not isinstance(value, Decimal):
        return False
    try:
        return value == quantize_money(value)
    except (ArithmeticError, TypeError, ValueError):
        return False


def _check_monetary_precision(quote: QuoteResult, issues: list[ReviewIssue]) -> None:
    invalid_paths: list[str] = []
    quote_amounts = (
        "raw_amount",
        "minimum_amount",
        "ideal_amount",
        "maximum_amount",
        "selected_amount",
    )
    for field_name in quote_amounts:
        if not _is_cent_value(getattr(quote, field_name, None)):
            invalid_paths.append(field_name)

    effort = quote.effort
    if not _is_cent_value(getattr(effort, "raw_amount", None)):
        invalid_paths.append("effort.raw_amount")
    for category, subtotal in getattr(effort, "category_subtotals", {}).items():
        if not _is_cent_value(subtotal):
            invalid_paths.append(f"effort.category_subtotals[{category}]")
    for index, category in enumerate(getattr(effort, "categories", ())):
        if not _is_cent_value(getattr(category, "subtotal", None)):
            invalid_paths.append(f"effort.categories[{index}].subtotal")

    schedule = quote.payment_schedule
    for index, payment in enumerate(schedule.payments):
        if not _is_cent_value(getattr(payment, "amount", None)):
            invalid_paths.append(f"payment_schedule.payments[{index}].amount")
    if not _is_cent_value(getattr(schedule, "total_amount", None)):
        invalid_paths.append("payment_schedule.total_amount")

    if invalid_paths:
        _add_issue(
            issues,
            "money_precision",
            "monetary values must use cent precision: " + ", ".join(invalid_paths),
            "error",
        )


def _check_commercial_consistency(
    quote: QuoteResult,
    policy: CommercialPolicy,
    issues: list[ReviewIssue],
) -> bool:
    selected = quote.selected_amount
    if not isinstance(selected, Decimal) or selected <= 0:
        return False

    floor = quantize_money(policy.quote_floor)
    ceiling = quantize_money(policy.quote_ceiling)
    if selected < floor:
        _add_issue(issues, "floor_not_applied", "selected amount is below the quote floor", "error")

    if quote.selected_band in {"minimum", "ideal", "maximum"}:
        band_amount = getattr(quote, f"{quote.selected_band}_amount")
        expected_selected = max(band_amount, floor)
        if selected != expected_selected:
            _add_issue(
                issues,
                "selected_band_mismatch",
                "selected amount does not match its selected band and floor",
                "error",
            )
        if quote.floor_applied is not (band_amount < floor):
            _add_issue(issues, "floor_flag_mismatch", "floor_applied is inconsistent", "error")
    elif quote.selected_band != "custom":
        _add_issue(issues, "unknown_selected_band", "selected band is not recognized", "error")

    ceiling_exceeded = selected > ceiling
    if quote.ceiling_exceeded is not ceiling_exceeded:
        _add_issue(issues, "ceiling_flag_mismatch", "ceiling_exceeded is inconsistent", "error")
    if quote.requires_modularization is not ceiling_exceeded:
        _add_issue(
            issues,
            "modularization_flag_mismatch",
            "requires_modularization is inconsistent with the ceiling",
            "error",
        )
    if quote.manual_approval_required is not ceiling_exceeded:
        _add_issue(
            issues,
            "manual_approval_flag_mismatch",
            "manual_approval_required is inconsistent with the ceiling",
            "error",
        )
    if ceiling_exceeded:
        _add_issue(
            issues,
            "manual_approval_required",
            (
                "selected amount exceeds the ceiling; retain the full amount and obtain "
                "manual approval"
            ),
            "warning",
        )
    return ceiling_exceeded


def _check_payment_schedule(
    quote: QuoteResult,
    policy: CommercialPolicy,
    issues: list[ReviewIssue],
) -> None:
    schedule = quote.payment_schedule
    amounts = [payment.amount for payment in schedule.payments]
    if any(not isinstance(amount, Decimal) or amount < 0 for amount in amounts):
        _add_issue(
            issues,
            "invalid_payment_amount",
            "payment amounts must not be negative",
            "error",
        )
        return
    if (
        schedule.total_amount != quote.selected_amount
        or sum(amounts, Decimal("0")) != quote.selected_amount
    ):
        _add_issue(
            issues,
            "payment_total_mismatch",
            "payment schedule must reconcile to selected amount",
            "error",
        )
        return

    if quote.selected_amount < policy.payment_threshold:
        if len(schedule.payments) != 1:
            _add_issue(
                issues,
                "payment_rule_mismatch",
                "below-threshold quotes require one payment",
                "error",
            )
            return
        payment = schedule.payments[0]
        if payment.label != "Full project" or payment.amount != quote.selected_amount:
            _add_issue(
                issues,
                "payment_rule_mismatch",
                "below-threshold payment is inconsistent",
                "error",
            )
        return

    if len(schedule.payments) < 2:
        _add_issue(
            issues,
            "payment_rule_mismatch",
            "threshold quotes require an advance and balance",
            "error",
        )
        return
    advance = schedule.payments[0]
    expected_advance = quantize_money(quote.selected_amount * policy.advance_rate)
    if advance.label != "Advance" or advance.amount != expected_advance:
        _add_issue(
            issues,
            "advance_mismatch",
            "advance payment is inconsistent with policy",
            "error",
        )

    if advance.module_name is not None:
        _add_issue(
            issues,
            "payment_module_identity",
            "advance payment must not identify a module",
            "error",
        )

    for index, payment in enumerate(schedule.payments):
        percentage = payment.percentage
        if percentage is not None and (
            not isinstance(percentage, Decimal) or percentage < 0 or percentage > 1
        ):
            _add_issue(
                issues,
                "payment_percentage_invalid",
                f"payment {index} percentage must be between 0 and 1",
                "error",
            )

    milestones = schedule.payments[1:]
    completion_milestones = [
        payment for payment in milestones if payment.label == "Project completion"
    ]
    if completion_milestones:
        if len(milestones) != 1 or completion_milestones[0].module_name is not None:
            _add_issue(
                issues,
                "payment_milestone_shape",
                "threshold schedules must use either one project completion milestone "
                "or module milestones",
                "error",
            )
        return

    module_names: set[str] = set()
    for index, payment in enumerate(milestones, start=1):
        module_name = payment.module_name
        if not isinstance(module_name, str) or not module_name.strip():
            _add_issue(
                issues,
                "payment_module_identity",
                f"payment {index} must identify a nonblank module",
                "error",
            )
            continue
        if module_name in module_names:
            _add_issue(
                issues,
                "payment_module_duplicate",
                f"payment {index} repeats module {module_name!r}",
                "error",
            )
        module_names.add(module_name)
        if payment.label != module_name:
            _add_issue(
                issues,
                "payment_label_mismatch",
                f"payment {index} label must match module_name",
                "error",
            )


def review_quote(
    draft: QuotationDraft,
    quote: QuoteResult,
    *,
    policy: CommercialPolicy = COMMERCIAL_POLICY,
) -> QuotationReview:
    """Review one approved draft and deterministic quote without provider calls."""

    approved_draft = require_approved_draft(draft)
    if not isinstance(quote, QuoteResult):
        raise QuotationReviewError("quote must be a deterministic QuoteResult")
    if quote.source_draft_fingerprint != _draft_fingerprint(approved_draft):
        raise QuotationReviewError("quote does not belong to the approved draft")

    issues: list[ReviewIssue] = []
    _check_scope(approved_draft, issues)
    _check_monetary_precision(quote, issues)
    _check_effort_and_amounts(approved_draft, quote, policy, issues)
    ceiling_exceeded = _check_commercial_consistency(quote, policy, issues)
    _check_payment_schedule(quote, policy, issues)

    if approved_draft.questions:
        _add_issue(
            issues,
            "open_questions",
            "questions remain pending confirmation",
            "warning",
        )
    has_errors = any(issue.severity == "error" for issue in issues)
    return QuotationReview(
        passed=not has_errors,
        ready_for_document=not has_errors and not approved_draft.questions and not ceiling_exceeded,
        requires_manual_approval=ceiling_exceeded,
        issues=tuple(issues),
    )


__all__ = ["QuotationReview", "QuotationReviewError", "ReviewIssue", "review_quote"]
