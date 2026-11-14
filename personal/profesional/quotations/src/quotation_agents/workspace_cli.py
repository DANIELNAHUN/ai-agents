"""Workspace-based quotation CLI: setup, list, resume and profile commands.

Usage:
    uv run quotation setup "Project name"
    uv run quotation list
    uv run quotation resume [SLUG]
    uv run quotation profile
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

from .attachments import SourceDocument
from .cli import (
    Fore,
    Style,
    _ask,
    _ask_choice,
    _ask_feedback,
    _ask_intake,
    _ask_yn,
    _bullet,
    _header,
    _infer_intake,
    _info,
    _phase_decompose,
    _phase_generate,
    _phase_pricing,
    _phase_review_draft,
    _review_tasks,
    _revise_category,
    _success,
    _warn,
)
from .ingestion import (
    IngestionResult,
    context_documents,
    create_digest_agent,
    digest_document,
    ingest_documents,
)
from .models import QuotationDraft, WorkCategory
from .notes import append_section, digest_lines, start_session
from .pricing import QuoteResult
from .profile import (
    PROFILE_TEMPLATE,
    DeveloperProfile,
    ProfileEdit,
    ProfileError,
    apply_edit,
    load_profile,
    save_profile,
)
from .profile_agent import (
    ProfileAgentError,
    collect_learning_sources,
    create_learning_agent,
    create_profile_edit_agent,
    load_learned_index,
    mark_reviewed,
    propose_profile_edits,
    save_learned_index,
    suggest_from_quotations,
)
from .progress import ProgressReporter, track
from .provider import create_configured_model
from .state import (
    DocumentDigest,
    GeneratedVersion,
    Phase,
    StateError,
    WorkspaceState,
    is_past,
    load_state,
    reopen,
    save_state,
)
from .workspace import (
    MAX_SLUG_LENGTH,
    WorkspaceError,
    WorkspacePaths,
    base_profile_path,
    create_slug_agent,
    create_workspace,
    learned_index_path,
    list_workspaces,
    open_workspace,
    resolve_root,
    slugify,
    suggest_slug,
    truncate_slug,
    unique_slug,
)

SCOPE_CHANGED_FEEDBACK = (
    "The approved scope changed. Revise these tasks so they match the new scope: keep tasks "
    "that still apply, adjust hours, add missing work, and remove tasks that no longer apply."
)
VERSION_FOLDER = re.compile(r"^v([1-9][0-9]*)$")

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
# resume
# ---------------------------------------------------------------------------

def next_version_number(output_dir: Path) -> int:
    """1 + the highest existing ``vN`` folder; other names are ignored."""

    if not output_dir.is_dir():
        return 1
    numbers = [
        int(match.group(1))
        for path in output_dir.iterdir()
        if path.is_dir() and (match := VERSION_FOLDER.match(path.name))
    ]
    return max(numbers, default=0) + 1


def write_snapshot(version_dir: Path, draft: QuotationDraft, quote: QuoteResult) -> None:
    """Keep the approved data behind a generated version for later comparison."""

    snapshot = {"draft": draft.model_dump(mode="json"), "quote": quote.model_dump(mode="json")}
    (version_dir / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _fail(message: str) -> NoReturn:
    print(f"\n{Fore.RED}{message}{Style.RESET_ALL}")
    sys.exit(1)


def _pick_slug(root: Path) -> str:
    choices = [summary for summary in list_workspaces(root) if summary.error is None]
    if not choices:
        print('No quotations yet. Run: uv run quotation setup "<name>"')
        sys.exit(0)
    _header("Choose a quotation")
    for number, summary in enumerate(choices, start=1):
        print(f"  {number}. {summary.slug} — {summary.name} ({summary.phase})")
    while True:
        answer = _ask("Quotation number")
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1].slug
        _warn(f"Choose a number between 1 and {len(choices)}.")


def _save(paths: WorkspacePaths, state: WorkspaceState, now: Clock) -> WorkspaceState:
    state = state.model_copy(update={"updated_at": now()})
    save_state(paths.state, state)
    return state


def _ingestion_notes(state: WorkspaceState, result: IngestionResult) -> list[str]:
    records = {record.name: record for record in state.documents}
    lines: list[str] = []
    for name in result.added + result.changed:
        digest = records[name].digest
        if digest is None:
            continue
        first, *rest = digest_lines(name, digest)
        prefix = "Updated " if name in result.changed else ""
        lines.extend([prefix + first, *rest])
    lines.extend(f"{name}: removed from documentations/" for name in result.removed)
    lines.extend(f"{name}: unreadable ({error})" for name, error in result.unreadable)
    return lines


def _ingest(
    paths: WorkspacePaths,
    state: WorkspaceState,
    models: ModelFactory,
    progress: ProgressReporter,
    now: Clock,
) -> tuple[WorkspaceState, IngestionResult]:
    def digest(document: SourceDocument) -> DocumentDigest:
        agent = track(create_digest_agent(models()), progress, f"Digest agent [{document.name}]")
        return digest_document(document, agent=agent)

    state, result = ingest_documents(paths, state, digest=digest, now=now())
    append_section(paths.notes, "Discovered", _ingestion_notes(state, result))
    for name, error in result.failed:
        _warn(f"Could not summarize {name}: {error}. It will be retried next time.")
    for name, error in result.unreadable:
        _warn(f"Skipped {name}: {error}")
    return _save(paths, state, now), result


def _hours(draft: QuotationDraft) -> str:
    return str(sum(task.estimated_hours or 0 for task in draft.tasks))


def _print_where_left_off(state: WorkspaceState) -> None:
    _header(f"{state.name} — session {state.session_count}")
    _info("Phase", state.phase.value)
    active = [record for record in state.documents if record.status == "active"]
    _info("Documents", str(len(active)))
    if state.draft is not None:
        _info("Client", state.draft.client_company)
        _info("Scope items", str(len(state.draft.inferred_scope)))
        if state.draft.tasks:
            _info("Tasks", f"{len(state.draft.tasks)} ({_hours(state.draft)} h)")
    for version in state.versions:
        _bullet(f"v{version.number} — {version.created_at.date()} — S/ {version.total}")


def _choose_reopen(state: WorkspaceState, result: IngestionResult) -> WorkspaceState | None:
    """Offer to go back to an earlier phase; None means quit."""

    if not is_past(state.phase, Phase.SCOPE_REVIEW):
        return state
    if result.has_new_content and _ask_yn(
        "New or changed documents arrived. Reopen scope review?", default=True
    ):
        return reopen(state, Phase.SCOPE_REVIEW)

    choices: dict[str, str] = {}
    if state.phase is not Phase.GENERATED:
        choices["c"] = "Continue"
    choices["s"] = "Reopen scope"
    if state.phase in (Phase.PRICING, Phase.GENERATED):
        choices["t"] = "Reopen tasks"
        choices["p"] = "Re-price and generate a new version"
    choices["q"] = "Quit"
    choice = _ask_choice("Next step", choices)
    if choice == "q":
        return None
    if choice == "c":
        return state
    target = {"s": Phase.SCOPE_REVIEW, "t": Phase.DECOMPOSITION, "p": Phase.PRICING}[choice]
    return reopen(state, target)


def _revise_for_new_scope(
    scope: QuotationDraft,
    models: ModelFactory,
    docs: tuple[SourceDocument, ...],
    progress: ProgressReporter,
) -> QuotationDraft:
    tasks = []
    for category in WorkCategory:
        tasks += _revise_category(
            scope,
            list(scope.tasks),
            category,
            SCOPE_CHANGED_FEEDBACK,
            models(),
            docs,
            progress,
            failure_outcome=f"The previous {category.value} tasks were kept.",
        )
    return scope.model_copy(update={"tasks": tasks})


def _generate_version(
    paths: WorkspacePaths,
    state: WorkspaceState,
    quote: QuoteResult,
    models: ModelFactory,
    progress: ProgressReporter,
    now: Clock,
    options: dict[str, Any],
) -> WorkspaceState:
    number = next_version_number(paths.output)
    version_dir = paths.output / f"v{number}"
    version_dir.mkdir(parents=True)
    _phase_generate(
        state.draft,
        quote,
        version_dir,
        options["language"],
        models(),
        options["project_name"] or state.name,
        options["provider_name"],
        progress,
    )
    write_snapshot(version_dir, state.draft, quote)
    version = GeneratedVersion(
        number=number,
        created_at=now(),
        total=quote.selected_amount,
        path=f"output/v{number}",
    )
    return state.model_copy(
        update={"quote": quote, "phase": Phase.GENERATED, "versions": [*state.versions, version]}
    )


def _run_intake(
    paths: WorkspacePaths,
    state: WorkspaceState,
    models: ModelFactory,
    docs: tuple[SourceDocument, ...],
    progress: ProgressReporter,
    now: Clock,
) -> WorkspaceState:
    """Ask the intake questions once, save the answers, then infer the scope."""

    _header("Phase 1 — Project intake")
    if state.client_company is None or state.original_request is None:
        client, request = _ask_intake()
        state = _save(
            paths,
            state.model_copy(update={"client_company": client, "original_request": request}),
            now,
        )
    else:
        _info("Client", state.client_company)
    try:
        draft = _infer_intake(
            state.client_company, state.original_request, models(), docs, progress
        )
    except Exception as exc:  # answers are saved; the next resume retries inference
        _fail(
            f"Requirement inference failed: {_describe_failure(exc)}\n"
            "Your intake answers were saved; run resume again to retry."
        )
    return state.model_copy(update={"draft": draft, "phase": Phase.SCOPE_REVIEW})


def _run_phases(
    paths: WorkspacePaths,
    state: WorkspaceState,
    profile: DeveloperProfile,
    models: ModelFactory,
    progress: ProgressReporter,
    now: Clock,
    options: dict[str, Any],
) -> WorkspaceState:
    """Run phases until a version is generated, checkpointing after each approval."""

    while state.phase is not Phase.GENERATED:
        docs = context_documents(state, profile)
        decided: list[str] = []
        if state.phase is Phase.INTAKE:
            state = _run_intake(paths, state, models, docs, progress, now)
            decided.append(f"Intake recorded for {state.draft.client_company}.")
        elif state.phase is Phase.SCOPE_REVIEW:
            scope = _phase_review_draft(state.draft, models(), docs, progress)
            # Saved before any task revision, so the approval survives a crash there.
            state = state.model_copy(update={"draft": scope, "phase": Phase.DECOMPOSITION})
            decided.append(f"Scope approved ({len(scope.inferred_scope)} items).")
        elif state.phase is Phase.DECOMPOSITION:
            scope = state.draft
            if state.revise_tasks_for_new_scope and scope.tasks:
                scope = _revise_for_new_scope(scope, models, docs, progress)
            if scope.tasks:
                draft = _review_tasks(scope, list(scope.tasks), models(), docs, progress)
            else:
                draft = _phase_decompose(scope, models(), docs, progress)
            state = state.model_copy(
                update={
                    "draft": draft,
                    "phase": Phase.PRICING,
                    "revise_tasks_for_new_scope": False,
                }
            )
            decided.append(f"Tasks approved: {len(draft.tasks)} tasks, {_hours(draft)} h.")
        elif (quote := _phase_pricing(state.draft)) is None:
            draft = _review_tasks(state.draft, list(state.draft.tasks), models(), docs, progress)
            state = state.model_copy(update={"draft": draft})
            decided.append(f"Tasks approved: {len(draft.tasks)} tasks, {_hours(draft)} h.")
        else:
            state = _generate_version(paths, state, quote, models, progress, now, options)
            decided.append(f"Generated v{state.versions[-1].number}: S/ {quote.selected_amount}.")
        append_section(paths.notes, "Decided", decided)
        state = _save(paths, state, now)
    return state


def cmd_resume(
    slug: str | None,
    root: Path,
    model_factory: ModelFactory,
    *,
    language: str,
    provider_name: str,
    project_name: str | None,
    now: Clock = _utc_now,
) -> None:
    """Continue a quotation from its last checkpoint without re-reading documents."""

    slug = slug or _pick_slug(root)
    try:
        paths = open_workspace(root, slug)
        state = load_state(paths.state)
        profile = load_profile(paths.profile)
    except (WorkspaceError, StateError, ProfileError) as exc:
        _fail(str(exc))

    state = state.model_copy(update={"session_count": state.session_count + 1})
    start_session(paths.notes, state.session_count, now().date())
    state = _save(paths, state, now)

    progress = ProgressReporter()
    state, result = _ingest(paths, state, model_factory, progress, now)
    _print_where_left_off(state)

    reopened = _choose_reopen(state, result)
    if reopened is None:
        return
    if reopened.phase is not state.phase:
        append_section(paths.notes, "Decided", [f"Reopened {reopened.phase.value}."])
        state = _save(paths, reopened, now)

    options = {"language": language, "provider_name": provider_name, "project_name": project_name}
    state = _run_phases(paths, state, profile, model_factory, progress, now, options)
    _success(f"Quotation ready: {paths.root / state.versions[-1].path}")


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------

def _told_changes(profile: DeveloperProfile, models: ModelFactory) -> DeveloperProfile:
    request = _ask("What changed in your profile? (empty to skip)")
    if not request:
        return profile
    try:
        edits = propose_profile_edits(profile, request, agent=create_profile_edit_agent(models()))
    except Exception as exc:  # keep the command usable when the provider fails
        _warn(f"The profile agent failed: {_describe_failure(exc)}")
        return profile
    profile, _approved = review_profile_edits(profile, edits)
    return profile


def _learned_changes(
    root: Path,
    profile: DeveloperProfile,
    models: ModelFactory,
) -> DeveloperProfile:
    index_path = learned_index_path(root)
    index = load_learned_index(index_path)
    sources = collect_learning_sources(root, index)
    if not sources:
        print("\nNo new quotation activity to learn from.")
        return profile
    try:
        suggestions = suggest_from_quotations(
            profile, sources, index, agent=create_learning_agent(models())
        )
    except Exception as exc:  # retried next time: the index is not updated
        _warn(f"The learning agent failed: {_describe_failure(exc)}")
        return profile

    if not suggestions:
        print("\nYour profile already covers your recent quotations.")
    for suggestion in suggestions:
        evidence = ", ".join(suggestion.evidence)
        _bullet(f"{suggestion.field}: {suggestion.value} (seen in: {evidence})")
        if _ask_yn("Add to your profile?", default=True):
            edit = ProfileEdit(
                field=suggestion.field,
                action="add",
                value=suggestion.value,
                reason=f"Seen in {evidence}",
            )
            profile = apply_edit(profile, edit)
    save_learned_index(index_path, mark_reviewed(index, sources, suggestions))
    return profile


def _save_base_profile(
    root: Path, before: DeveloperProfile, after: DeveloperProfile
) -> None:
    if after != before:
        save_profile(base_profile_path(root), after)
        _success(f"Base profile updated: {base_profile_path(root)}")


def cmd_profile(root: Path, model_factory: ModelFactory) -> None:
    """Improve the base profile from what you tell it and from past quotations."""

    _header("Developer profile")
    try:
        profile = ensure_base_profile(root)
        original = profile
        print_profile(profile)
        profile = _told_changes(profile, model_factory)
        _save_base_profile(root, original, profile)
        learned = _learned_changes(root, profile, model_factory)
        _save_base_profile(root, profile, learned)
    except (ProfileError, ProfileAgentError) as exc:
        _fail(str(exc))


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
    elif args.command == "resume":
        cmd_resume(
            args.slug,
            root,
            models,
            language=args.language,
            provider_name=args.provider_name,
            project_name=args.project_name,
        )
    else:
        cmd_profile(root, models)


if __name__ == "__main__":
    main()
