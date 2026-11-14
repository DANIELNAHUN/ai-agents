from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quotation_agents.ingestion import (
    IngestionError,
    context_documents,
    digest_document,
    ingest_documents,
)
from quotation_agents.attachments import SourceDocument
from quotation_agents.profile import PROFILE_TEMPLATE
from quotation_agents.state import DocumentDigest, load_state
from quotation_agents.workspace import create_workspace

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


class CountingDigest:
    def __init__(self, fail_names=()):
        self.calls: list[str] = []
        self.fail_names = set(fail_names)

    def __call__(self, document: SourceDocument) -> DocumentDigest:
        self.calls.append(document.name)
        if document.name in self.fail_names:
            self.fail_names.discard(document.name)
            raise RuntimeError("provider down")
        return DocumentDigest(summary=f"summary of {document.text}", technologies=["n8n"])


@pytest.fixture
def workspace(tmp_path):
    paths = create_workspace(tmp_path, "CRM", "crm", PROFILE_TEMPLATE, NOW)
    return paths, load_state(paths.state)


def test_ingest_new_file_records_digest(workspace):
    paths, state = workspace
    (paths.documentations / "a.md").write_text("draft A", encoding="utf-8")

    state, result = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)

    assert result.added == ["a.md"]
    assert result.has_new_content
    assert state.documents[0].status == "active"
    assert state.documents[0].digest.summary == "summary of draft A"


def test_ingest_unchanged_file_not_redigested(workspace):
    paths, state = workspace
    (paths.documentations / "a.md").write_text("draft A", encoding="utf-8")
    digest = CountingDigest()
    state, _ = ingest_documents(paths, state, digest=digest, now=NOW)

    state, result = ingest_documents(paths, state, digest=digest, now=NOW)

    assert digest.calls == ["a.md"]
    assert result.has_new_content is False


def test_ingest_changed_file_replaces_digest(workspace):
    paths, state = workspace
    file = paths.documentations / "a.md"
    file.write_text("draft A", encoding="utf-8")
    state, _ = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)
    file.write_text("draft A v2", encoding="utf-8")

    state, result = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)

    assert result.changed == ["a.md"]
    assert len(state.documents) == 1
    assert state.documents[0].digest.summary == "summary of draft A v2"


def test_ingest_removed_file_marked_removed(workspace):
    paths, state = workspace
    file = paths.documentations / "a.md"
    file.write_text("draft A", encoding="utf-8")
    state, _ = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)
    file.unlink()

    state, result = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)

    assert result.removed == ["a.md"]
    assert state.documents[0].status == "removed"


def test_ingest_skips_lock_and_hidden_files(workspace):
    paths, state = workspace
    (paths.documentations / "~$a.docx").write_bytes(b"lock")
    (paths.documentations / ".DS_Store").write_bytes(b"x")
    (paths.documentations / "nested").mkdir()

    state, result = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)

    assert state.documents == []
    assert result.unreadable == []


def test_ingest_unsupported_file_recorded_unreadable(workspace):
    paths, state = workspace
    (paths.documentations / "img.png").write_bytes(b"\x89PNG")
    digest = CountingDigest()

    state, result = ingest_documents(paths, state, digest=digest, now=NOW)
    state, second = ingest_documents(paths, state, digest=digest, now=NOW)

    assert result.unreadable[0][0] == "img.png"
    assert state.documents[0].status == "unreadable"
    assert second.unreadable == []
    assert digest.calls == []


def test_ingest_digest_failure_is_retried_next_time(workspace):
    paths, state = workspace
    (paths.documentations / "a.md").write_text("A", encoding="utf-8")
    (paths.documentations / "b.md").write_text("B", encoding="utf-8")
    digest = CountingDigest(fail_names={"b.md"})

    state, result = ingest_documents(paths, state, digest=digest, now=NOW)

    assert [name for name, _error in result.failed] == ["b.md"]
    assert [record.name for record in state.documents] == ["a.md"]

    state, result = ingest_documents(paths, state, digest=digest, now=NOW)

    assert result.added == ["b.md"]
    assert {record.name for record in state.documents} == {"a.md", "b.md"}


def test_context_documents_profile_first_and_skips_removed(workspace):
    paths, state = workspace
    (paths.documentations / "a.md").write_text("A", encoding="utf-8")
    (paths.documentations / "b.md").write_text("B", encoding="utf-8")
    state, _ = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)
    (paths.documentations / "b.md").unlink()
    state, _ = ingest_documents(paths, state, digest=CountingDigest(), now=NOW)

    documents = context_documents(state, PROFILE_TEMPLATE)

    assert [document.name for document in documents] == ["developer_profile.md", "a.md (digest)"]
    assert "summary of A" in documents[1].text


def test_digest_document_sends_document_as_data():
    class Agent:
        def __init__(self):
            self.requests = []

        def invoke(self, request, config=None):
            self.requests.append(request)
            return {"structured_response": {"summary": "S"}}

    agent = Agent()

    digest = digest_document(SourceDocument(name="a.md", text="Draft body"), agent=agent)

    assert digest.summary == "S"
    assert "Draft body" in agent.requests[0]["messages"][-1]["content"]


def test_digest_document_invalid_response_raises():
    with pytest.raises(IngestionError):
        digest_document(SourceDocument(name="a.md", text="x"), agent=lambda request: {})
