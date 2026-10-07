from pathlib import Path

import pytest

from cv_agents.config import CVConfig
from cv_agents.profile import ProfileLoadError, load_profile


def test_load_profile_returns_raw_markdown(tmp_path: Path) -> None:
    profile = tmp_path / "professional.md"
    raw_markdown = "# Professional profile\n\n- Python  \n"
    profile.write_text(raw_markdown, encoding="utf-8")
    config = CVConfig(vault_root=tmp_path, profile_path=profile.name)

    assert load_profile(config) == raw_markdown


def test_load_profile_reports_missing_file(tmp_path: Path) -> None:
    config = CVConfig(vault_root=tmp_path, profile_path="missing.md")

    with pytest.raises(ProfileLoadError, match="not found"):
        load_profile(config)


def test_load_profile_reports_directory_instead_of_file(tmp_path: Path) -> None:
    (tmp_path / "profile.md").mkdir()
    config = CVConfig(vault_root=tmp_path, profile_path="profile.md")

    with pytest.raises(ProfileLoadError, match="not a file"):
        load_profile(config)
