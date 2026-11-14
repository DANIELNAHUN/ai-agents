"""Append-only, human-readable notes log for a quotation workspace."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from .state import DocumentDigest


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def init_notes(path: Path, name: str) -> None:
    """Start a notes file with its header."""

    path.write_text(f"# Quotation notes — {name}\n", encoding="utf-8")


def start_session(path: Path, number: int, today: date) -> None:
    """Append a dated session heading."""

    _append(path, f"\n## {today.isoformat()} — Session {number}\n")


def append_section(
    path: Path,
    heading: Literal["Discovered", "Decided"],
    items: Sequence[str],
) -> None:
    """Append a bullet section; nothing is written for an empty list."""

    if not items:
        return
    bullets = "".join(f"- {item}\n" for item in items)
    _append(path, f"### {heading}\n{bullets}")


def digest_lines(name: str, digest: DocumentDigest) -> list[str]:
    """Render a document digest as note lines, summary first."""

    lines = [f"{name}: {digest.summary}"]
    groups = (
        ("requirement", digest.requirements),
        ("constraint", digest.constraints),
        ("open question", digest.open_questions),
        ("technology", digest.technologies),
    )
    for label, values in groups:
        lines.extend(f"  {label}: {value}" for value in values)
    return lines
