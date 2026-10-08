"""Provider-neutral invocation boundary for quotation model calls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class Invocation(Protocol):
    """Callable accepting a model request and returning its response."""

    def __call__(self, request: dict[str, Any]) -> Any: ...


class ProviderError(RuntimeError):
    """Raised when an injected model boundary cannot be resolved."""


def resolve_invocation(
    *,
    invoke: Invocation | None = None,
    model: Any | None = None,
) -> Invocation:
    """Return an injected callable or a model's ``invoke`` method.

    No provider is constructed implicitly, so resolving this boundary never
    requires credentials, network access, or a live model call.
    """

    if invoke is not None and model is not None:
        raise ProviderError("Pass either invoke or model, not both")
    if invoke is not None:
        if not callable(invoke):
            raise ProviderError("invoke must be callable")
        return invoke
    if model is not None:
        model_invoke: Callable[[dict[str, Any]], Any] | None = getattr(model, "invoke", None)
        if callable(model_invoke):
            return model_invoke
        raise ProviderError("model must provide a callable invoke method")
    raise ProviderError("Pass an injected invoke callable or model")
