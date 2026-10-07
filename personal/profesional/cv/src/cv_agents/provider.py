"""Optional provider construction kept lazy and explicit."""

from __future__ import annotations

from typing import Any


class ProviderError(RuntimeError):
    """Raised when the configured model provider cannot be constructed."""


def create_openai_model(model_name: str) -> Any:
    """Create an OpenAI chat model only when the pipeline is actually invoked.

    The API key is read by ``langchain-openai`` from its normal environment
    configuration. It is never accepted as a function argument or persisted.
    """

    if not model_name.strip():
        raise ProviderError("CV_MODEL cannot be empty")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ProviderError(
            "OpenAI support is not installed; install the project dependencies to use the CLI"
        ) from exc
    try:
        return ChatOpenAI(model=model_name)
    except Exception as exc:
        raise ProviderError(f"Unable to configure OpenAI model {model_name!r}: {exc}") from exc
