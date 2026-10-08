from typing import Any

import pytest
from pydantic import ValidationError

from quotation_agents import (
    ApprovalState,
    DraftApprovalRequiredError,
    InferenceError,
    ProviderError,
    QuotationDraft,
    RequirementInference,
    approve_draft,
    create_requirement_inference_agent,
    infer_requirements,
    intake_draft,
    require_approved_draft,
    revise_draft,
)

REQUEST = "  Build a booking site\nwith payment support.  "


def test_injected_mapping_produces_pending_draft_and_preserves_intake() -> None:
    calls: list[dict[str, Any]] = []

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(request)
        return {
            "structured_response": {
                "inferred_scope": ["Booking flow"],
                "assumptions": ["Payment provider is not selected"],
                "questions": ["Which payment provider is required?"],
                "risks": ["Payment requirements may change"],
            }
        }

    draft = intake_draft("Example Ltd", REQUEST, invoke=fake_invoke)

    assert draft.client_company == "Example Ltd"
    assert draft.original_request == REQUEST
    assert draft.inferred_scope == ["Booking flow"]
    assert draft.approval_state is ApprovalState.PENDING
    assert len(calls) == 1


def test_provider_request_delimits_untrusted_input_and_excludes_approval_output() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"structured_response": RequirementInference(inferred_scope=["Checkout"])}

    infer_requirements("Example Ltd", REQUEST, invoke=fake_invoke)

    user_content = seen["messages"][1]["content"]
    assert "<quotation_input_data>" in user_content
    assert "</quotation_input_data>" in user_content
    assert "<client_company>\nExample Ltd\n</client_company>" in user_content
    assert f"<original_request>\n{REQUEST}\n</original_request>" in user_content
    assert "untrusted source data" in seen["messages"][0]["content"]
    assert "approval" in seen["messages"][0]["content"]

    with pytest.raises(InferenceError):
        infer_requirements(
            "Example Ltd",
            REQUEST,
            invoke=lambda _: {
                "structured_response": {
                    "inferred_scope": [],
                    "approval_state": "approved",
                }
            },
        )

    with pytest.raises(InferenceError):
        infer_requirements(
            "Example Ltd",
            REQUEST,
            invoke=lambda _: {
                "structured_response": QuotationDraft(
                    client_company="Example Ltd",
                    original_request=REQUEST,
                    approval_state=ApprovalState.APPROVED,
                )
            },
        )


@pytest.mark.parametrize(
    ("client_company", "original_request"),
    [("", "A request"), ("  ", "A request"), ("Example Ltd", ""), ("Example Ltd", "  ")],
)
def test_blank_intake_is_rejected_before_provider_call(
    client_company: str, original_request: str
) -> None:
    called = False

    def fake_invoke(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"structured_response": {}}

    with pytest.raises(ValidationError):
        intake_draft(client_company, original_request, invoke=fake_invoke)

    assert called is False


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"structured_response": None},
        {"structured_response": {"unknown": "field"}},
        {"structured_response": {"inferred_scope": "not a list"}},
    ],
)
def test_missing_or_invalid_provider_payload_fails_deterministically(
    response: dict[str, Any],
) -> None:
    with pytest.raises(InferenceError):
        infer_requirements("Example Ltd", REQUEST, invoke=lambda _: response)


def test_workflow_requires_explicit_approval_and_revision_resets_it() -> None:
    draft = intake_draft(
        "Example Ltd",
        REQUEST,
        invoke=lambda _: {"structured_response": {"inferred_scope": ["Booking flow"]}},
    )

    with pytest.raises(DraftApprovalRequiredError):
        require_approved_draft(draft)

    approved = approve_draft(draft)
    assert approved.approval_state is ApprovalState.APPROVED
    assert require_approved_draft(approved) is approved

    revised = revise_draft(approved, inferred_scope=["Booking flow", "Checkout"])
    assert revised.approval_state is ApprovalState.PENDING
    assert revised.original_request == REQUEST
    assert revised.inferred_scope == ["Booking flow", "Checkout"]


def test_revision_cannot_change_original_request() -> None:
    draft = intake_draft(
        "Example Ltd",
        REQUEST,
        invoke=lambda _: {"structured_response": {}},
    )

    with pytest.raises(ValueError, match="original_request"):
        revise_draft(draft, original_request="A different request")


def test_inference_requires_an_injected_boundary() -> None:
    with pytest.raises(ProviderError):
        infer_requirements("Example Ltd", REQUEST)


def test_agent_factory_uses_injected_model_and_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(model: Any, **kwargs: Any) -> object:
        captured["model"] = model
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("quotation_agents.inference.create_agent", fake_create_agent)
    model = object()

    assert create_requirement_inference_agent(model) is not None
    assert captured["model"] is model
    assert captured["response_format"] is RequirementInference
    assert "untrusted source data" in captured["system_prompt"]
