from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from quotation_agents import workspace_cli
from quotation_agents.profile import PROFILE_TEMPLATE, load_profile, save_profile
from quotation_agents.workspace import base_profile_path, create_workspace

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


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


def _no_model():
    raise AssertionError("the model must not be created")


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_no_subcommand_prints_help(capsys):
    with pytest.raises(SystemExit) as exit_info:
        workspace_cli.main([])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "setup" in output
    assert "resume" in output


def test_attachment_flag_removed():
    with pytest.raises(SystemExit) as exit_info:
        workspace_cli.main(["resume", "--attachment", "x"])

    assert exit_info.value.code == 2


def test_setup_short_name_creates_workspace_without_model(monkeypatch, tmp_path):
    _feed_input(monkeypatch, ["", "n", "n"])

    paths = workspace_cli.cmd_setup("CRM Cableclub", tmp_path, _no_model, now=lambda: NOW)

    assert paths.root == tmp_path / "crm-cableclub"
    assert paths.state.is_file()
    assert not base_profile_path(tmp_path).exists()
    assert load_profile(paths.profile) == PROFILE_TEMPLATE


def test_setup_creates_base_profile_from_template_on_request(monkeypatch, tmp_path):
    _feed_input(monkeypatch, ["", "y", "n"])

    workspace_cli.cmd_setup("CRM", tmp_path, _no_model, now=lambda: NOW)

    assert load_profile(base_profile_path(tmp_path)) == PROFILE_TEMPLATE


def test_setup_long_name_uses_slug_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        workspace_cli, "create_slug_agent", lambda _model: FakeAgent({"slug": "crm campaigns"})
    )
    _feed_input(monkeypatch, ["", "n", "n"])
    name = "Sistema integral de gestion de campanas para Cableclub con reportes"

    paths = workspace_cli.cmd_setup(name, tmp_path, lambda: object(), now=lambda: NOW)

    assert paths.root.name == "crm-campaigns"


def test_setup_long_name_falls_back_when_slug_agent_fails(monkeypatch, tmp_path):
    def failing_factory(_model):
        raise RuntimeError("provider down")

    monkeypatch.setattr(workspace_cli, "create_slug_agent", failing_factory)
    _feed_input(monkeypatch, ["", "n", "n"])
    name = "Sistema integral de gestion de campanas para Cableclub con reportes"

    paths = workspace_cli.cmd_setup(name, tmp_path, lambda: object(), now=lambda: NOW)

    assert len(paths.root.name) <= 40
    assert paths.root.name.startswith("sistema-integral")


def test_setup_profile_adjustment_writes_project_copy_only(monkeypatch, tmp_path):
    save_profile(base_profile_path(tmp_path), PROFILE_TEMPLATE)
    edits = [
        {"field": "tools", "action": "add", "value": "n8n", "reason": "uses n8n"},
        {"field": "stack", "action": "add", "value": "Vue", "reason": "client wants Vue"},
    ]
    monkeypatch.setattr(
        workspace_cli, "create_profile_edit_agent", lambda _model: FakeAgent({"edits": edits})
    )
    _feed_input(monkeypatch, ["", "y", "We use n8n here", "y", "n"])

    paths = workspace_cli.cmd_setup("CRM", tmp_path, lambda: object(), now=lambda: NOW)

    project = load_profile(paths.profile)
    assert "n8n" in project.tools
    assert "Vue" not in project.stack
    assert load_profile(base_profile_path(tmp_path)) == PROFILE_TEMPLATE
    assert "Project profile adjusted: tools add n8n" in paths.notes.read_text(encoding="utf-8")


def test_setup_reasks_when_name_slugifies_empty(monkeypatch, tmp_path):
    _feed_input(monkeypatch, ["CRM", "", "n", "n"])

    paths = workspace_cli.cmd_setup("¿¿??", tmp_path, _no_model, now=lambda: NOW)

    assert paths.root.name == "crm"


def test_setup_collision_gets_suffix(monkeypatch, tmp_path):
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    _feed_input(monkeypatch, ["", "n", "n"])

    paths = workspace_cli.cmd_setup("CRM", tmp_path, _no_model, now=lambda: NOW)

    assert paths.root.name == "crm-2"


def test_list_shows_invalid_workspace(tmp_path, capsys):
    create_workspace(tmp_path, "CRM Cableclub", "crm-cableclub", PROFILE_TEMPLATE, NOW)
    (tmp_path / "broken").mkdir()

    workspace_cli.cmd_list(tmp_path)

    output = _plain(capsys.readouterr().out)
    assert "crm-cableclub" in output
    assert "CRM Cableclub" in output
    assert "intake" in output
    assert "broken" in output
    assert "invalid: missing state.json" in output


def test_list_empty_root_hint(tmp_path, capsys):
    workspace_cli.cmd_list(tmp_path)

    assert 'uv run quotation setup "<name>"' in capsys.readouterr().out
