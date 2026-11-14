"""Workspace-based quotation CLI: setup, list, resume and profile commands.

Usage:
    uv run quotation setup "Project name"
    uv run quotation list
    uv run quotation resume [SLUG]
    uv run quotation profile
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli import (
    Fore,
    Style,
    _ask,
    _ask_feedback,
    _ask_yn,
    _bullet,
    _header,
    _info,
    _success,
    _warn,
)
from .notes import append_section
from .profile import (
    PROFILE_TEMPLATE,
    DeveloperProfile,
    ProfileEdit,
    ProfileError,
    apply_edit,
    load_profile,
    save_profile,
)
from .profile_agent import create_profile_edit_agent, propose_profile_edits
from .provider import create_configured_model
from .workspace import (
    MAX_SLUG_LENGTH,
    WorkspacePaths,
    base_profile_path,
    create_slug_agent,
    create_workspace,
    list_workspaces,
    resolve_root,
    slugify,
    suggest_slug,
    truncate_slug,
    unique_slug,
)

Clock = Callable[[], datetime]
ModelFactory = Callable[[], Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _describe_failure(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    return detail if len(detail) <= 300 else detail[:300] + "…"


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def ensure_base_profile(root: Path) -> DeveloperProfile:
    """Load the base profile, offering to create it from the template when missing."""

    path = base_profile_path(root)
    if path.is_file():
        return load_profile(path)
    if _ask_yn("No base profile found. Create one from the template?", default=True):
        save_profile(path, PROFILE_TEMPLATE)
        _success(f"Base profile created: {path} (edit it, or run: uv run quotation profile)")
    return PROFILE_TEMPLATE


def print_profile(profile: DeveloperProfile) -> None:
    _info("Stack", ", ".join(profile.stack) or "-")
    _info("Tools", ", ".join(profile.tools) or "-")
    _info("MCPs", ", ".join(profile.mcps) or "-")
    _info("Project kinds", ", ".join(profile.project_kinds) or "-")
    team = ", ".join(f"{member.name} ({member.role})" for member in profile.team)
    _info("Team", team or "-")


def describe_edit(edit: ProfileEdit) -> str:
    return f"{edit.field} {edit.action} {edit.value}"


def review_profile_edits(
    profile: DeveloperProfile,
    edits: list[ProfileEdit],
) -> tuple[DeveloperProfile, list[ProfileEdit]]:
    """Show each proposed edit and apply only the ones the user approves."""

    approved: list[ProfileEdit] = []
    if not edits:
        _warn("The agent proposed no changes.")
    for edit in edits:
        print()
        _bullet(f"{describe_edit(edit)}" + (f" — {edit.reason}" if edit.reason else ""))
        if not _ask_yn("Apply this change?", default=True):
            continue
        try:
            profile = apply_edit(profile, edit)
        except ProfileError as exc:
            _warn(f"Could not apply this change: {exc}")
            continue
        approved.append(edit)
    return profile, approved


def _adjust_project_profile(paths: WorkspacePaths, model_factory: ModelFactory) -> None:
    profile = load_profile(paths.profile)
    print_profile(profile)
    if not _ask_yn("Adjust anything in the profile for this project?", default=False):
        return
    request = _ask_feedback("What should change for this project?")
    if not request:
        return
    try:
        edits = propose_profile_edits(
            profile, request, agent=create_profile_edit_agent(model_factory())
        )
    except Exception as exc:  # keep setup usable when the provider fails
        _warn(f"The profile agent failed: {_describe_failure(exc)}. Edit {paths.profile} by hand.")
        return
    profile, approved = review_profile_edits(profile, edits)
    if approved:
        save_profile(paths.profile, profile)
        append_section(
            paths.notes,
            "Decided",
            [f"Project profile adjusted: {describe_edit(edit)}" for edit in approved],
        )


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def _ask_name(name: str | None) -> tuple[str, str]:
    while True:
        name = (name or "").strip() or _ask("Quotation name")
        slug = slugify(name)
        if slug:
            return name, slug
        _warn("That name has no letters or numbers to build a folder name from.")
        name = None


def _short_slug(name: str, slug: str, model_factory: ModelFactory) -> str:
    if len(slug) <= MAX_SLUG_LENGTH:
        return slug
    try:
        suggested = suggest_slug(name, agent=create_slug_agent(model_factory()))
    except Exception as exc:  # fall back to a plain cut
        _warn(f"Could not summarize the name ({_describe_failure(exc)}); truncating it.")
        suggested = ""
    return suggested or truncate_slug(slug)


def cmd_setup(
    name: str | None,
    root: Path,
    model_factory: ModelFactory,
    now: Clock = _utc_now,
) -> WorkspacePaths:
    """Create a quotation workspace and optionally tailor its profile copy."""

    _header("New quotation workspace")
    name, slug = _ask_name(name)
    slug = _short_slug(name, slug, model_factory)
    chosen = slugify(_ask("Folder name", default=slug)) or slug
    folder = unique_slug(root, chosen)
    if folder != chosen:
        _warn(f"A workspace named {chosen!r} already exists; using {folder!r}.")

    profile = ensure_base_profile(root)
    paths = create_workspace(root, name, folder, profile, now())
    _success(f"Workspace created: {paths.root}")

    print(f"\n{Fore.CYAN}Developer profile for this project:{Style.RESET_ALL}")
    _adjust_project_profile(paths, model_factory)

    print(
        f"\nDrop draft files into {paths.documentations}, then run:\n"
        f"  uv run quotation resume {folder}"
    )
    return paths


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(root: Path) -> None:
    """Print every workspace with its phase, activity and latest version."""

    summaries = list_workspaces(root)
    if not summaries:
        print('No quotations yet. Run: uv run quotation setup "<name>"')
        return
    _header(f"Quotations in {root}")
    for summary in summaries:
        if summary.error:
            print(f"  {summary.slug:<32} invalid: {summary.error}")
            continue
        version = (
            f"v{summary.latest_version} S/ {summary.latest_total}"
            if summary.latest_version
            else "-"
        )
        activity = summary.last_activity.date().isoformat() if summary.last_activity else "-"
        print(
            f"  {summary.slug:<32} {summary.name}\n"
            f"  {'':<32} phase: {summary.phase}  last activity: {activity}  latest: {version}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        metavar="DIR",
        help="Workspaces folder (default: $QUOTATION_WORKSPACES or the package quotes/ folder)",
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to a .env file with QUOTATION_* variables",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quotation",
        description="Software quotation workspaces",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    setup = commands.add_parser("setup", help="Create a quotation workspace")
    setup.add_argument("name", nargs="?", help="Quotation name (asked when omitted)")
    _add_common(setup)

    listing = commands.add_parser("list", help="List all quotation workspaces")
    _add_common(listing)

    resume = commands.add_parser("resume", help="Continue a quotation where you left off")
    resume.add_argument(
        "slug", nargs="?", help="Workspace folder name (pick from a list if omitted)"
    )
    resume.add_argument(
        "--language",
        choices=["en", "es"],
        default="es",
        help="Language for the internal proposal document (default: es)",
    )
    resume.add_argument(
        "--provider-name",
        default="Daniel Calcina",
        metavar="NAME",
        help="Provider name shown in commercial proposals (default: Daniel Calcina)",
    )
    resume.add_argument(
        "--project-name",
        default=None,
        metavar="NAME",
        help="Project name in the commercial proposal (default: the workspace name)",
    )
    _add_common(resume)

    profile = commands.add_parser("profile", help="Improve your base developer profile")
    _add_common(profile)
    return parser


def _model_factory(dotenv: Path | None) -> ModelFactory:
    cache: list[Any] = []

    def create() -> Any:
        if not cache:
            try:
                cache.append(create_configured_model(dotenv_path=dotenv))
            except Exception as exc:
                print(f"\n{Fore.RED}Configuration error: {exc}{Style.RESET_ALL}")
                print(
                    "\nMake sure you have a .env file or environment variables set:\n"
                    "  QUOTATION_PROVIDER=openai\n"
                    "  QUOTATION_MODEL=gpt-4o-mini\n"
                    "  QUOTATION_API_KEY=sk-...\n"
                )
                sys.exit(1)
        return cache[0]

    return create


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    root = resolve_root(args.root)
    models = _model_factory(args.dotenv)
    if args.command == "setup":
        cmd_setup(args.name, root, models)
    elif args.command == "list":
        cmd_list(root)
    else:
        print(f"The {args.command!r} command is not available yet.")
        sys.exit(1)


if __name__ == "__main__":
    main()
