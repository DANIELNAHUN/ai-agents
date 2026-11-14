import sys
from types import SimpleNamespace
from typing import Any

import pytest

from quotation_agents import QuotationConfig
from quotation_agents.provider import ProviderError, create_configured_model, resolve_invocation


def test_resolve_invocation_accepts_fake_callable() -> None:
    response = {"structured_response": {"ok": True}}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        return {**response, "request": request}

    invocation = resolve_invocation(invoke=fake_invoke)

    assert invocation({"text": "offline test"}) == {
        "structured_response": {"ok": True},
        "request": {"text": "offline test"},
    }


def test_resolve_invocation_accepts_model_with_invoke_method() -> None:
    class FakeModel:
        def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
            return {"received": request}

    invocation = resolve_invocation(model=FakeModel())

    assert invocation({"prompt": "test"}) == {"received": {"prompt": "test"}}


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"invoke": lambda request: request, "model": object()},
        {"model": object()},
    ],
)
def test_resolve_invocation_reports_invalid_or_missing_boundary(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ProviderError):
        resolve_invocation(**kwargs)


def test_create_configured_model_passes_openai_compatible_kwargs_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    model = create_configured_model(
        QuotationConfig(
            provider="freellm",
            model="local-model",
            http_timeout_seconds=22,
            base_url="https://free.example/v1",
            api_key="test-secret",
        )
    )

    assert isinstance(model, FakeChatOpenAI)
    assert calls == [
        {
            "model": "local-model",
            "timeout": 22.0,
            "api_key": "test-secret",
            "base_url": "https://free.example/v1",
        }
    ]


def test_create_configured_model_uses_ollama_sentinel_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    create_configured_model(QuotationConfig(provider="ollama"))

    assert calls[0]["api_key"] == "ollama"
    assert calls[0]["base_url"] == "http://localhost:11434/v1"


def test_create_configured_model_rejects_missing_key_without_exposing_secret() -> None:
    with pytest.raises(ProviderError, match="API key is required") as error:
        create_configured_model(QuotationConfig(provider="openai"))

    assert "API key is required" in str(error.value)


def test_create_configured_model_loads_dotenv_path_and_environment(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "QUOTATION_PROVIDER=openai\nQUOTATION_MODEL=dotenv-model\nQUOTATION_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=FakeChatOpenAI))

    create_configured_model(dotenv_file, environ={"QUOTATION_MODEL": "environment-model"})

    assert calls[0]["model"] == "environment-model"
    assert calls[0]["api_key"] == "dotenv-key"
