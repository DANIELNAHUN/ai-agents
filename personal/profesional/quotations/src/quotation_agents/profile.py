"""Developer profile stored as Markdown with YAML frontmatter."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .attachments import SourceDocument

PROFILE_FIELDS: tuple[str, ...] = (
    "stack",
    "tools",
    "mcps",
    "project_kinds",
    "team",
    "conventions",
)
LIST_FIELDS = ("stack", "tools", "mcps", "project_kinds")
CONVENTIONS_HEADING = "## Conventions"
FRONTMATTER_DELIMITER = "---"


class ProfileError(ValueError):
    """Raised when a developer profile cannot be parsed or edited."""


class TeamMember(BaseModel):
    """One person who can work on quoted projects."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    # Reserved for future pricing; never read by the pricing module yet.
    rate_per_hour: Decimal | None = Field(default=None, gt=0)


class DeveloperProfile(BaseModel):
    """Stack, tools, team and conventions that guide quotation agents."""

    model_config = ConfigDict(extra="forbid")

    stack: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    project_kinds: list[str] = Field(default_factory=list)
    team: list[TeamMember] = Field(default_factory=list)
    # Hand-written Markdown placed before the Conventions section, kept verbatim.
    sections: str = ""
    conventions: str = ""


class ProfileEdit(BaseModel):
    """One proposed change to a developer profile."""

    model_config = ConfigDict(extra="forbid")

    field: Literal["stack", "tools", "mcps", "project_kinds", "team", "conventions"]
    action: Literal["add", "remove", "replace"]
    value: str = Field(min_length=1)
    reason: str = ""


PROFILE_TEMPLATE = DeveloperProfile(
    stack=["Python", "React"],
    tools=["GitHub"],
    mcps=[],
    project_kinds=["fullstack"],
    team=[TeamMember(name="Me", role="fullstack")],
    conventions="Describe the conventions you want the agents to follow.",
)


def _error_detail(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{location}: {first['msg']}"


def parse_profile(text: str, *, source: str = "profile.md") -> DeveloperProfile:
    """Parse profile Markdown: YAML frontmatter plus a Conventions section."""

    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise ProfileError(f"{source}: missing YAML frontmatter delimited by '---'")
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONTMATTER_DELIMITER
        )
    except StopIteration as exc:
        raise ProfileError(f"{source}: frontmatter is not closed with '---'") from exc

    try:
        data = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{source}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{source}: frontmatter must be a mapping of fields")

    body = "\n".join(lines[end + 1 :])
    before, heading, after = body.partition(CONVENTIONS_HEADING)
    data["sections"] = before.strip() if heading else body.strip()
    if heading:
        data["conventions"] = after.strip()

    try:
        return DeveloperProfile.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(f"{source}: {_error_detail(exc)}") from exc


def render_profile(profile: DeveloperProfile) -> str:
    """Render a profile as Markdown with YAML frontmatter."""

    data = profile.model_dump(mode="json", exclude={"conventions", "sections"})
    data["team"] = [
        {key: value for key, value in member.items() if value is not None}
        for member in data["team"]
    ]
    frontmatter = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    sections = f"{profile.sections}\n\n" if profile.sections else ""
    return (
        f"{FRONTMATTER_DELIMITER}\n{frontmatter}{FRONTMATTER_DELIMITER}\n{sections}"
        f"{CONVENTIONS_HEADING}\n{profile.conventions}\n"
    )


def load_profile(path: Path) -> DeveloperProfile:
    """Read and parse a profile file."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"{path}: cannot read profile: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ProfileError(f"{path}: file is not UTF-8 encoded") from exc
    return parse_profile(text, source=str(path))


def save_profile(path: Path, profile: DeveloperProfile) -> None:
    """Write a profile file, creating its folder when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_profile(profile), encoding="utf-8")


def profile_source_document(profile: DeveloperProfile) -> SourceDocument:
    """Expose the profile to agents as delimited source data."""

    return SourceDocument(name="developer_profile.md", text=render_profile(profile))


def _contains(values: list[str], value: str) -> bool:
    return value.casefold() in {item.casefold() for item in values}


def _edit_list(values: list[str], edit: ProfileEdit) -> list[str]:
    value = edit.value.strip()
    if edit.action == "add":
        return values if _contains(values, value) else [*values, value]
    if edit.action == "remove":
        return [item for item in values if item.casefold() != value.casefold()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_member(value: str) -> TeamMember:
    name, separator, role = value.partition(" - ")
    if not separator or not name.strip() or not role.strip():
        raise ProfileError(f"Team member must look like 'Name - role': {value!r}")
    return TeamMember(name=name.strip(), role=role.strip())


def _edit_team(team: list[TeamMember], edit: ProfileEdit) -> list[TeamMember]:
    if edit.action == "remove":
        name = edit.value.strip().casefold()
        return [member for member in team if member.name.casefold() != name]
    member = _parse_member(edit.value)
    if edit.action == "replace":
        return [member]
    others = [item for item in team if item.name.casefold() != member.name.casefold()]
    return [*others, member]


def _edit_conventions(conventions: str, edit: ProfileEdit) -> str:
    value = edit.value.strip()
    if edit.action == "remove":
        raise ProfileError("Conventions can be added to or replaced, not removed")
    if edit.action == "replace" or not conventions.strip():
        return value
    return f"{conventions.rstrip()}\n\n{value}"


def apply_edit(profile: DeveloperProfile, edit: ProfileEdit) -> DeveloperProfile:
    """Return a copy of the profile with one edit applied."""

    if edit.field in LIST_FIELDS:
        current = getattr(profile, edit.field)
        return profile.model_copy(update={edit.field: _edit_list(current, edit)})
    if edit.field == "team":
        return profile.model_copy(update={"team": _edit_team(profile.team, edit)})
    return profile.model_copy(
        update={"conventions": _edit_conventions(profile.conventions, edit)}
    )
