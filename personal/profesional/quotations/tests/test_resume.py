from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quotation_agents import workspace_cli
from quotation_agents.models import QuotationDraft, QuotationTask, WorkCategory
from quotation_agents.pricing import calculate_quote
from quotation_agents.profile import PROFILE_TEMPLATE
from quotation_agents.state import Phase, load_state, save_state
from quotation_agents.workflow import approve_draft, revise_draft
from quotation_agents.workspace import create_workspace

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
TASKS = [
    QuotationTask(category=WorkCategory.BACKEND, description="API", estimated_hours=Decimal("10")),
    QuotationTask(category=WorkCategory.FRONTEND, description="UI", estimated_hours=Decimal("8")),
]


class FakeAgent:
    def __init__(self, structured_response):
        self.structured_response = structured_response
        self.requests = []

    def invoke(self, request, config=None):
        self.requests.append(request)
        return {"structured_response": self.structured_response}


def _feed_input(monkeypatch, answers):
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_args: next(iterator))


def _plain(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def pending_draft() -> QuotationDraft:
    return QuotationDraft(
        client_company="Cableclub",
        original_request="Campaign system",
        inferred_scope=["Campaign inbox", "Reports"],
    )


def approved_with_tasks() -> QuotationDraft:
    return approve_draft(revise_draft(approve_draft(pending_draft()), tasks=TASKS))


class Recorder:
    """Fake interactive phases that record how they were called."""

    def __init__(self, monkeypatch):
        self.calls: list[str] = []
        self.docs = None
        self.revisions: list[tuple[WorkCategory, str, list[QuotationTask]]] = []
        self.pricing_answers: list[bool] = []
        self.digest_calls = 0
        recorder = self

        def digest_factory(_model):
            class Agent:
                def invoke(self, request, config=None):
                    recorder.digest_calls += 1
                    return {"structured_response": {"summary": "Digest"}}

            return Agent()

        def ask_intake():
            recorder.calls.append("ask_intake")
            return "Cableclub", "Campaign system"

        def intake(client, request, model, docs, progress):
            recorder.calls.append("intake")
            recorder.docs = docs
            return pending_draft()

        def review_draft(draft, model, docs, progress):
            recorder.calls.append("scope")
            return approve_draft(draft)

        def decompose(scope, model, docs, progress):
            recorder.calls.append("decompose")
            return approve_draft(revise_draft(scope, tasks=TASKS))

        def review_tasks(scope, tasks, model, docs=(), progress=None):
            recorder.calls.append("review_tasks")
            return approve_draft(revise_draft(scope, tasks=tasks))

        def revise_category(scope, tasks, category, feedback, model, docs, progress, **_kw):
            recorder.revisions.append((category, feedback, list(tasks)))
            return [task for task in tasks if task.category is category]

        def pricing(draft):
            recorder.calls.append("pricing")
            if recorder.pricing_answers and not recorder.pricing_answers.pop(0):
                return None
            return calculate_quote(draft)

        def generate(draft, quote, output_dir, language, model, project_name, provider, progress):
            recorder.calls.append("generate")
            recorder.project_name = project_name
            internal = b"internal " + project_name.encode()
            (output_dir / "quotation-internal.docx").write_bytes(internal)
            (output_dir / "quotation-commercial.docx").write_bytes(b"commercial")

        monkeypatch.setattr(workspace_cli, "create_digest_agent", digest_factory)
        monkeypatch.setattr(workspace_cli, "_ask_intake", ask_intake)
        monkeypatch.setattr(workspace_cli, "_infer_intake", intake)
        monkeypatch.setattr(workspace_cli, "_phase_review_draft", review_draft)
        monkeypatch.setattr(workspace_cli, "_phase_decompose", decompose)
        monkeypatch.setattr(workspace_cli, "_review_tasks", review_tasks)
        monkeypatch.setattr(workspace_cli, "_revise_category", revise_category)
        monkeypatch.setattr(workspace_cli, "_phase_pricing", pricing)
        monkeypatch.setattr(workspace_cli, "_phase_generate", generate)


def _resume(root, slug="crm", project_name=None):
    workspace_cli.cmd_resume(
        slug,
        root,
        lambda: object(),
        language="es",
        provider_name="Daniel",
        project_name=project_name,
        now=lambda: NOW,
    )


@pytest.fixture
def paths(tmp_path):
    return create_workspace(tmp_path, "CRM Cableclub", "crm", PROFILE_TEMPLATE, NOW)


def _set_state(paths, **changes):
    state = load_state(paths.state)
    save_state(paths.state, state.model_copy(update=changes))


def test_resume_runs_from_intake_to_generated_v1(monkeypatch, paths):
    recorder = Recorder(monkeypatch)
    (paths.documentations / "a.md").write_text("Draft", encoding="utf-8")

    _resume(paths.root.parent)

    version = paths.output / "v1"
    assert (version / "quotation-internal.docx").is_file()
    assert (version / "quotation-commercial.docx").is_file()
    snapshot = json.loads((version / "snapshot.json").read_text(encoding="utf-8"))
    assert len(snapshot["draft"]["tasks"]) == 2
    assert snapshot["quote"]["selected_amount"]
    state = load_state(paths.state)
    assert state.phase is Phase.GENERATED
    assert [version.number for version in state.versions] == [1]
    assert recorder.project_name == "CRM Cableclub"
    assert [document.name for document in recorder.docs] == [
        "developer_profile.md",
        "a.md (digest)",
    ]
    notes = paths.notes.read_text(encoding="utf-8")
    for expected in ("Session 1", "a.md: Digest", "Scope approved (2 items).",
                     "Tasks approved: 2 tasks, 18 h.", "Generated v1: S/ "):
        assert expected in notes


def test_resume_quit_during_task_review_keeps_approved_scope(monkeypatch, paths):
    recorder = Recorder(monkeypatch)

    def quit_decompose(*_args):
        recorder.calls.append("decompose")
        raise SystemExit(0)

    monkeypatch.setattr(workspace_cli, "_phase_decompose", quit_decompose)

    with pytest.raises(SystemExit):
        _resume(paths.root.parent)

    state = load_state(paths.state)
    assert state.phase is Phase.DECOMPOSITION
    assert state.draft.approval_state == "approved"

    recorder.calls.clear()
    _feed_input(monkeypatch, ["c"])
    with pytest.raises(SystemExit):
        _resume(paths.root.parent)

    assert recorder.calls == ["decompose"]


def test_resume_does_not_redigest_unchanged_documents(monkeypatch, paths):
    recorder = Recorder(monkeypatch)
    (paths.documentations / "a.md").write_text("Draft", encoding="utf-8")
    _resume(paths.root.parent)

    _feed_input(monkeypatch, ["q"])
    _resume(paths.root.parent)

    assert recorder.digest_calls == 1
    assert load_state(paths.state).session_count == 2


def test_resume_new_document_after_scope_offers_reopen(monkeypatch, paths):
    recorder = Recorder(monkeypatch)
    _set_state(paths, phase=Phase.PRICING, draft=approved_with_tasks())
    (paths.documentations / "new.md").write_text("New draft", encoding="utf-8")
    _feed_input(monkeypatch, ["y"])

    _resume(paths.root.parent)

    assert recorder.calls[:2] == ["scope", "review_tasks"]
    assert [category for category, _f, _t in recorder.revisions] == list(WorkCategory)
    assert all(
        feedback == workspace_cli.SCOPE_CHANGED_FEEDBACK for _c, feedback, _t in recorder.revisions
    )
    assert all(tasks == TASKS for _c, _f, tasks in recorder.revisions)
    state = load_state(paths.state)
    assert state.phase is Phase.GENERATED
    assert state.revise_tasks_for_new_scope is False


def test_regenerate_creates_v2_and_keeps_v1(monkeypatch, paths):
    Recorder(monkeypatch)
    _resume(paths.root.parent)
    v1 = (paths.output / "v1" / "quotation-internal.docx").read_bytes()

    _feed_input(monkeypatch, ["p"])
    _resume(paths.root.parent, project_name="Renamed")

    assert (paths.output / "v1" / "quotation-internal.docx").read_bytes() == v1
    assert (paths.output / "v2" / "quotation-internal.docx").read_bytes() == b"internal Renamed"
    assert [version.number for version in load_state(paths.state).versions] == [1, 2]


def test_pricing_back_returns_to_tasks_and_recalculates(monkeypatch, paths):
    recorder = Recorder(monkeypatch)
    recorder.pricing_answers = [False, True]
    _set_state(paths, phase=Phase.PRICING, draft=approved_with_tasks())
    _feed_input(monkeypatch, ["c"])

    _resume(paths.root.parent)

    assert recorder.calls == ["pricing", "review_tasks", "pricing", "generate"]
    assert load_state(paths.state).phase is Phase.GENERATED


def test_resume_without_slug_picks_from_list(monkeypatch, tmp_path, capsys):
    create_workspace(tmp_path, "Old", "old", PROFILE_TEMPLATE, NOW)
    newer = create_workspace(tmp_path, "New", "new", PROFILE_TEMPLATE, NOW.replace(day=15))
    recorder = Recorder(monkeypatch)

    def quit_intake(*_args):
        recorder.calls.append("intake")
        raise SystemExit(0)

    monkeypatch.setattr(workspace_cli, "_infer_intake", quit_intake)
    _feed_input(monkeypatch, ["9", "1"])

    with pytest.raises(SystemExit):
        _resume(tmp_path, slug=None)

    assert load_state(newer.state).session_count == 1
    assert "1. new" in _plain(capsys.readouterr().out)


def test_next_version_number_ignores_non_version_folders(tmp_path):
    for name in ("v1", "v3", "notes", "vX"):
        (tmp_path / name).mkdir()
    (tmp_path / "v9").write_text("file", encoding="utf-8")

    assert workspace_cli.next_version_number(tmp_path) == 4
    assert workspace_cli.next_version_number(tmp_path / "missing") == 1


def test_resume_invalid_state_exits_with_message(paths, capsys):
    paths.state.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        _resume(paths.root.parent)

    assert exit_info.value.code == 1
    assert "state.json" in capsys.readouterr().out


def test_resume_unknown_workspace_exits_with_message(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _resume(tmp_path, slug="missing")

    assert exit_info.value.code == 1
    assert "Workspace not found" in capsys.readouterr().out


def test_reopened_scope_approval_survives_quit_during_task_revision(monkeypatch, paths):
    recorder = Recorder(monkeypatch)
    _set_state(paths, phase=Phase.PRICING, draft=approved_with_tasks())
    original_revise = workspace_cli._revise_category

    def quit_revise(*_args, **_kwargs):
        raise SystemExit(0)

    monkeypatch.setattr(workspace_cli, "_revise_category", quit_revise)
    _feed_input(monkeypatch, ["s"])

    with pytest.raises(SystemExit):
        _resume(paths.root.parent)

    state = load_state(paths.state)
    assert state.phase is Phase.DECOMPOSITION
    assert state.draft.approval_state == "approved"
    assert state.revise_tasks_for_new_scope is True

    monkeypatch.setattr(workspace_cli, "_revise_category", original_revise)
    recorder.calls.clear()
    _feed_input(monkeypatch, ["c"])
    _resume(paths.root.parent)

    assert recorder.calls[:2] == ["review_tasks", "pricing"]
    assert [category for category, _f, _t in recorder.revisions] == list(WorkCategory)
    assert load_state(paths.state).revise_tasks_for_new_scope is False


def test_intake_answers_survive_inference_failure(monkeypatch, paths, capsys):
    recorder = Recorder(monkeypatch)

    def failing_intake(*_args):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(workspace_cli, "_infer_intake", failing_intake)

    with pytest.raises(SystemExit) as exit_info:
        _resume(paths.root.parent)

    assert exit_info.value.code == 1
    assert "provider timeout" in capsys.readouterr().out
    state = load_state(paths.state)
    assert state.phase is Phase.INTAKE
    assert (state.client_company, state.original_request) == ("Cableclub", "Campaign system")

    monkeypatch.setattr(workspace_cli, "_infer_intake", lambda *a: pending_draft())
    recorder.calls.clear()
    _resume(paths.root.parent)

    assert "ask_intake" not in recorder.calls
    assert load_state(paths.state).phase is Phase.GENERATED
