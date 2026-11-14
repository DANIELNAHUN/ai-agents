"""Interactive phases of the software quotation workflow.

The commands that drive these phases live in ``workspace_cli`` (entry point
``uv run quotation``).

Environment variables (or .env file in the project root):
    QUOTATION_PROVIDER     Provider name: openai | ollama | omniroute | freellm
    QUOTATION_MODEL        Model name (default: gpt-4o-mini)
    QUOTATION_API_KEY      API key for the provider
    QUOTATION_BASE_URL     Base URL for custom/local providers (required for ollama, freellm)
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional colour support
# ---------------------------------------------------------------------------
try:
    from colorama import Fore, Style
    from colorama import init as _colorama_init

    _colorama_init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

    class Fore:  # type: ignore[no-redef]
        CYAN = YELLOW = GREEN = RED = MAGENTA = BLUE = ""

    class Style:  # type: ignore[no-redef]
        BRIGHT = RESET_ALL = ""


# ---------------------------------------------------------------------------
# Quotation package imports
# ---------------------------------------------------------------------------
from quotation_agents import (
    ApprovalState,
    QuotationCalculationError,
    QuotationDraft,
    QuotationTask,
    QuoteResult,
    RequirementInference,
    WorkCategory,
    approve_draft,
    calculate_quote,
    create_commercial_synthesis_agent,
    create_decomposition_agent,
    create_requirement_inference_agent,
    decompose_category,
    generate_commercial_proposal_documents,
    generate_proposal_documents,
    review_quote,
    revise_draft,
    synthesize_commercial_proposal,
)
from quotation_agents.attachments import SourceDocument
from quotation_agents.inference import infer_requirements
from quotation_agents.progress import ProgressReporter, track

# ---------------------------------------------------------------------------
# Pretty print helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "─", width: int = 60) -> None:
    print(Fore.CYAN + char * width)


def _header(text: str) -> None:
    _sep()
    print(Fore.CYAN + Style.BRIGHT + f"  {text}")
    _sep()


def _info(label: str, value: str) -> None:
    print(f"  {Fore.YELLOW}{label}:{Style.RESET_ALL} {value}")


def _bullet(text: str) -> None:
    print(f"  {Fore.MAGENTA}•{Style.RESET_ALL} {text}")


def _success(text: str) -> None:
    print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ {text}{Style.RESET_ALL}")


def _warn(text: str) -> None:
    print(f"\n{Fore.YELLOW}⚠ {text}{Style.RESET_ALL}")


def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        value = input(f"\n{Fore.BLUE}{Style.BRIGHT}{prompt}{hint}:{Style.RESET_ALL} ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
    return value or default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = _ask(f"{prompt} ({hint})")
    if not raw:
        return default
    return raw.lower() in {"y", "yes", "s", "si", "sí"}


# ---------------------------------------------------------------------------
# Workflow phases
# ---------------------------------------------------------------------------

def _agent_label(name: str, model: Any, progress: ProgressReporter) -> str:
    model_name = getattr(model, "model_name", None) or getattr(model, "model", None)
    if not isinstance(model_name, str):
        return name
    return f"{name} {progress.separator} {model_name}"


def _ask_intake() -> tuple[str, str]:
    """Ask for the client name and the free-text project description."""

    client = _ask("Client / company name")
    if not client:
        print("Client name is required.")
        sys.exit(1)

    print(
        f"\n{Fore.YELLOW}Describe the project in as much detail as you have.\n"
        "Single blank lines between paragraphs are kept.\n"
        f"Press Enter on two empty lines in a row to finish.{Style.RESET_ALL}"
    )
    lines = []
    try:
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
    request = "\n".join(lines).strip()
    if not request:
        print("Project description is required.")
        sys.exit(1)
    return client, request


def _infer_intake(
    client: str,
    request: str,
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
    progress: ProgressReporter | None = None,
) -> QuotationDraft:
    """Infer requirements for the given intake answers with the LLM."""

    if source_documents:
        print("\nAttached requirement documents:")
        for document in source_documents:
            _bullet(document.name)

    print()
    progress = progress or ProgressReporter()
    inference = infer_requirements(
        client,
        request,
        source_documents=source_documents,
        agent=track(
            create_requirement_inference_agent(model),
            progress,
            _agent_label("Requirement inference agent", model, progress),
        ),
    )

    draft = QuotationDraft(
        client_company=client,
        original_request=request,
        inferred_scope=inference.inferred_scope,
        assumptions=inference.assumptions,
        questions=inference.questions,
        risks=inference.risks,
        approval_state=ApprovalState.PENDING,
    )
    return draft


def _phase_intake(
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
    progress: ProgressReporter | None = None,
) -> QuotationDraft:
    """Phase 1 — Gather client info and infer requirements with the LLM."""
    _header("Phase 1 — Project intake")

    client, request = _ask_intake()
    return _infer_intake(client, request, model, source_documents, progress)


def _ask_choice(prompt: str, choices: dict[str, str]) -> str:
    """Ask until the user picks one of the keyed choices; return its key."""

    menu = "  ".join(f"[{key}] {label}" for key, label in choices.items())
    while True:
        print(f"\n{Fore.CYAN}{menu}{Style.RESET_ALL}")
        answer = _ask(prompt).lower()
        if answer in choices:
            return answer
        _warn(f"Invalid option {answer!r}; choose one of: {', '.join(choices)}")


def _ask_feedback(prompt: str) -> str:
    feedback = _ask(prompt)
    if not feedback:
        _warn("No feedback entered; nothing was changed.")
    return feedback


def _print_scope(draft: QuotationDraft) -> None:
    _info("Client", draft.client_company)
    req_preview = draft.original_request[:120]
    if len(draft.original_request) > 120:
        req_preview += "…"
    _info("Request", req_preview)

    print(f"\n{Fore.CYAN}Inferred scope:{Style.RESET_ALL}")
    for item in draft.inferred_scope:
        _bullet(item)

    sections = (
        ("Assumptions", draft.assumptions),
        ("Questions pending confirmation", draft.questions),
        ("Risks", draft.risks),
    )
    for title, items in sections:
        if items:
            print(f"\n{Fore.YELLOW}{title}:{Style.RESET_ALL}")
            for item in items:
                _bullet(item)


def _phase_review_draft(
    draft: QuotationDraft,
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
    progress: ProgressReporter | None = None,
) -> QuotationDraft:
    """Phase 2 — Review the inferred scope; approve it or revise it with feedback."""
    _header("Phase 2 — Review inferred scope")

    progress = progress or ProgressReporter()
    while True:
        _print_scope(draft)
        choice = _ask_choice(
            "Scope decision",
            {"a": "Approve", "r": "Revise with feedback", "q": "Quit"},
        )
        if choice == "a":
            return approve_draft(draft)
        if choice == "q":
            print("Scope rejected. Exiting.")
            sys.exit(0)

        feedback = _ask_feedback("What should the agent change in the scope?")
        if not feedback:
            continue
        print()
        try:
            inference = infer_requirements(
                draft.client_company,
                draft.original_request,
                source_documents=source_documents,
                agent=track(
                    create_requirement_inference_agent(model),
                    progress,
                    _agent_label("Requirement inference agent", model, progress),
                ),
                feedback=feedback,
                previous=RequirementInference(
                    inferred_scope=draft.inferred_scope,
                    assumptions=draft.assumptions,
                    questions=draft.questions,
                    risks=draft.risks,
                ),
            )
        except Exception as exc:  # keep the interactive session alive on agent errors
            _agent_failed("inference", exc, "the previous scope was kept; try again or approve.")
            continue
        draft = revise_draft(draft, **inference.model_dump())


def _agent_failed(agent_name: str, exc: Exception, outcome: str) -> None:
    detail = " ".join(str(exc).split())
    if len(detail) > 300:
        detail = detail[:300] + "…"
    _warn(f"The {agent_name} agent failed: {detail}\n  {outcome}")


def _decompose(
    scope: QuotationDraft,
    category: WorkCategory,
    model: Any,
    source_documents: tuple[SourceDocument, ...],
    progress: ProgressReporter,
    *,
    failure_outcome: str,
    feedback: str | None = None,
    previous_tasks: list[QuotationTask] | None = None,
    task_numbers: list[int] | None = None,
) -> list[QuotationTask] | None:
    """Run one category agent; return None (after warning) when the agent fails."""

    print()
    try:
        decomposition = decompose_category(
            scope,
            category,
            source_documents=source_documents,
            agent=track(
                create_decomposition_agent(model, category=category),
                progress,
                _agent_label(f"Decomposition agent [{category.value}]", model, progress),
            ),
            feedback=feedback,
            previous_tasks=previous_tasks or (),
            task_numbers=task_numbers,
        )
    except Exception as exc:  # keep the interactive session alive on agent errors
        _agent_failed(category.value, exc, failure_outcome)
        return None
    return list(decomposition.tasks)


def _print_tasks(tasks: list[QuotationTask]) -> None:
    print(f"\n{Fore.CYAN}Tasks:{Style.RESET_ALL}")
    for number, task in enumerate(tasks, start=1):
        hours_text = f"{task.estimated_hours}h" if task.estimated_hours else "?h"
        print(f"  {number:>2}. [{task.category.value}] {task.description} — {hours_text}")
    total = sum((task.estimated_hours or Decimal("0") for task in tasks), Decimal("0"))
    print(f"\n{Fore.CYAN}Total tasks:{Style.RESET_ALL} {len(tasks)} · {total}h estimated")

    missing = sum(1 for task in tasks if task.estimated_hours is None)
    if missing:
        noun = "task has" if missing == 1 else "tasks have"
        _warn(f"{missing} {noun} no estimated hours (shown as ?h).")


def _ask_task_number(tasks: list[QuotationTask]) -> int | None:
    raw = _ask(f"Task number (1-{len(tasks)})")
    if raw.isdigit() and 1 <= int(raw) <= len(tasks):
        return int(raw) - 1
    _warn("Invalid task number.")
    return None


_PLAIN_HOURS = re.compile(r"\d+(\.\d+)?")


def _ask_hours(description: str) -> Decimal:
    while True:
        raw = _ask(f"Hours for \"{description}\"").replace(",", ".")
        if _PLAIN_HOURS.fullmatch(raw) and Decimal(raw) > 0:
            return Decimal(raw)
        _warn("Enter a positive number of hours, for example 6 or 2.5.")


def _with_hours(task: QuotationTask, hours: Decimal) -> QuotationTask:
    """Return a copy of the task with new hours, re-running model validation."""

    return QuotationTask.model_validate({**task.model_dump(), "estimated_hours": hours})


def _empty_categories(tasks: list[QuotationTask]) -> list[WorkCategory]:
    used = {task.category for task in tasks}
    return [category for category in WorkCategory if category not in used]


def _ask_category(tasks: list[QuotationTask]) -> WorkCategory | None:
    categories = list(WorkCategory)
    empty = set(_empty_categories(tasks))
    for number, category in enumerate(categories, start=1):
        marker = " (no tasks)" if category in empty else ""
        _bullet(f"{number}. {category.value}{marker}")
    raw = _ask(f"Category to revise (1-{len(categories)})")
    if raw.isdigit() and 1 <= int(raw) <= len(categories):
        return categories[int(raw) - 1]
    _warn("Invalid category.")
    return None


def _confirm_empty_categories(tasks: list[QuotationTask]) -> bool:
    """Ask before approving when a whole category has no tasks (risk of under-quoting)."""

    empty = _empty_categories(tasks)
    if not empty:
        return True
    _warn(
        "These categories have no tasks: "
        + ", ".join(category.value for category in empty)
        + "\n  The quote will not include any work for them."
    )
    return _ask_yn("Approve anyway?", default=False)


def _revise_category(
    scope: QuotationDraft,
    tasks: list[QuotationTask],
    category: WorkCategory,
    feedback: str,
    model: Any,
    source_documents: tuple[SourceDocument, ...],
    progress: ProgressReporter,
    failure_outcome: str,
) -> list[QuotationTask]:
    """Revise one category with feedback; keep its previous tasks if the agent fails."""

    numbered = [
        (number, task) for number, task in enumerate(tasks, start=1) if task.category is category
    ]
    revised = _decompose(
        scope,
        category,
        model,
        source_documents,
        progress,
        failure_outcome=failure_outcome,
        feedback=feedback,
        previous_tasks=[task for _number, task in numbered],
        task_numbers=[number for number, _task in numbered],
    )
    if revised is None:
        return [task for _number, task in numbered]
    return revised


def _review_tasks(
    scope: QuotationDraft,
    tasks: list[QuotationTask],
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
    progress: ProgressReporter | None = None,
) -> QuotationDraft:
    """Let the user approve tasks, fix hours, or ask agents to revise them with feedback."""

    progress = progress or ProgressReporter()
    tasks = list(tasks)
    while True:
        _print_tasks(tasks)
        choice = _ask_choice(
            "Task decision",
            {
                "a": "Approve",
                "e": "Edit hours",
                "r": "Revise a category with feedback",
                "g": "Revise all categories with feedback",
                "q": "Quit",
            },
        )
        if choice == "q":
            print("Tasks rejected. Exiting.")
            sys.exit(0)
        if choice == "a":
            if any(task.estimated_hours is None for task in tasks):
                _warn(
                    "Every task needs estimated hours before pricing. "
                    "Edit them or ask the agent to revise the category."
                )
                continue
            if not _confirm_empty_categories(tasks):
                continue
            return approve_draft(revise_draft(scope, tasks=tasks))
        if choice == "e":
            index = _ask_task_number(tasks)
            if index is not None:
                hours = _ask_hours(tasks[index].description)
                tasks[index] = _with_hours(tasks[index], hours)
            continue

        if choice == "g":
            feedback = _ask_feedback("What should the agents change across all tasks?")
            if not feedback:
                continue
            revised: list[QuotationTask] = []
            for category in WorkCategory:
                revised += _revise_category(
                    scope, tasks, category, feedback, model, source_documents, progress,
                    failure_outcome=f"The previous {category.value} tasks were kept.",
                )
            tasks = revised
            continue

        category = _ask_category(tasks)
        if category is None:
            continue
        feedback = _ask_feedback(f"What should the {category.value} agent change?")
        if not feedback:
            continue
        revised = _revise_category(
            scope, tasks, category, feedback, model, source_documents, progress,
            failure_outcome="The previous tasks were kept; try again, edit hours, or approve.",
        )
        order = list(WorkCategory)
        tasks = [task for task in tasks if task.category is not category] + revised
        tasks.sort(key=lambda task: order.index(task.category))


def _phase_decompose(
    draft: QuotationDraft,
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
    progress: ProgressReporter | None = None,
) -> QuotationDraft:
    """Phase 3 — Decompose into technical tasks per work category, then review them."""
    _header("Phase 3 — Technical task decomposition")

    progress = progress or ProgressReporter()
    tasks: list[QuotationTask] = []
    for category in WorkCategory:
        category_tasks = _decompose(
            draft,
            category,
            model,
            source_documents,
            progress,
            failure_outcome="The category is empty for now; use [r] to retry it.",
        )
        tasks.extend(category_tasks or [])
    return _review_tasks(draft, tasks, model, source_documents, progress)


def _phase_pricing(draft: QuotationDraft) -> QuoteResult | None:
    """Phase 4 — Show pricing; return the quote, or None to go back to the tasks."""
    _header("Phase 4 — Pricing")

    try:
        quote = calculate_quote(draft)
    except QuotationCalculationError as exc:
        _warn(f"Cannot calculate the quote: {exc}. Returning to task review.")
        return None

    _info("Total hours", str(quote.effort.total_hours))
    _info("Calendar days (3h/day)", str(quote.effort.calendar_days))
    _info("Minimum", f"S/ {quote.minimum_amount}")
    _info("Ideal", f"S/ {quote.ideal_amount}")
    _info("Maximum", f"S/ {quote.maximum_amount}")
    _info("Selected", f"S/ {quote.selected_amount}")

    if quote.ceiling_exceeded:
        _warn(
            "Quote exceeds S/ 10,000 ceiling. "
            "Consider modularizing delivery or requesting manual approval."
        )

    print(f"\n{Fore.CYAN}Payment schedule:{Style.RESET_ALL}")
    for payment in quote.payment_schedule.payments:
        _bullet(f"{payment.label} — S/ {payment.amount}")

    choice = _ask_choice(
        "Quote decision",
        {"a": "Accept", "b": "Back to tasks to adjust and recalculate", "q": "Quit"},
    )
    if choice == "q":
        print("Quote rejected. Exiting.")
        sys.exit(0)
    return quote if choice == "a" else None


def _phase_generate(
    draft: QuotationDraft,
    quote: Any,
    output_dir: Path,
    language: str,
    model: Any,
    project_name: str,
    provider_name: str,
    progress: ProgressReporter | None = None,
) -> None:
    """Phase 5 — Generate internal DOCX and client-facing commercial DOCX."""
    _header("Phase 5 — Generating proposal documents")

    # --- Internal technical proposal ---
    print(f"\n{Fore.CYAN}Generating internal technical proposal...{Style.RESET_ALL}")
    review = review_quote(draft, quote)
    if not review.ready_for_document:
        _warn("Review issues found:")
        for issue in review.issues:
            _bullet(f"[{issue.severity}] {issue.code}: {issue.message}")
        if not _ask_yn("Continue anyway?", default=False):
            sys.exit(0)

    internal_docs = generate_proposal_documents(
        draft,
        quote,
        output_dir,
        filename="quotation-internal",
        language=language,
        overwrite=True,
    )
    _success(f"Internal proposal: {internal_docs.docx_path}")

    # --- Commercial (client-facing) proposal ---
    print()
    progress = progress or ProgressReporter()
    commercial = synthesize_commercial_proposal(
        draft,
        quote,
        project_name=project_name,
        provider_name=provider_name,
        agent=track(
            create_commercial_synthesis_agent(model),
            progress,
            _agent_label("Commercial synthesis agent", model, progress),
        ),
    )

    commercial_docs = generate_commercial_proposal_documents(
        commercial,
        output_dir,
        filename="quotation-commercial",
        overwrite=True,
    )
    _success(f"Commercial proposal: {commercial_docs.docx_path}")

    _sep("═")
    print(f"\n{Fore.GREEN}{Style.BRIGHT}Done! Both proposals saved to:{Style.RESET_ALL}")
    print(f"  {output_dir}")
    print(
        f"\n  {Fore.YELLOW}quotation-internal.docx{Style.RESET_ALL} "
        "→ for you (technical breakdown)"
    )
    print(
        f"  {Fore.YELLOW}quotation-commercial.docx{Style.RESET_ALL} "
        "→ for the client (business language)"
    )
