from pathlib import Path

import pytest

from cv_agents.config import ConfigurationError, CVConfig, load_config


def test_load_config_reads_dotenv_and_resolves_profile_without_reading_it(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        f"CV_VAULT_ROOT={vault}\nCV_PROFILE_PATH=profile/professional.md\n",
        encoding="utf-8",
    )

    config = load_config(dotenv_file, environ={})

    assert config.vault_root == vault.resolve()
    assert config.profile_file == vault / "profile" / "professional.md"
    assert not config.profile_file.exists()


def test_config_rejects_profile_paths_outside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="must not escape"):
        CVConfig(vault_root=vault, profile_path="../profile.md")


def test_load_config_reports_missing_required_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="CV_VAULT_ROOT is required"):
        load_config(tmp_path / ".env", environ={})
