from decimal import Decimal

import pytest

from quotation_agents.models import WorkCategory
from quotation_agents.rates import (
    COMMERCIAL_POLICY,
    HOURLY_RATES,
    CommercialPolicy,
    quantize_money,
)


def test_hourly_rates_cover_each_category_in_pen() -> None:
    assert HOURLY_RATES == {
        WorkCategory.PLANNING_AND_COORDINATION: Decimal("10.00"),
        WorkCategory.BACKEND: Decimal("30.00"),
        WorkCategory.FRONTEND: Decimal("20.00"),
        WorkCategory.DEVOPS: Decimal("15.00"),
    }
    assert all(isinstance(rate, Decimal) for rate in HOURLY_RATES.values())


def test_commercial_policy_defaults_are_centralized_and_immutable() -> None:
    policy = COMMERCIAL_POLICY

    assert policy.currency == "PEN"
    assert policy.igv_included is False
    assert policy.available_hours_per_day == Decimal("3")
    assert policy.quote_floor == Decimal("150.00")
    assert policy.quote_ceiling == Decimal("10000.00")
    assert policy.payment_threshold == Decimal("700.00")
    assert policy.advance_rate == Decimal("0.40")
    assert policy.validity_days == 14
    with pytest.raises(ValueError):
        policy.currency = "USD"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("1.005"), Decimal("1.01")),
        (Decimal("-1.005"), Decimal("-1.01")),
    ],
)
def test_money_rounding_is_half_up_to_cents(amount: Decimal, expected: Decimal) -> None:
    assert quantize_money(amount) == expected


def test_money_rounding_requires_decimal() -> None:
    with pytest.raises(TypeError, match="must be a Decimal"):
        quantize_money(1.005)  # type: ignore[arg-type]


def test_commercial_policy_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        CommercialPolicy(unlisted_rule=True)
