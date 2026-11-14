from __future__ import annotations

from decimal import Decimal

import pytest

from quotation_agents.profile import (
    DeveloperProfile,
    ProfileEdit,
    ProfileError,
    TeamMember,
    apply_edit,
    parse_profile,
    profile_source_document,
    render_profile,
)


def _profile(**changes) -> DeveloperProfile:
    data = {
        "stack": ["Python", "React"],
        "tools": ["ClickUp", "GitHub"],
        "mcps": ["github"],
        "project_kinds": ["backend"],
        "team": [TeamMember(name="Daniel", role="fullstack")],
        "conventions": "Use trunk-based development.",
    }
    data.update(changes)
    return DeveloperProfile(**data)


def _edit(field: str, action: str, value: str) -> ProfileEdit:
    return ProfileEdit(field=field, action=action, value=value, reason="test")


def test_render_then_parse_round_trips():
    profile = _profile(
        team=[TeamMember(name="Daniel", role="fullstack", rate_per_hour=Decimal("25"))]
    )

    assert parse_profile(render_profile(profile)) == profile


def test_parse_reads_conventions_body():
    text = "---\nstack: [Python]\n---\n## Conventions\nUse trunk-based dev.\n"

    profile = parse_profile(text)

    assert profile.stack == ["Python"]
    assert profile.conventions == "Use trunk-based dev."


def test_parse_without_frontmatter_raises_profile_error():
    with pytest.raises(ProfileError, match="profile.md"):
        parse_profile("## Conventions\nNothing here\n")


def test_parse_invalid_field_names_file_and_field():
    with pytest.raises(ProfileError) as excinfo:
        parse_profile("---\nstack: 5\n---\n")

    assert "profile.md" in str(excinfo.value)
    assert "stack" in str(excinfo.value)


def test_apply_edit_add_is_case_insensitive_noop_when_present():
    profile = _profile(stack=["Python"])

    updated = apply_edit(profile, _edit("stack", "add", "python"))

    assert updated.stack == ["Python"]


def test_apply_edit_remove_and_replace_list():
    profile = _profile()

    removed = apply_edit(profile, _edit("tools", "remove", "github"))
    replaced = apply_edit(profile, _edit("stack", "replace", "Python, Vue"))

    assert removed.tools == ["ClickUp"]
    assert replaced.stack == ["Python", "Vue"]
    assert profile.tools == ["ClickUp", "GitHub"]


def test_apply_edit_team_add_and_remove():
    profile = _profile()

    added = apply_edit(profile, _edit("team", "add", "Ana - frontend"))
    removed = apply_edit(added, _edit("team", "remove", "ana"))

    assert added.team[-1] == TeamMember(name="Ana", role="frontend")
    assert removed.team == [TeamMember(name="Daniel", role="fullstack")]


def test_apply_edit_conventions():
    profile = _profile(conventions="First.")

    added = apply_edit(profile, _edit("conventions", "add", "Second."))
    replaced = apply_edit(profile, _edit("conventions", "replace", "Only."))

    assert added.conventions == "First.\n\nSecond."
    assert replaced.conventions == "Only."
    with pytest.raises(ProfileError):
        apply_edit(profile, _edit("conventions", "remove", "First."))


def test_profile_source_document_name():
    document = profile_source_document(_profile())

    assert document.name == "developer_profile.md"
    assert "Python" in document.text
