"""Load the canonical professional profile from Markdown."""

from __future__ import annotations

from .config import CVConfig


class ProfileLoadError(RuntimeError):
    """Raised when the configured professional profile cannot be read."""


def load_profile(config: CVConfig) -> str:
    """Return the profile Markdown exactly as stored in the configured file."""

    vault_root = config.vault_root.resolve()
    profile_file = config.profile_file
    resolved_profile = profile_file.resolve(strict=False)
    try:
        resolved_profile.relative_to(vault_root)
    except ValueError as exc:
        raise ProfileLoadError("Configured profile path escapes the Obsidian vault") from exc

    if not profile_file.exists():
        raise ProfileLoadError(f"Professional profile not found: {profile_file}")
    if not profile_file.is_file():
        raise ProfileLoadError(f"Professional profile is not a file: {profile_file}")

    try:
        return profile_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        message = f"Unable to read professional profile {profile_file}: {exc}"
        raise ProfileLoadError(message) from exc
