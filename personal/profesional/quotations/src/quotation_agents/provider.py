"""Provider-neutral invocation boundary for quotation model calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from .config import QuotationConfig, load_config


class Invocation(Protocol):
    """Callable accepting a model request and returning its response."""

    def __call__(self, request: dict[str, Any]) -> Any: ...


class ProviderError(RuntimeError):
    """Raised when an injected model boundary cannot be resolved."""


def create_configured_model(
    config: QuotationConfig | str | Path | None = None,
    *,
    dotenv_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Construct a configured OpenAI-compatible model without making a request.

    ``config`` may be a validated :class:`QuotationConfig` or a dotenv path.
    When omitted, configuration is loaded from the current directory and the
    optional injected environment mapping. The adapter import is intentionally
    local so importing this package never initializes a provider.
    """

    if isinstance(config, QuotationConfig):
        if dotenv_path is not None or environ is not None:
            raise ProviderError(
                "Do not combine a QuotationConfig with dotenv or environment inputs"
            )
        resolved_config = config
    elif config is None:
        resolved_config = load_config(dotenv_path, environ=environ)
    elif isinstance(config, (str, Path)):
        if dotenv_path is not None:
            raise ProviderError("Pass the dotenv path either positionally or by keyword, not both")
        resolved_config = load_config(config, environ=environ)
    else:
        raise ProviderError("config must be a QuotationConfig or dotenv path")

    api_key = (
        resolved_config.api_key.get_secret_value()
        if resolved_config.api_key is not None
        else None
    )
    if api_key is None:
        if resolved_config.provider == "ollama":
            api_key = "ollama"
        else:
            raise ProviderError(
                f"API key is required for provider '{resolved_config.provider}'; "
                "set QUOTATION_API_KEY or the provider-specific API key"
            )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ProviderError("langchain-openai is required to construct a quotation model") from exc

    kwargs: dict[str, Any] = {
        "model": resolved_config.model,
        "timeout": resolved_config.http_timeout_seconds,
        "api_key": api_key,
    }
    if resolved_config.base_url is not None:
        kwargs["base_url"] = resolved_config.base_url
    return ChatOpenAI(**kwargs)


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
