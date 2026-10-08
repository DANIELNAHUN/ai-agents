from typing import Any

import pytest

from quotation_agents.provider import ProviderError, resolve_invocation


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
