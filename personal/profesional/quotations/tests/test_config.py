from pathlib import Path

import pytest

from quotation_agents.config import ConfigurationError, QuotationConfig, load_config


def test_load_config_uses_defaults_and_injected_environment(tmp_path: Path) -> None:
    config = load_config(
        tmp_path / "missing.env",
        environ={"QUOTATION_MODEL": "test-model"},
    )

    assert config == QuotationConfig(model="test-model", http_timeout_seconds=15)


def test_process_environment_overrides_dotenv(tmp_path: Path) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "QUOTATION_MODEL=dotenv-model\nQUOTATION_HTTP_TIMEOUT_SECONDS=20\n",
        encoding="utf-8",
    )

    config = load_config(
        dotenv_file,
        environ={"QUOTATION_MODEL": "environment-model"},
    )

    assert config.model == "environment-model"
    assert config.http_timeout_seconds == 20


@pytest.mark.parametrize("timeout", ["0", "121", "not-a-number"])
def test_load_config_rejects_invalid_timeout(tmp_path: Path, timeout: str) -> None:
    with pytest.raises(ConfigurationError, match="Invalid quotation configuration"):
        load_config(environ={"QUOTATION_HTTP_TIMEOUT_SECONDS": timeout})


def test_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        QuotationConfig(model="test-model", unexpected="value")


def test_config_rejects_blank_model_name() -> None:
    with pytest.raises(ConfigurationError, match="QUOTATION_MODEL must not be blank"):
        load_config(environ={"QUOTATION_MODEL": "  "})
