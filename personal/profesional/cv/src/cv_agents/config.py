"""Configuration loading and validation for the CV package."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigurationError(ValueError):
    """Raised when the CV configuration is missing or unsafe to use."""


class CVConfig(BaseModel):
    """Validated runtime configuration for the CV pipeline."""

    model_config = ConfigDict(extra="forbid")

    vault_root: Path = Field(description="Absolute path to the local Obsidian vault")
    profile_path: str = Field(description="Markdown profile path relative to the vault")
    http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    model: str = Field(default="gpt-4o-mini", min_length=1, description="Configured CV model name")

    @field_validator("vault_root", mode="before")
    @classmethod
    def validate_vault_root(cls, value: object) -> Path:
        if value is None or not str(value).strip():
            raise ValueError("CV_VAULT_ROOT is required")

        root = Path(str(value)).expanduser()
        if not root.is_absolute():
            root = root.resolve()
        if not root.exists():
            raise ValueError(f"CV vault root does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"CV vault root is not a directory: {root}")
        return root.resolve()

    @field_validator("profile_path", mode="before")
    @classmethod
    def validate_profile_path(cls, value: object) -> str:
        if value is None or not str(value).strip():
            raise ValueError("CV_PROFILE_PATH is required")

        raw_path = str(value).strip()
        profile_path = Path(raw_path)
        if profile_path.is_absolute() or profile_path.drive or profile_path.root:
            raise ValueError("CV_PROFILE_PATH must be relative to CV_VAULT_ROOT")
        if ".." in profile_path.parts:
            raise ValueError("CV_PROFILE_PATH must not escape CV_VAULT_ROOT")
        if profile_path.suffix.lower() != ".md":
            raise ValueError("CV_PROFILE_PATH must point to a Markdown file")
        return profile_path.as_posix()

    @property
    def profile_file(self) -> Path:
        """Return the configured profile path without requiring the file to exist."""

        return self.vault_root / self.profile_path


def load_config(
    dotenv_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> CVConfig:
    """Load configuration from dotenv and environment variables.

    Process environment variables take precedence over values in the dotenv file.
    The profile itself is intentionally not read by this function.
    """

    env_file = Path(dotenv_path) if dotenv_path is not None else Path.cwd() / ".env"
    dotenv_settings = dotenv_values(env_file) if env_file.is_file() else {}
    process_environment = os.environ if environ is None else environ
    settings = {
        **{key: value for key, value in dotenv_settings.items() if value is not None},
        **dict(process_environment),
    }

    try:
        return CVConfig(
            vault_root=settings.get("CV_VAULT_ROOT"),
            profile_path=settings.get("CV_PROFILE_PATH"),
            http_timeout_seconds=settings.get("CV_HTTP_TIMEOUT_SECONDS", 15.0),
            model=settings.get("CV_MODEL", "gpt-4o-mini"),
        )
    except ValueError as exc:
        raise ConfigurationError(f"Invalid CV configuration: {exc}") from exc
