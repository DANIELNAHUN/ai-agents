from pathlib import Path

import pytest

from quotation_agents.config import (
    OLLAMA_DEFAULT_BASE_URL,
    ConfigurationError,
    QuotationConfig,
    load_config,
)


def test_load_config_uses_defaults_and_injected_environment(tmp_path: Path) -> None:
    config = load_config(
        tmp_path / "missing.env",
        environ={"QUOTATION_MODEL": "test-model"},
    )

    assert config == QuotationConfig(model="test-model", http_timeout_seconds=15)


def test_process_environment_overrides_dotenv(tmp_path: Path) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "QUOTATION_PROVIDER=ollama\n"
        "QUOTATION_MODEL=dotenv-model\n"
        "QUOTATION_HTTP_TIMEOUT_SECONDS=20\n"
        "QUOTATION_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )

    config = load_config(
        dotenv_file,
        environ={"QUOTATION_PROVIDER": "OPENAI", "QUOTATION_MODEL": "environment-model"},
    )

    assert config.provider == "openai"
    assert config.model == "environment-model"
    assert config.http_timeout_seconds == 20
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "dotenv-key"


def test_load_config_resolves_provider_key_fallbacks() -> None:
    config = load_config(
        environ={
            "QUOTATION_PROVIDER": "Omni-Route",
            "QUOTATION_BASE_URL": "https://gateway.example/v1",
            "OMNIROUTE_API_KEY": "omni-secret",
        }
    )

    assert config.provider == "omniroute"
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "omni-secret"
    assert "omni-secret" not in repr(config)
    assert "omni-secret" not in str(config)


def test_ollama_defaults_to_local_endpoint_without_a_key() -> None:
    config = load_config(environ={"QUOTATION_PROVIDER": "OLLAMA"})

    assert config.provider == "ollama"
    assert config.base_url == OLLAMA_DEFAULT_BASE_URL
    assert config.api_key is None


@pytest.mark.parametrize(
    ("provider", "message"),
    [("unknown", "openai, ollama, omniroute, freellm"), ("  ", "must not be blank")],
)
def test_load_config_rejects_invalid_provider(provider: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_config(environ={"QUOTATION_PROVIDER": provider})


@pytest.mark.parametrize("base_url", ["file:///tmp/model", "not-an-url", "ftp://model.example"])
def test_load_config_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ConfigurationError, match=r"HTTP\(S\) URL"):
        load_config(
            environ={
                "QUOTATION_PROVIDER": "openai",
                "QUOTATION_BASE_URL": base_url,
            }
        )


def test_load_config_requires_base_url_for_deployment_specific_provider() -> None:
    with pytest.raises(ConfigurationError, match="QUOTATION_BASE_URL is required"):
        load_config(environ={"QUOTATION_PROVIDER": "freellm"})


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
