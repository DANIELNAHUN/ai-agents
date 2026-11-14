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
