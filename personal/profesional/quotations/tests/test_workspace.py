from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quotation_agents.profile import PROFILE_TEMPLATE, load_profile
from quotation_agents.state import Phase, load_state, save_state
from quotation_agents.workspace import (
    DEFAULT_ROOT,
    PACKAGE_ROOT,
    WorkspaceError,
    create_workspace,
    list_workspaces,
    open_workspace,
    resolve_root,
    slugify,
    suggest_slug,
    unique_slug,
)

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


class FakeAgent:
    def __init__(self, structured_response):
        self.structured_response = structured_response
        self.requests = []

    def invoke(self, request, config=None):
        self.requests.append(request)
        return {"structured_response": self.structured_response}


def test_resolve_root_precedence(tmp_path):
    env = {"QUOTATION_WORKSPACES": str(tmp_path / "env")}

    assert resolve_root(tmp_path / "cli", env) == tmp_path / "cli"
    assert resolve_root(None, env) == tmp_path / "env"
    assert resolve_root(None, {}) == DEFAULT_ROOT
    assert DEFAULT_ROOT.parent.name == "quotations"


def test_slugify():
    assert slugify("Sistema de Campañas Cableclub") == "sistema-de-campanas-cableclub"
    assert slugify("¿¿??") == ""


def test_unique_slug_appends_suffix(tmp_path):
    (tmp_path / "crm").mkdir()
    assert unique_slug(tmp_path, "crm") == "crm-2"
    (tmp_path / "crm-2").mkdir()
    assert unique_slug(tmp_path, "crm") == "crm-3"
    assert unique_slug(tmp_path, "other") == "other"


def test_suggest_slug_uses_agent_and_truncates():
    agent = FakeAgent({"slug": "CRM Cableclub Campaigns"})

    slug = suggest_slug("A very long quotation name " * 3, agent=agent)

    assert slug == "crm-cableclub-campaigns"
    assert "A very long quotation name" in agent.requests[0]["messages"][-1]["content"]


def test_suggest_slug_caps_length():
    agent = FakeAgent({"slug": "word " * 20})

    assert len(suggest_slug("x", agent=agent)) <= 40


def test_create_workspace_layout(tmp_path):
    paths = create_workspace(tmp_path, "CRM Cableclub", "crm-cableclub", PROFILE_TEMPLATE, NOW)

    assert paths.root == tmp_path / "crm-cableclub"
    assert paths.documentations.is_dir()
    assert paths.output.is_dir()
    assert load_profile(paths.profile) == PROFILE_TEMPLATE
    assert paths.notes.read_text(encoding="utf-8").startswith("# Quotation notes — CRM Cableclub")
    state = load_state(paths.state)
    assert state.phase is Phase.INTAKE
    assert state.name == "CRM Cableclub"


def test_create_workspace_rejects_reserved_and_existing(tmp_path):
    with pytest.raises(WorkspaceError):
        create_workspace(tmp_path, "Profile", "_profile", PROFILE_TEMPLATE, NOW)
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    with pytest.raises(WorkspaceError):
        create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)


def test_list_workspaces_reports_invalid_state(tmp_path):
    older = create_workspace(tmp_path, "Old", "old", PROFILE_TEMPLATE, NOW)
    newer = create_workspace(tmp_path, "New", "new", PROFILE_TEMPLATE, NOW)
    state = load_state(newer.state)
    save_state(newer.state, state.model_copy(update={"updated_at": NOW + timedelta(days=1)}))
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "state.json").write_text("{", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    (tmp_path / "_profile").mkdir()
    (tmp_path / ".hidden").mkdir()

    summaries = list_workspaces(tmp_path)

    assert [summary.slug for summary in summaries[:2]] == ["new", "old"]
    assert summaries[0].name == "New"
    assert summaries[0].phase is Phase.INTAKE
    assert {summary.slug for summary in summaries[2:]} == {"broken", "empty"}
    assert all(summary.error for summary in summaries[2:])
    assert older.root.exists()


def test_list_workspaces_missing_root_is_empty(tmp_path):
    assert list_workspaces(tmp_path / "missing") == []


def test_open_workspace_requires_state(tmp_path):
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    (tmp_path / "empty").mkdir()

    assert open_workspace(tmp_path, "crm").root == tmp_path / "crm"
    with pytest.raises(WorkspaceError):
        open_workspace(tmp_path, "empty")
    with pytest.raises(WorkspaceError):
        open_workspace(tmp_path, "missing")


def test_gitignore_ignores_quotes():
    lines = (PACKAGE_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "quotes/" in lines
