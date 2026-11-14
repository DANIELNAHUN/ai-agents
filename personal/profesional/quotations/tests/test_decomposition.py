from typing import Any

import pytest
from pydantic import ValidationError

from quotation_agents import (
    ApprovalState,
    DecompositionError,
    DraftApprovalRequiredError,
    ProviderError,
    QuotationDraft,
    QuotationTask,
    TaskDecomposition,
    WorkCategory,
    approve_draft,
    create_decomposition_agent,
    decompose_category,
    require_approved_draft,
    revise_draft,
)

REQUEST = "  Build a booking site\nwith payment support.  "


def approved_draft() -> QuotationDraft:
    return QuotationDraft(
        client_company="Example Ltd",
        original_request=REQUEST,
        inferred_scope=["Booking flow"],
        assumptions=["Payment provider is not selected"],
        questions=["Which payment provider is required?"],
        risks=["Payment requirements may change"],
        approval_state=ApprovalState.APPROVED,
    )


def response_for(category: WorkCategory, description: str = "Implement the task") -> dict[str, Any]:
    return {
        "structured_response": {
            "tasks": [{"category": category.value, "description": description}],
        }
    }


def test_agent_factory_uses_schema_tools_and_requested_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(model: Any, **kwargs: Any) -> object:
        captured["model"] = model
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("quotation_agents.decomposition.create_agent", fake_create_agent)
    model = object()
    tools = [object()]

    assert (
        create_decomposition_agent(
            model,
            category=WorkCategory.BACKEND,
            tools=tools,
        )
        is not None
    )
    assert captured["model"] is model
    assert captured["tools"] == tools
    assert captured["response_format"] is TaskDecomposition
    assert WorkCategory.BACKEND.value in captured["system_prompt"]
    assert "untrusted source data" in captured["system_prompt"]

    with pytest.raises(DecompositionError):
        create_decomposition_agent(model, category="mobile")


@pytest.mark.parametrize("boundary", ["invoke", "model", "agent"])
def test_decomposition_supports_callable_model_and_agent_injection(boundary: str) -> None:
    calls: list[dict[str, Any]] = []

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(request)
        return response_for(WorkCategory.BACKEND)

    class FakeModel:
        def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
            return fake_invoke(request)

    kwargs = {boundary: fake_invoke if boundary != "model" else FakeModel()}
    result = decompose_category(approved_draft(), WorkCategory.BACKEND, **kwargs)

    assert result.tasks[0].category is WorkCategory.BACKEND
    assert len(calls) == 1


def test_decomposition_delimits_and_preserves_request_source() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"structured_response": TaskDecomposition()}

    draft = approved_draft()
    result = decompose_category(draft, WorkCategory.FRONTEND, invoke=fake_invoke)

    user_content = seen["messages"][1]["content"]
    assert result.tasks == []
    assert "<quotation_input_data>" in user_content
    assert "</quotation_input_data>" in user_content
    assert f"<client_company>\n{draft.client_company}\n</client_company>" in user_content
    assert f"<original_request>\n{REQUEST}\n</original_request>" in user_content
    assert "<requested_category>\nfrontend\n</requested_category>" in user_content
    assert "untrusted source data" in seen["messages"][0]["content"]


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"structured_response": None},
        {"structured_response": {"unknown": "field"}},
        {
            "structured_response": {
                "tasks": [{"category": "backend", "description": "Task", "extra": True}]
            }
        },
        {"structured_response": {"tasks": "not a list"}},
    ],
)
def test_malformed_or_unknown_decomposition_output_is_rejected(
    response: dict[str, Any],
) -> None:
    with pytest.raises(DecompositionError):
        decompose_category(approved_draft(), WorkCategory.BACKEND, invoke=lambda _: response)


def test_mixed_category_output_is_rejected_without_rewriting_tasks() -> None:
    response = {
        "structured_response": {
            "tasks": [
                {"category": "backend", "description": "Build API"},
                {"category": "frontend", "description": "Build screen"},
            ]
        }
    }

    with pytest.raises(DecompositionError, match="outside the requested"):
        decompose_category(approved_draft(), WorkCategory.BACKEND, invoke=lambda _: response)


def test_pending_approval_short_circuits_before_provider_invocation() -> None:
    draft = approved_draft().model_copy(update={"approval_state": ApprovalState.PENDING})
    called = False

    def fake_invoke(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called = True
        return response_for(WorkCategory.BACKEND)

    with pytest.raises(DraftApprovalRequiredError):
        decompose_category(draft, WorkCategory.BACKEND, invoke=fake_invoke)

    assert called is False


def test_decomposition_does_not_mutate_draft_and_revision_requires_reapproval() -> None:
    draft = approved_draft()
    result = decompose_category(
        draft,
        WorkCategory.BACKEND,
        invoke=lambda _: response_for(WorkCategory.BACKEND, "Build API"),
    )

    assert draft.tasks == []
    assert draft.approval_state is ApprovalState.APPROVED
    revised = revise_draft(draft, tasks=result.tasks)

    assert revised.client_company == draft.client_company
    assert revised.original_request == REQUEST
    assert revised.tasks == result.tasks
    assert revised.approval_state is ApprovalState.PENDING
    with pytest.raises(DraftApprovalRequiredError):
        require_approved_draft(revised)
    assert approve_draft(revised).approval_state is ApprovalState.APPROVED


def test_decomposition_requires_an_injected_boundary_for_approved_draft() -> None:
    with pytest.raises(ProviderError, match="injected invoke callable or model"):
        decompose_category(approved_draft(), WorkCategory.DEVOPS)


def test_task_decomposition_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TaskDecomposition.model_validate({"tasks": [], "approval_state": "approved"})


def test_decomposition_prompt_requires_hour_estimates_for_every_task() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"structured_response": TaskDecomposition()}

    decompose_category(approved_draft(), WorkCategory.BACKEND, invoke=fake_invoke)

    system_prompt = seen["messages"][0]["content"]
    assert "estimated_hours" in system_prompt
    assert "Every task must include" in system_prompt
    assert "invent requirements, estimates" not in system_prompt
    assert len(seen["messages"]) == 2


def test_decomposition_sends_reviewer_feedback_with_previous_tasks() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return response_for(WorkCategory.BACKEND, "Build claims API")

    previous = [
        QuotationTask(category=WorkCategory.BACKEND, description="Claims inbox"),
        QuotationTask(
            category=WorkCategory.BACKEND, description="Notifications", estimated_hours="6"
        ),
    ]
    result = decompose_category(
        approved_draft(),
        WorkCategory.BACKEND,
        invoke=fake_invoke,
        feedback="Split the inbox into list and detail tasks",
        previous_tasks=previous,
    )

    assert result.tasks[0].description == "Build claims API"
    assert len(seen["messages"]) == 3
    feedback_message = seen["messages"][2]
    assert feedback_message["role"] == "user"
    assert "<reviewer_feedback>" in feedback_message["content"]
    assert "Split the inbox into list and detail tasks" in feedback_message["content"]
    assert "- Claims inbox (no estimate)" in feedback_message["content"]
    assert "- Notifications (6h)" in feedback_message["content"]
    assert "<quotation_input_data>" not in feedback_message["content"]


def test_decomposition_feedback_uses_reviewer_task_numbers() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"structured_response": TaskDecomposition()}

    previous = [
        QuotationTask(
            category=WorkCategory.DEVOPS, description="Docker setup", estimated_hours="4"
        ),
        QuotationTask(category=WorkCategory.DEVOPS, description="CI/CD pipeline"),
    ]
    decompose_category(
        approved_draft(),
        WorkCategory.DEVOPS,
        invoke=fake_invoke,
        feedback="14. takes 3 hours, remove 15.",
        previous_tasks=previous,
        task_numbers=[14, 15],
    )

    content = seen["messages"][2]["content"]
    assert "14. Docker setup (4h)" in content
    assert "15. CI/CD pipeline (no estimate)" in content


def test_decomposition_prompt_says_to_omit_removed_tasks_instead_of_zero_hours() -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(request: dict[str, Any]) -> dict[str, Any]:
        seen.update(request)
        return {"structured_response": TaskDecomposition()}

    decompose_category(approved_draft(), WorkCategory.DEVOPS, invoke=fake_invoke)

    system_prompt = seen["messages"][0]["content"]
    assert "omit it from the list" in system_prompt
    assert "never return 0 hours" in system_prompt
    assert "by their number" in system_prompt


def test_decomposition_prompt_explains_developer_profile():
    from quotation_agents.decomposition import DECOMPOSITION_SYSTEM_PROMPT

    assert "developer_profile.md" in DECOMPOSITION_SYSTEM_PROMPT
    assert "(digest)" in DECOMPOSITION_SYSTEM_PROMPT
