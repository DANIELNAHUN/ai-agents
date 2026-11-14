from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quotation_agents.models import ApprovalState, QuotationDraft, QuotationTask, WorkCategory
from quotation_agents.pricing import calculate_quote
from quotation_agents.state import (
    DocumentDigest,
    DocumentRecord,
    GeneratedVersion,
    Phase,
    StateError,
    WorkspaceState,
    load_state,
    reopen,
    save_state,
)

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def approved_draft_with_tasks() -> QuotationDraft:
    return QuotationDraft(
        client_company="Cableclub",
        original_request="Campaign system",
        inferred_scope=["Campaign inbox"],
        tasks=[
            QuotationTask(
                category=WorkCategory.BACKEND,
                description="API",
                estimated_hours=Decimal("10"),
            ),
            QuotationTask(
                category=WorkCategory.FRONTEND,
                description="UI",
                estimated_hours=Decimal("8"),
            ),
        ],
        approval_state=ApprovalState.APPROVED,
    )


def full_state() -> WorkspaceState:
    draft = approved_draft_with_tasks()
    return WorkspaceState(
        name="Sistema de Campañas",
        slug="sistema-de-campanas",
        created_at=NOW,
        updated_at=NOW,
        phase=Phase.GENERATED,
        session_count=2,
        draft=draft,
        quote=calculate_quote(draft),
        documents=[
            DocumentRecord(
                name="a.md",
                sha256="0" * 64,
                status="active",
                digest=DocumentDigest(
                    summary="Draft",
                    requirements=["Inbox"],
                    constraints=[],
                    open_questions=[],
                    technologies=["n8n"],
                ),
                updated_at=NOW,
            )
        ],
        versions=[
            GeneratedVersion(number=1, created_at=NOW, total=Decimal("540.00"), path="output/v1")
        ],
    )


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = full_state()

    save_state(path, state)

    assert load_state(path) == state


def test_load_state_invalid_json_names_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(StateError, match="state.json"):
        load_state(path)


def test_load_state_invalid_field_names_field(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, full_state())
    path.write_text(
        path.read_text(encoding="utf-8").replace('"generated"', '"nope"'), encoding="utf-8"
    )

    with pytest.raises(StateError, match="phase"):
        load_state(path)


def test_load_state_missing_file_names_file(tmp_path):
    with pytest.raises(StateError, match="state.json"):
        load_state(tmp_path / "state.json")


def test_save_state_leaves_no_tmp_file(tmp_path):
    save_state(tmp_path / "state.json", full_state())

    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_reopen_scope_keeps_tasks_and_clears_quote():
    reopened = reopen(full_state(), Phase.SCOPE_REVIEW)

    assert reopened.phase is Phase.SCOPE_REVIEW
    assert reopened.draft.approval_state is ApprovalState.PENDING
    assert len(reopened.draft.tasks) == 2
    assert reopened.quote is None
    assert reopened.revise_tasks_for_new_scope is True


def test_reopen_decomposition_keeps_scope_approved():
    reopened = reopen(full_state(), Phase.DECOMPOSITION)

    assert reopened.phase is Phase.DECOMPOSITION
    assert reopened.draft.approval_state is ApprovalState.APPROVED
    assert reopened.quote is None
    assert reopened.revise_tasks_for_new_scope is False


def test_load_state_non_utf8_names_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes('{"name": "café"}'.encode("latin-1"))

    with pytest.raises(StateError, match="state.json"):
        load_state(path)


def test_load_state_rejects_naive_datetime(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, full_state())
    text = path.read_text(encoding="utf-8")
    naive = text.replace('"2026-11-14T10:00:00Z"', '"2026-11-14T10:00:00"', 1)
    path.write_text(naive, encoding="utf-8")

    with pytest.raises(StateError, match="created_at"):
        load_state(path)


def test_load_state_requires_draft_after_intake(tmp_path):
    path = tmp_path / "state.json"
    state = WorkspaceState(name="X", slug="x", created_at=NOW, updated_at=NOW)
    save_state(path, state)
    data = path.read_text(encoding="utf-8").replace('"intake"', '"decomposition"')
    path.write_text(data, encoding="utf-8")

    with pytest.raises(StateError, match="draft"):
        load_state(path)
