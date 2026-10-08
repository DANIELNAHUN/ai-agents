"""Standalone foundations for software quotation workflows."""

from .config import ConfigurationError, QuotationConfig, load_config
from .models import ApprovalState, QuotationDraft, QuotationTask, WorkCategory
from .provider import Invocation, ProviderError, resolve_invocation
from .rates import (
    COMMERCIAL_POLICY,
    HOURLY_RATES,
    CommercialPolicy,
    quantize_money,
)

__all__ = [
    "ApprovalState",
    "COMMERCIAL_POLICY",
    "CommercialPolicy",
    "ConfigurationError",
    "HOURLY_RATES",
    "Invocation",
    "ProviderError",
    "QuotationConfig",
    "QuotationDraft",
    "QuotationTask",
    "WorkCategory",
    "load_config",
    "quantize_money",
    "resolve_invocation",
]
