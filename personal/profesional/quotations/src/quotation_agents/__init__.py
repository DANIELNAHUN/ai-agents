"""Standalone foundations for software quotation workflows."""

from .config import ConfigurationError, QuotationConfig, load_config
from .inference import (
    INFERENCE_SYSTEM_PROMPT,
    InferenceError,
    create_requirement_inference_agent,
    infer_requirements,
)
from .models import (
    ApprovalState,
    QuotationDraft,
    QuotationTask,
    RequirementInference,
    WorkCategory,
)
from .provider import Invocation, ProviderError, resolve_invocation
from .rates import (
    COMMERCIAL_POLICY,
    HOURLY_RATES,
    CommercialPolicy,
    quantize_money,
)
from .workflow import (
    DraftApprovalRequiredError,
    QuotationWorkflowError,
    approve_draft,
    create_pending_draft,
    edit_draft,
    intake_draft,
    require_approved_draft,
    revise_draft,
)

__all__ = [
    "ApprovalState",
    "COMMERCIAL_POLICY",
    "CommercialPolicy",
    "ConfigurationError",
    "DraftApprovalRequiredError",
    "HOURLY_RATES",
    "INFERENCE_SYSTEM_PROMPT",
    "InferenceError",
    "Invocation",
    "ProviderError",
    "QuotationConfig",
    "QuotationDraft",
    "QuotationTask",
    "QuotationWorkflowError",
    "RequirementInference",
    "WorkCategory",
    "approve_draft",
    "create_pending_draft",
    "create_requirement_inference_agent",
    "edit_draft",
    "infer_requirements",
    "intake_draft",
    "load_config",
    "quantize_money",
    "require_approved_draft",
    "resolve_invocation",
    "revise_draft",
]
