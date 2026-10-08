"""Configuration loading and validation for the quotation package."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

SUPPORTED_PROVIDERS = ("openai", "ollama", "omniroute", "freellm")
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"

_PROVIDER_ALIASES = {
    "openai": "openai",
    "open-ai": "openai",
    "open_ai": "openai",
    "ollama": "ollama",
    "omniroute": "omniroute",
    "omni-route": "omniroute",
    "omni_route": "omniroute",
    "freellm": "freellm",
    "free-llm": "freellm",
    "free_llm": "freellm",
}


class ConfigurationError(ValueError):
    """Raised when quotation configuration is invalid."""


class QuotationConfig(BaseModel):
    """Validated runtime configuration for quotation workflows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(default="openai", min_length=1)
    model: str = Field(default="gpt-4o-mini", min_length=1)
    http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    base_url: str | None = None
    api_key: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_and_defaults(cls, values: object) -> object:
        if not isinstance(values, Mapping):
            return values

        settings = dict(values)
        provider = _normalize_provider(settings.get("provider", "openai"))
        settings["provider"] = provider
        if provider == "ollama" and not _has_value(settings.get("base_url")):
            settings["base_url"] = OLLAMA_DEFAULT_BASE_URL
        if provider in {"omniroute", "freellm"} and not _has_value(settings.get("base_url")):
            raise ValueError(f"QUOTATION_BASE_URL is required for provider '{provider}'")
        return settings

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _normalize_provider(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("QUOTATION_MODEL must not be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.hostname is None:
            raise ValueError("QUOTATION_BASE_URL must be an HTTP(S) URL")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            return value
        if not isinstance(value, str):
            raise ValueError("QUOTATION_API_KEY must be a string")
        value = value.strip()
        return value or None


def load_config(
    dotenv_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> QuotationConfig:
    """Load dotenv values, then override them with process or injected values."""

    env_file = Path(dotenv_path) if dotenv_path is not None else Path.cwd() / ".env"
    dotenv_settings = dotenv_values(env_file) if env_file.is_file() else {}
    process_environment = os.environ if environ is None else environ
    settings = {
        **{key: value for key, value in dotenv_settings.items() if value is not None},
        **dict(process_environment),
    }

    try:
        provider = _normalize_provider(settings.get("QUOTATION_PROVIDER", "openai"))
        api_key = _first_value(
            settings,
            "QUOTATION_API_KEY",
            f"{provider.upper()}_API_KEY",
        )
        return QuotationConfig(
            provider=provider,
            model=settings.get("QUOTATION_MODEL", "gpt-4o-mini"),
            http_timeout_seconds=settings.get("QUOTATION_HTTP_TIMEOUT_SECONDS", 15.0),
            base_url=_optional_value(settings.get("QUOTATION_BASE_URL")),
            api_key=api_key,
        )
    except ValueError as exc:
        raise ConfigurationError(f"Invalid quotation configuration: {exc}") from exc


def _has_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_value(settings: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = _optional_value(settings.get(name))
        if value is not None:
            return value
    return None


def _normalize_provider(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("QUOTATION_PROVIDER must not be blank")
    normalized = _PROVIDER_ALIASES.get(value.strip().lower())
    if normalized is None:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(f"Unsupported quotation provider; supported providers: {supported}")
    return normalized
