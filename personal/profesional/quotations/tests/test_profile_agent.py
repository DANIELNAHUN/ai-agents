from __future__ import annotations

import pytest

from quotation_agents.profile import PROFILE_TEMPLATE, ProfileEdit
from quotation_agents.profile_agent import ProfileAgentError, propose_profile_edits


class FakeAgent:
    def __init__(self, structured_response):
        self.structured_response = structured_response
        self.requests = []

    def invoke(self, request, config=None):
        self.requests.append(request)
        return {"structured_response": self.structured_response}


N8N_EDIT = {"field": "tools", "action": "add", "value": "n8n", "reason": "User adopted n8n"}


def test_propose_profile_edits_returns_edits():
    agent = FakeAgent({"edits": [N8N_EDIT]})

    edits = propose_profile_edits(PROFILE_TEMPLATE, "I now use n8n", agent=agent)

    assert edits == [ProfileEdit(**N8N_EDIT)]


def test_propose_profile_edits_sends_profile_and_request():
    agent = FakeAgent({"edits": []})

    propose_profile_edits(PROFILE_TEMPLATE, "I now use n8n", agent=agent)

    content = agent.requests[0]["messages"][-1]["content"]
    assert "I now use n8n" in content
    assert "React" in content


def test_propose_profile_edits_invalid_response_raises():
    agent = FakeAgent({"edits": [{"field": "salary", "action": "add", "value": "1"}]})

    with pytest.raises(ProfileAgentError):
        propose_profile_edits(PROFILE_TEMPLATE, "x", agent=agent)


# --- Learned suggestions -----------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from quotation_agents.profile_agent import (  # noqa: E402
    LearnedIndex,
    LearnedRecord,
    ProfileSuggestion,
    collect_learning_sources,
    load_learned_index,
    mark_reviewed,
    save_learned_index,
    suggest_from_quotations,
)
from quotation_agents.workspace import create_workspace  # noqa: E402

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _suggestion(field, value, evidence=("crm",)):
    return {"field": field, "value": value, "evidence": list(evidence)}


def test_collect_learning_sources_skips_unchanged_fingerprint(tmp_path):
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    sources = collect_learning_sources(tmp_path, LearnedIndex())
    index = mark_reviewed(LearnedIndex(), sources, [])

    assert [source.slug for source in sources] == ["crm"]
    assert collect_learning_sources(tmp_path, index) == []


def test_collect_learning_sources_includes_changed_notes(tmp_path):
    paths = create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    index = mark_reviewed(LearnedIndex(), collect_learning_sources(tmp_path, LearnedIndex()), [])
    with paths.notes.open("a", encoding="utf-8") as handle:
        handle.write("- uses Supabase\n")

    sources = collect_learning_sources(tmp_path, index)

    assert [source.slug for source in sources] == ["crm"]
    assert "Supabase" in sources[0].notes


def test_suggest_filters_existing_and_already_shown(tmp_path):
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    sources = collect_learning_sources(tmp_path, LearnedIndex())
    profile = PROFILE_TEMPLATE.model_copy(update={"tools": ["GitHub", "n8n"]})
    record = LearnedRecord(fingerprint="x", shown=["tools:clickup"])
    index = LearnedIndex(workspaces={"old": record})
    agent = FakeAgent(
        {
            "suggestions": [
                _suggestion("tools", "N8N"),
                _suggestion("tools", "ClickUp"),
                _suggestion("stack", "Supabase"),
            ]
        }
    )

    suggestions = suggest_from_quotations(profile, sources, index, agent=agent)

    assert suggestions == [ProfileSuggestion(field="stack", value="Supabase", evidence=["crm"])]
    assert "crm" in agent.requests[0]["messages"][-1]["content"]


def test_suggest_drops_unknown_evidence_slugs(tmp_path):
    create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    sources = collect_learning_sources(tmp_path, LearnedIndex())
    agent = FakeAgent(
        {
            "suggestions": [
                _suggestion("stack", "Supabase", evidence=("crm", "ghost")),
                _suggestion("stack", "Rust", evidence=("ghost",)),
            ]
        }
    )

    suggestions = suggest_from_quotations(PROFILE_TEMPLATE, sources, LearnedIndex(), agent=agent)

    assert suggestions == [ProfileSuggestion(field="stack", value="Supabase", evidence=["crm"])]


def test_learned_index_round_trip_and_invalid_names_file(tmp_path):
    path = tmp_path / "learned.json"
    index = LearnedIndex(workspaces={"crm": LearnedRecord(fingerprint="f", shown=["stack:rust"])})

    save_learned_index(path, index)

    assert load_learned_index(path) == index
    assert load_learned_index(tmp_path / "missing.json") == LearnedIndex()
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ProfileAgentError, match="learned.json"):
        load_learned_index(path)
