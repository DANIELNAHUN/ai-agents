"""Pure effort, pricing, module, and payment calculations for quotations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import QuotationDraft, QuotationTask, WorkCategory
from .rates import COMMERCIAL_POLICY, HOURLY_RATES, CommercialPolicy, quantize_money
from .workflow import require_approved_draft


class QuotationCalculationError(ValueError):
    """Raised when editable quotation inputs cannot be calculated safely."""


class CategoryEstimate(BaseModel):
    """Hours, rate, and rounded subtotal for one work category."""

    model_config = ConfigDict(extra="forbid")

    category: WorkCategory
    hours: Decimal = Field(ge=0)
    rate: Decimal = Field(gt=0)
    subtotal: Decimal = Field(ge=0)


class EffortEstimate(BaseModel):
    """Deterministic effort summary derived from estimated task hours."""

    model_config = ConfigDict(extra="forbid")

    total_hours: Decimal = Field(gt=0)
    calendar_days: int = Field(gt=0)
    category_hours: dict[WorkCategory, Decimal]
    category_subtotals: dict[WorkCategory, Decimal]
    categories: tuple[CategoryEstimate, ...]
    raw_amount: Decimal = Field(gt=0)


class QuoteInputs(BaseModel):
    """Editable commercial inputs; defaults intentionally add no contingency."""

    model_config = ConfigDict(extra="forbid")

    complexity_factor: Decimal = Field(default=Decimal("1.00"), ge=1)
    dependency_factor: Decimal = Field(default=Decimal("1.00"), ge=1)
    risk_factor: Decimal = Field(default=Decimal("1.00"), ge=1)
    contingency_rate: Decimal = Field(default=Decimal("0.00"), ge=0)
    selected_band: Literal["minimum", "ideal", "maximum"] = "ideal"
    custom_amount: Decimal | None = Field(default=None, gt=0)
    quote_floor: Decimal | None = Field(default=None, ge=0)
    quote_ceiling: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_custom_bounds(self) -> "QuoteInputs":
        if (
            self.quote_floor is not None
            and self.quote_ceiling is not None
            and self.quote_floor > self.quote_ceiling
        ):
            raise ValueError("quote_floor must be less than or equal to quote_ceiling")
        return self


class Payment(BaseModel):
    """One deterministic payment milestone."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    percentage: Decimal | None = Field(default=None, ge=0, le=1)
    module_name: str | None = None


class PaymentSchedule(BaseModel):
    """A payment schedule whose rounded amounts reconcile exactly."""

    model_config = ConfigDict(extra="forbid")

    payments: tuple[Payment, ...] = Field(min_length=1)
    total_amount: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def validate_reconciliation(self) -> "PaymentSchedule":
        if sum((payment.amount for payment in self.payments), Decimal("0")) != self.total_amount:
            raise ValueError("payment amounts must reconcile exactly to total_amount")
        return self

    @property
    def total(self) -> Decimal:
        """Convenient alias for the reconciled schedule total."""

        return self.total_amount


class ModuleSpec(BaseModel):
    """Editable, deterministic partition definition using zero-based task indexes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    task_indices: list[int] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module name must not be blank")
        return value


class QuoteModule(BaseModel):
    """A module containing the original task objects in deterministic order."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    tasks: tuple[QuotationTask, ...] = Field(min_length=1)

    @property
    def total_hours(self) -> Decimal:
        return sum((task.estimated_hours or Decimal("0") for task in self.tasks), Decimal("0"))

    @property
    def raw_amount(self) -> Decimal:
        return sum(
            (
                task.estimated_hours * HOURLY_RATES[task.category]
                for task in self.tasks
                if task.estimated_hours is not None
            ),
            Decimal("0"),
        )


class QuoteResult(BaseModel):
    """Editable, inspectable result of a pure quote calculation."""

    model_config = ConfigDict(extra="forbid")

    effort: EffortEstimate
    raw_amount: Decimal = Field(gt=0)
    minimum_amount: Decimal = Field(gt=0)
    ideal_amount: Decimal = Field(gt=0)
    maximum_amount: Decimal = Field(gt=0)
    selected_amount: Decimal = Field(gt=0)
    selected_band: str
    floor_applied: bool
    ceiling_exceeded: bool
    requires_modularization: bool
    manual_approval_required: bool
    payment_schedule: PaymentSchedule
    source_draft_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    @property
    def quote_amount(self) -> Decimal:
        """Alias for the amount selected for the quote."""

        return self.selected_amount


def _draft_fingerprint(draft: QuotationDraft) -> str:
    """Return a stable identity for the complete serialized draft state."""

    serialized = json.dumps(
        draft.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _task_list(tasks_or_draft: Sequence[QuotationTask] | QuotationDraft) -> list[QuotationTask]:
    if isinstance(tasks_or_draft, QuotationDraft):
        return list(require_approved_draft(tasks_or_draft).tasks)
    if isinstance(tasks_or_draft, (str, bytes)):
        raise QuotationCalculationError("tasks must be a non-empty sequence of QuotationTask")
    tasks = list(tasks_or_draft)
    if not tasks:
        raise QuotationCalculationError("at least one task is required")
    if any(not isinstance(task, QuotationTask) for task in tasks):
        raise QuotationCalculationError("tasks must contain only QuotationTask values")
    return tasks


def estimate_effort(
    tasks_or_draft: Sequence[QuotationTask] | QuotationDraft,
    *,
    policy: CommercialPolicy = COMMERCIAL_POLICY,
) -> EffortEstimate:
    """Calculate category hours, subtotals, and rounded-up calendar days."""

    tasks = _task_list(tasks_or_draft)
    if any(task.estimated_hours is None for task in tasks):
        raise QuotationCalculationError("every task must have estimated_hours before calculation")

    category_hours = {
        category: sum(
            (task.estimated_hours for task in tasks if task.category is category),
            Decimal("0"),
        )
        for category in WorkCategory
    }
    category_subtotals = {
        category: quantize_money(category_hours[category] * HOURLY_RATES[category])
        for category in WorkCategory
    }
    categories = tuple(
        CategoryEstimate(
            category=category,
            hours=category_hours[category],
            rate=HOURLY_RATES[category],
            subtotal=category_subtotals[category],
        )
        for category in WorkCategory
    )
    total_hours = sum(category_hours.values(), Decimal("0"))
    calendar_days = int(
        (total_hours / policy.available_hours_per_day).to_integral_value(rounding=ROUND_CEILING)
    )
    raw_amount = quantize_money(sum(category_subtotals.values(), Decimal("0")))
    return EffortEstimate(
        total_hours=total_hours,
        calendar_days=calendar_days,
        category_hours=category_hours,
        category_subtotals=category_subtotals,
        categories=categories,
        raw_amount=raw_amount,
    )


def _effective_policy(policy: CommercialPolicy, inputs: QuoteInputs) -> CommercialPolicy:
    values = policy.model_dump()
    if inputs.quote_floor is not None:
        values["quote_floor"] = inputs.quote_floor
    if inputs.quote_ceiling is not None:
        values["quote_ceiling"] = inputs.quote_ceiling
    try:
        return CommercialPolicy.model_validate(values)
    except ValueError as exc:
        raise QuotationCalculationError(str(exc)) from exc


def _module_specs(modules: Mapping[str, Sequence[int]] | Sequence[ModuleSpec]) -> list[ModuleSpec]:
    if isinstance(modules, Mapping):
        return [
            ModuleSpec(name=name, task_indices=list(indices))
            for name, indices in modules.items()
        ]
    return [ModuleSpec.model_validate(module) for module in modules]


def split_modules(
    tasks: Sequence[QuotationTask],
    modules: Mapping[str, Sequence[int]] | Sequence[ModuleSpec],
) -> tuple[QuoteModule, ...]:
    """Partition every task exactly once, preserving category and task order."""

    task_list = _task_list(tasks)
    specs = _module_specs(modules)
    if not specs:
        raise QuotationCalculationError("at least one module is required")
    names: set[str] = set()
    assigned: list[int] = []
    result: list[QuoteModule] = []
    for spec in specs:
        if spec.name in names:
            raise QuotationCalculationError(f"duplicate module name: {spec.name!r}")
        names.add(spec.name)
        if any(index < 0 or index >= len(task_list) for index in spec.task_indices):
            raise QuotationCalculationError(f"module {spec.name!r} contains an invalid task index")
        if len(set(spec.task_indices)) != len(spec.task_indices):
            raise QuotationCalculationError(f"module {spec.name!r} assigns a task more than once")
        assigned.extend(spec.task_indices)
        result.append(
            QuoteModule(
                name=spec.name,
                tasks=tuple(task_list[index].model_copy(deep=True) for index in spec.task_indices),
            )
        )
    if len(set(assigned)) != len(assigned):
        raise QuotationCalculationError("a task cannot be assigned to more than one module")
    if set(assigned) != set(range(len(task_list))):
        raise QuotationCalculationError("modules must assign every task exactly once")
    return tuple(result)


partition_tasks = split_modules


def _module_weights(modules: Sequence[QuoteModule]) -> list[Decimal]:
    if not modules:
        return []
    names: set[str] = set()
    weights: list[Decimal] = []
    for module in modules:
        if module.name in names:
            raise QuotationCalculationError(f"duplicate module name: {module.name!r}")
        names.add(module.name)
        if module.raw_amount <= 0:
            raise QuotationCalculationError("module amounts must be positive")
        weights.append(module.raw_amount)
    return weights


def _allocate_amount(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    weight_total = sum(weights, Decimal("0"))
    raw = [total * weight / weight_total for weight in weights]
    allocations = [quantize_money(amount) for amount in raw]
    residual = total - sum(allocations, Decimal("0"))
    cent = Decimal("0.01")
    if residual:
        direction = 1 if residual > 0 else -1
        ordered = sorted(
            range(len(weights)),
            key=lambda index: (
                -(raw[index] - allocations[index])
                if direction > 0
                else raw[index] - allocations[index],
                index,
            ),
        )
        while residual:
            for index in ordered:
                if direction < 0 and allocations[index] < cent:
                    continue
                allocations[index] += cent * direction
                residual -= cent * direction
                if not residual:
                    break
            else:
                raise QuotationCalculationError("could not reconcile module payment rounding")
    return allocations


def create_payment_schedule(
    amount: Decimal,
    *,
    modules: Sequence[QuoteModule] | None = None,
    policy: CommercialPolicy = COMMERCIAL_POLICY,
) -> PaymentSchedule:
    """Create threshold-based payments and reconcile every cent deterministically."""

    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    amount = quantize_money(amount)
    if amount <= 0:
        raise QuotationCalculationError("payment amount must be positive")
    if amount < policy.payment_threshold:
        return PaymentSchedule(
            payments=(Payment(label="Full project", amount=amount, percentage=Decimal("1.00")),),
            total_amount=amount,
        )

    advance = quantize_money(amount * policy.advance_rate)
    remaining = amount - advance
    payments = [Payment(label="Advance", amount=advance, percentage=policy.advance_rate)]
    validated_modules = tuple(modules or ())
    weights = _module_weights(validated_modules)
    if weights:
        allocations = _allocate_amount(remaining, weights)
        payments.extend(
            Payment(
                label=module.name,
                module_name=module.name,
                amount=allocation,
                percentage=quantize_money(allocation / amount),
            )
            for module, allocation in zip(validated_modules, allocations)
        )
    else:
        payments.append(Payment(label="Project completion", amount=remaining))
    return PaymentSchedule(payments=tuple(payments), total_amount=amount)


def calculate_quote(
    draft: QuotationDraft,
    *,
    inputs: QuoteInputs | None = None,
    policy: CommercialPolicy = COMMERCIAL_POLICY,
    modules: Sequence[QuoteModule] | None = None,
) -> QuoteResult:
    """Calculate a quote without mutating the approved draft or its tasks."""

    approved_draft = require_approved_draft(draft)
    quote_inputs = inputs or QuoteInputs()
    effective_policy = _effective_policy(policy, quote_inputs)
    effort = estimate_effort(approved_draft.tasks, policy=effective_policy)
    raw_amount = effort.raw_amount
    minimum_amount = quantize_money(raw_amount)
    ideal_amount = quantize_money(
        raw_amount * quote_inputs.complexity_factor * quote_inputs.dependency_factor
    )
    maximum_amount = quantize_money(
        ideal_amount * quote_inputs.risk_factor * (Decimal("1") + quote_inputs.contingency_rate)
    )
    band_amounts = {
        "minimum": minimum_amount,
        "ideal": ideal_amount,
        "maximum": maximum_amount,
    }
    selected_before_floor = quote_inputs.custom_amount or band_amounts[quote_inputs.selected_band]
    floor_applied = selected_before_floor < effective_policy.quote_floor
    selected_amount = quantize_money(max(selected_before_floor, effective_policy.quote_floor))
    ceiling_exceeded = selected_amount > effective_policy.quote_ceiling
    schedule = create_payment_schedule(selected_amount, modules=modules, policy=effective_policy)
    return QuoteResult(
        effort=effort,
        raw_amount=raw_amount,
        minimum_amount=minimum_amount,
        ideal_amount=ideal_amount,
        maximum_amount=maximum_amount,
        selected_amount=selected_amount,
        selected_band=(
            "custom" if quote_inputs.custom_amount is not None else quote_inputs.selected_band
        ),
        floor_applied=floor_applied,
        ceiling_exceeded=ceiling_exceeded,
        requires_modularization=ceiling_exceeded,
        manual_approval_required=ceiling_exceeded,
        payment_schedule=schedule,
        source_draft_fingerprint=_draft_fingerprint(approved_draft),
    )


calculate_effort = estimate_effort
build_payment_schedule = create_payment_schedule
