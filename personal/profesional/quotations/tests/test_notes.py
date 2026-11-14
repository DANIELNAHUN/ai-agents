from __future__ import annotations

from datetime import date

from quotation_agents.notes import append_section, digest_lines, init_notes, start_session
from quotation_agents.state import DocumentDigest


def test_notes_append_only_sections(tmp_path):
    path = tmp_path / "notes.md"
    init_notes(path, "Sistema de Campañas")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("Hand edit by the user.\n")

    start_session(path, 2, date(2026, 11, 14))
    append_section(path, "Decided", ["Scope approved (6 items)."])

    assert path.read_text(encoding="utf-8") == (
        "# Quotation notes — Sistema de Campañas\n"
        "Hand edit by the user.\n"
        "\n## 2026-11-14 — Session 2\n"
        "### Decided\n"
        "- Scope approved (6 items).\n"
    )


def test_append_section_empty_is_noop(tmp_path):
    path = tmp_path / "notes.md"
    init_notes(path, "X")
    before = path.read_text(encoding="utf-8")

    append_section(path, "Discovered", [])

    assert path.read_text(encoding="utf-8") == before


def test_digest_lines_lists_summary_first():
    digest = DocumentDigest(
        summary="Campaign draft",
        requirements=["Inbox"],
        constraints=["Budget"],
        open_questions=["Deadline?"],
        technologies=["n8n"],
    )

    lines = digest_lines("a.md", digest)

    assert lines[0] == "a.md: Campaign draft"
    assert "  requirement: Inbox" in lines
    assert "  constraint: Budget" in lines
    assert "  open question: Deadline?" in lines
    assert "  technology: n8n" in lines
