"""Configuration loading and validation for the quotation package."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigurationError(ValueError):
    """Raised when quotation configuration is invalid."""


class QuotationConfig(BaseModel):
    """Validated runtime configuration for quotation workflows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(default="gpt-4o-mini", min_length=1)
    http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("QUOTATION_MODEL must not be blank")
        return value


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
        return QuotationConfig(
            model=settings.get("QUOTATION_MODEL", "gpt-4o-mini"),
            http_timeout_seconds=settings.get("QUOTATION_HTTP_TIMEOUT_SECONDS", 15.0),
        )
    except ValueError as exc:
        raise ConfigurationError(f"Invalid quotation configuration: {exc}") from exc
