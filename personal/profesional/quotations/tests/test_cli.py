"""CLI wiring tests: phases must call structured agents, not raw chat models."""

from __future__ import annotations

import io
from typing import Any

import pytest

from quotation_agents import (
    ApprovalState,
    QuotationDraft,
    QuotationTask,
    QuoteResult,
    WorkCategory,
    approve_draft,
    cli,
)
from quotation_agents.progress import ProgressReporter


class RawChatModel:
    """Mimics ChatOpenAI: rejects the agent-style dict request."""

    def invoke(self, request: Any) -> Any:
        if isinstance(request, dict):
            raise ValueError(
                f"Invalid input type {type(request)}. "
                "Must be a PromptValue, str, or list of BaseMessages."
            )
        raise AssertionError("raw model must not be invoked by the CLI")


class FakeAgent:
    def __init__(self, structured_response: dict[str, Any]) -> None:
        self.structured_response = structured_response
        self.requests: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any] | None] = []

    def invoke(
        self, request: dict[str, Any], config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append(request)
        self.configs.append(config)
        return {"structured_response": self.structured_response}


def _feed_input(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_args: next(iterator))


def test_intake_builds_inference_agent_from_configured_model(monkeypatch, capsys):
    model = RawChatModel()
    model.model_name = "gpt-4o-mini"
    agent = FakeAgent({"inferred_scope": ["Claims inbox"], "risks": ["External API"]})
    built_with: list[Any] = []

    def fake_factory(received_model: Any) -> FakeAgent:
        built_with.append(received_model)
        return agent

    monkeypatch.setattr(cli, "create_requirement_inference_agent", fake_factory)
    _feed_input(monkeypatch, ["Cableclub", "Claims module", "", "", "y"])

    draft = cli._phase_intake(model)

    assert built_with == [model]
    assert len(agent.requests) == 1
    assert draft.client_company == "Cableclub"
    assert draft.original_request == "Claims module"
    assert draft.inferred_scope == ["Claims inbox"]
    assert draft.risks == ["External API"]
    assert agent.configs[0] is not None and agent.configs[0]["callbacks"]
    output = capsys.readouterr().out
    assert "▸ Requirement inference agent · gpt-4o-mini" in output
    assert "✔ Requirement inference agent · gpt-4o-mini ·" in output


def test_intake_prompt_explains_two_empty_lines_and_keeps_paragraphs(monkeypatch, capsys):
    agent = FakeAgent({"inferred_scope": ["Claims inbox"]})
    monkeypatch.setattr(cli, "create_requirement_inference_agent", lambda _model: agent)
    _feed_input(
        monkeypatch,
        ["Cableclub", "First paragraph", "", "Second paragraph", "", "", "y"],
    )

    draft = cli._phase_intake(RawChatModel())

    output = capsys.readouterr().out
    assert "Press Enter on two empty lines in a row to finish." in output
    assert "Press Enter twice when done." not in output
    assert draft.original_request == "First paragraph\n\nSecond paragraph"


def test_decompose_builds_one_agent_per_category(monkeypatch, capsys):
    model = RawChatModel()
    built: list[tuple[Any, WorkCategory]] = []
    agents: list[FakeAgent] = []

    def fake_factory(received_model: Any, *, category: WorkCategory) -> FakeAgent:
        built.append((received_model, category))
        agent = FakeAgent(
            {
                "tasks": [
                    {
                        "category": category.value,
                        "description": f"{category.value} task",
                        "estimated_hours": "2",
                    }
                ]
            }
        )
        agents.append(agent)
        return agent

    monkeypatch.setattr(cli, "create_decomposition_agent", fake_factory)
    _feed_input(monkeypatch, ["a"])
    draft = approve_draft(
        QuotationDraft(
            client_company="Cableclub",
            original_request="Claims module",
            inferred_scope=["Claims inbox"],
        )
    )

    result = cli._phase_decompose(draft, model)

    assert built == [(model, category) for category in WorkCategory]
    assert all(len(agent.requests) == 1 for agent in agents)
    assert len(result.tasks) == len(WorkCategory)
    output = capsys.readouterr().out
    for category in WorkCategory:
        assert f"✔ Decomposition agent [{category.value}]" in output


def _scope_draft(approved: bool = True) -> QuotationDraft:
    draft = QuotationDraft(
        client_company="Cableclub",
        original_request="Claims module",
        inferred_scope=["Claims inbox"],
    )
    return approve_draft(draft) if approved else draft


def _decomposition_factory(responses: dict[WorkCategory, list[list[dict[str, Any]]]]):
    """Return a factory whose agents answer per category, one response per call."""

    agents: dict[WorkCategory, list[FakeAgent]] = {category: [] for category in WorkCategory}

    def factory(_model: Any, *, category: WorkCategory) -> FakeAgent:
        queue = responses.get(category) or [[]]
        tasks = queue.pop(0) if len(queue) > 1 else queue[0]
        agent = FakeAgent({"tasks": tasks})
        agents[category].append(agent)
        return agent

    return factory, agents


def test_task_review_blocks_approval_without_hours_and_allows_manual_edit(monkeypatch, capsys):
    backend_task = {"category": "backend", "description": "Claims inbox API"}
    factory, _agents = _decomposition_factory({WorkCategory.BACKEND: [[backend_task]]})
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["x", "a", "e", "1", "abc", "8", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert "1 task has no estimated hours" in output
    assert "Every task needs estimated hours before pricing" in output
    assert "Invalid option" in output
    assert "Enter a positive number of hours" in output
    assert draft.approval_state is ApprovalState.APPROVED
    assert [(task.description, task.estimated_hours) for task in draft.tasks] == [
        ("Claims inbox API", 8)
    ]


def test_task_review_revises_one_category_with_reviewer_feedback(monkeypatch):
    first = {"category": "backend", "description": "Claims inbox API"}
    revised = {"category": "backend", "description": "Claims inbox API", "estimated_hours": "12"}
    factory, agents = _decomposition_factory({WorkCategory.BACKEND: [[first], [revised]]})
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["r", "2", "Estimate hours for every task", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    backend_agents = agents[WorkCategory.BACKEND]
    assert len(backend_agents) == 2
    assert len(agents[WorkCategory.FRONTEND]) == 1
    feedback_message = backend_agents[1].requests[0]["messages"][2]["content"]
    assert "Estimate hours for every task" in feedback_message
    assert "1. Claims inbox API (no estimate)" in feedback_message
    assert [(task.description, task.estimated_hours) for task in draft.tasks] == [
        ("Claims inbox API", 12)
    ]


def test_scope_review_revises_with_reviewer_feedback(monkeypatch):
    agent = FakeAgent({"inferred_scope": ["Claims inbox", "Dashboard with three charts"]})
    monkeypatch.setattr(cli, "create_requirement_inference_agent", lambda _model: agent)
    _feed_input(monkeypatch, ["r", "The dashboard has three charts", "a"])

    draft = cli._phase_review_draft(_scope_draft(approved=False), RawChatModel())

    assert draft.approval_state is ApprovalState.APPROVED
    assert draft.inferred_scope == ["Claims inbox", "Dashboard with three charts"]
    assert draft.original_request == "Claims module"
    feedback_message = agent.requests[0]["messages"][2]["content"]
    assert "The dashboard has three charts" in feedback_message
    assert "Claims inbox" in feedback_message


def test_scope_review_reports_each_applied_revision(monkeypatch):
    agent = FakeAgent({"inferred_scope": ["Claims inbox", "SSO"]})
    monkeypatch.setattr(cli, "create_requirement_inference_agent", lambda _model: agent)
    _feed_input(monkeypatch, ["r", "Add SSO", "a"])
    revisions = []

    draft = cli._phase_review_draft(
        _scope_draft(approved=False),
        RawChatModel(),
        on_revision=lambda feedback, revised: revisions.append((feedback, revised)),
    )

    assert [(feedback, revised.inferred_scope) for feedback, revised in revisions] == [
        ("Add SSO", ["Claims inbox", "SSO"])
    ]
    assert revisions[0][1].approval_state is ApprovalState.PENDING
    assert draft.inferred_scope == ["Claims inbox", "SSO"]


def test_scope_review_approves_without_calling_the_agent(monkeypatch):
    def fail_factory(_model: Any) -> FakeAgent:
        raise AssertionError("approval must not call the agent")

    monkeypatch.setattr(cli, "create_requirement_inference_agent", fail_factory)
    _feed_input(monkeypatch, ["a"])

    draft = cli._phase_review_draft(_scope_draft(approved=False), RawChatModel())

    assert draft.approval_state is ApprovalState.APPROVED
    assert draft.inferred_scope == ["Claims inbox"]


def _priced_draft(hours: str | None) -> QuotationDraft:
    task = QuotationTask(category=WorkCategory.BACKEND, description="API", estimated_hours=hours)
    return approve_draft(_scope_draft().model_copy(update={"tasks": [task]}))


def test_pricing_returns_to_tasks_instead_of_crashing_when_hours_are_missing(capsys):
    assert cli._phase_pricing(_priced_draft(None)) is None
    assert "Cannot calculate the quote" in capsys.readouterr().out


@pytest.mark.parametrize(("answer", "accepted"), [("a", True), ("b", False)])
def test_pricing_accepts_or_goes_back_to_tasks(monkeypatch, answer, accepted):
    _feed_input(monkeypatch, [answer])

    result = cli._phase_pricing(_priced_draft("10"))

    assert isinstance(result, QuoteResult) is accepted
    assert (result is None) is not accepted


class FailingAgent:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, request: Any, config: Any = None) -> Any:
        self.calls += 1
        raise ValueError("tasks.3.estimated_hours Input should be greater than 0")


def test_task_revision_failure_keeps_previous_tasks_and_session(monkeypatch, capsys):
    devops_task = {"category": "devops", "description": "Docker setup", "estimated_hours": "4"}
    calls = {"devops": 0}
    failing = FailingAgent()

    def factory(_model: Any, *, category: WorkCategory) -> Any:
        if category is WorkCategory.DEVOPS:
            calls["devops"] += 1
            if calls["devops"] > 1:
                return failing
            return FakeAgent({"tasks": [devops_task]})
        return FakeAgent({"tasks": []})

    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["r", "4", "Docker setup takes 3 hours", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert failing.calls == 1
    assert "devops agent failed" in output
    assert "greater than 0" in output
    assert "previous tasks were kept" in output
    assert [(task.description, task.estimated_hours) for task in draft.tasks] == [
        ("Docker setup", 4)
    ]


def test_initial_decomposition_failure_leaves_category_empty_with_retry_hint(monkeypatch, capsys):
    backend_task = {"category": "backend", "description": "API", "estimated_hours": "5"}

    def factory(_model: Any, *, category: WorkCategory) -> Any:
        if category is WorkCategory.DEVOPS:
            return FailingAgent()
        if category is WorkCategory.BACKEND:
            return FakeAgent({"tasks": [backend_task]})
        return FakeAgent({"tasks": []})

    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert "devops agent failed" in output
    assert "use [r] to retry" in output
    assert [task.description for task in draft.tasks] == ["API"]


def test_task_revision_sends_the_task_numbers_shown_to_the_reviewer(monkeypatch):
    backend = {"category": "backend", "description": "API", "estimated_hours": "5"}
    devops = {"category": "devops", "description": "Docker setup", "estimated_hours": "4"}
    factory, agents = _decomposition_factory(
        {WorkCategory.BACKEND: [[backend]], WorkCategory.DEVOPS: [[devops], [devops]]}
    )
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["r", "4", "2. takes 3 hours", "a", "y"])

    cli._phase_decompose(_scope_draft(), RawChatModel())

    feedback = agents[WorkCategory.DEVOPS][1].requests[0]["messages"][2]["content"]
    assert "2. Docker setup (4h)" in feedback


def test_scope_revision_failure_keeps_previous_scope(monkeypatch, capsys):
    failing = FailingAgent()
    monkeypatch.setattr(cli, "create_requirement_inference_agent", lambda _model: failing)
    _feed_input(monkeypatch, ["r", "Add a dashboard", "a"])

    draft = cli._phase_review_draft(_scope_draft(approved=False), RawChatModel())

    assert failing.calls == 1
    assert "inference agent failed" in capsys.readouterr().out
    assert draft.inferred_scope == ["Claims inbox"]
    assert draft.approval_state is ApprovalState.APPROVED


def _task_payload(category: WorkCategory, description: str, hours: str) -> dict[str, Any]:
    return {"category": category.value, "description": description, "estimated_hours": hours}


def _one_task_per_category() -> dict[WorkCategory, list[list[dict[str, Any]]]]:
    return {
        category: [[_task_payload(category, f"{category.value} task", "2")]]
        for category in WorkCategory
    }


def test_global_revision_reruns_every_category_with_the_same_feedback(monkeypatch):
    responses = _one_task_per_category()
    for category in WorkCategory:
        responses[category].append([_task_payload(category, f"{category.value} revised", "3")])
    factory, agents = _decomposition_factory(responses)
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["g", "Add 1 hour to every task", "a"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    for number, category in enumerate(WorkCategory, start=1):
        assert len(agents[category]) == 2
        feedback = agents[category][1].requests[0]["messages"][2]["content"]
        assert "Add 1 hour to every task" in feedback
        assert f"{number}. {category.value} task (2h)" in feedback
    assert [(task.description, task.estimated_hours) for task in draft.tasks] == [
        (f"{category.value} revised", 3) for category in WorkCategory
    ]


def test_global_revision_keeps_a_failed_category_and_applies_the_rest(monkeypatch, capsys):
    calls = {category: 0 for category in WorkCategory}

    def factory(_model: Any, *, category: WorkCategory) -> Any:
        calls[category] += 1
        if calls[category] > 1 and category is WorkCategory.DEVOPS:
            return FailingAgent()
        if calls[category] > 1 and category is WorkCategory.BACKEND:
            return FakeAgent({"tasks": [_task_payload(category, "API v2", "9")]})
        return FakeAgent({"tasks": [_task_payload(category, f"{category.value} task", "2")]})

    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["g", "Rename the API", "a"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert all(count == 2 for count in calls.values())
    assert "devops agent failed" in output
    assert "previous devops tasks were kept" in output
    assert [task.description for task in draft.tasks] == [
        "planning_and_coordination task",
        "API v2",
        "frontend task",
        "devops task",
    ]


def test_category_menu_marks_empty_categories_and_can_fill_them(monkeypatch, capsys):
    responses = _one_task_per_category()
    kickoff = _task_payload(WorkCategory.PLANNING_AND_COORDINATION, "Kickoff", "1")
    responses[WorkCategory.PLANNING_AND_COORDINATION] = [[], [kickoff]]
    factory, _agents = _decomposition_factory(responses)
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["r", "1", "Add a kickoff meeting", "a"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert "1. planning_and_coordination (no tasks)" in output
    assert "2. backend\n" in output
    assert draft.tasks[0].description == "Kickoff"


def test_approval_with_empty_categories_requires_explicit_confirmation(monkeypatch, capsys):
    backend_task = _task_payload(WorkCategory.BACKEND, "API", "5")
    factory, _agents = _decomposition_factory({WorkCategory.BACKEND: [[backend_task]]})
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["a", "n", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    output = capsys.readouterr().out
    assert output.count("These categories have no tasks") == 2
    assert "planning_and_coordination, frontend, devops" in output
    assert draft.approval_state is ApprovalState.APPROVED
    assert [task.description for task in draft.tasks] == ["API"]


def test_approval_without_empty_categories_does_not_ask_for_confirmation(monkeypatch, capsys):
    factory, _agents = _decomposition_factory(_one_task_per_category())
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["a"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    assert "These categories have no tasks" not in capsys.readouterr().out
    assert draft.approval_state is ApprovalState.APPROVED


@pytest.mark.parametrize("raw", ["1e3", "1E2", "Infinity", "NaN", "0", "-2", "abc"])
def test_edit_hours_rejects_non_plain_numbers(monkeypatch, capsys, raw):
    backend_task = _task_payload(WorkCategory.BACKEND, "API", "5")
    factory, _agents = _decomposition_factory({WorkCategory.BACKEND: [[backend_task]]})
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    _feed_input(monkeypatch, ["e", "1", raw, "2,5", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    assert "Enter a positive number of hours" in capsys.readouterr().out
    assert [str(task.estimated_hours) for task in draft.tasks] == ["2.5"]


def test_edited_task_is_revalidated_as_a_quotation_task(monkeypatch):
    backend_task = _task_payload(WorkCategory.BACKEND, "API", "5")
    factory, _agents = _decomposition_factory({WorkCategory.BACKEND: [[backend_task]]})
    monkeypatch.setattr(cli, "create_decomposition_agent", factory)
    validated: list[Any] = []
    original = QuotationTask.model_validate

    def spy(data: Any, *args: Any, **kwargs: Any) -> QuotationTask:
        validated.append(data)
        return original(data, *args, **kwargs)

    monkeypatch.setattr(QuotationTask, "model_validate", spy)
    _feed_input(monkeypatch, ["e", "1", "8", "a", "y"])

    draft = cli._phase_decompose(_scope_draft(), RawChatModel())

    assert any(
        isinstance(data, dict) and str(data.get("estimated_hours")) == "8" for data in validated
    )
    assert [str(task.estimated_hours) for task in draft.tasks] == ["8"]


def test_agent_label_uses_the_reporter_separator():
    model = RawChatModel()
    model.model_name = "gpt-4o-mini"
    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")

    assert cli._agent_label("Agent", model, ProgressReporter(stream=ascii_stream)) == (
        "Agent | gpt-4o-mini"
    )
    assert cli._agent_label("Agent", model, ProgressReporter(stream=io.StringIO())) == (
        "Agent · gpt-4o-mini"
    )


COMMERCIAL_RESPONSE = {
    "project_understanding": {
        "summary": "Claims inbox for the support team.",
        "components": [{"title": "Claims inbox", "description": "Track client claims"}],
    },
    "task_groups": [{"name": "Claims inbox", "task_numbers": [1]}],
    "budget_scope": {"includes": ["Backend"], "excludes": ["Hosting"]},
    "payment_schedule": [
        {"milestone_label": "Single payment", "amount": 420.00, "condition": "on delivery of $420"}
    ],
    "deliverables": [{"name": "Deliverable 1", "content": "Source code"}],
}


def test_generate_runs_the_tracked_commercial_agent_and_writes_both_documents(
    monkeypatch, capsys, tmp_path
):
    task = QuotationTask(category=WorkCategory.BACKEND, description="API", estimated_hours="14")
    draft = approve_draft(_scope_draft().model_copy(update={"tasks": [task]}))
    quote = cli.calculate_quote(draft)
    agent = FakeAgent(COMMERCIAL_RESPONSE)
    built_with: list[Any] = []

    def factory(model: Any) -> FakeAgent:
        built_with.append(model)
        return agent

    monkeypatch.setattr(cli, "create_commercial_synthesis_agent", factory)
    model = RawChatModel()

    cli._phase_generate(draft, quote, tmp_path, "es", model, "Claims module", "Daniel Calcina")

    output = capsys.readouterr().out
    assert built_with == [model]
    assert len(agent.requests) == 1
    assert agent.configs[0] is not None and agent.configs[0]["callbacks"]
    assert "✔ Commercial synthesis agent" in output
    assert "Currency corrected to soles (S/.):" in output
    assert "'on delivery of $420' -> 'on delivery of S/. 420'" in output
    assert (tmp_path / "quotation-internal.docx").is_file()
    assert (tmp_path / "quotation-commercial.docx").is_file()
