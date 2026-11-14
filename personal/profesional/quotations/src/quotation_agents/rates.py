"""Central commercial rates and policy defaults for quotation workflows."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import WorkCategory

MONEY_QUANTUM = Decimal("0.01")
MONEY_ROUNDING = ROUND_HALF_UP

HOURLY_RATES = MappingProxyType(
    {
        WorkCategory.PLANNING_AND_COORDINATION: Decimal("10.00"),
        WorkCategory.BACKEND: Decimal("30.00"),
        WorkCategory.FRONTEND: Decimal("20.00"),
        WorkCategory.DEVOPS: Decimal("15.00"),
    }
)


class CommercialPolicy(BaseModel):
    """Commercial thresholds and terms that later quote calculations will use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["PEN"] = "PEN"
    igv_included: Literal[False] = False
    available_hours_per_day: Decimal = Field(default=Decimal("3"), gt=0)
    quote_floor: Decimal = Field(default=Decimal("150.00"), ge=0)
    quote_ceiling: Decimal = Field(default=Decimal("10000.00"), gt=0)
    payment_threshold: Decimal = Field(default=Decimal("700.00"), ge=0)
    advance_rate: Decimal = Field(default=Decimal("0.40"), gt=0, le=1)
    validity_days: int = Field(default=14, gt=0)

    @model_validator(mode="after")
    def validate_quote_bounds(self) -> "CommercialPolicy":
        if self.quote_floor > self.quote_ceiling:
            raise ValueError("quote_floor must be less than or equal to quote_ceiling")
        return self


COMMERCIAL_POLICY = CommercialPolicy()


def quantize_money(amount: Decimal) -> Decimal:
    """Round a monetary amount to cents using the documented half-up rule."""

    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    return amount.quantize(MONEY_QUANTUM, rounding=MONEY_ROUNDING)
