"""Interactive CLI for the software quotation workflow.

Usage:
    uv run python -m quotation_agents.cli
    uv run python -m quotation_agents.cli --output ./proposals --language es
    uv run python -m quotation_agents.cli --help

Environment variables (or .env file in the project root):
    QUOTATION_PROVIDER     Provider name: openai | ollama | omniroute | freellm
    QUOTATION_MODEL        Model name (default: gpt-4o-mini)
    QUOTATION_API_KEY      API key for the provider
    QUOTATION_BASE_URL     Base URL for custom/local providers (required for ollama, freellm)
"""

from __future__ import annotations

import argparse
import sys
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
    AttachmentError,
    ApprovalState,
    QuotationDraft,
    QuotationTask,
    WorkCategory,
    approve_draft,
    calculate_quote,
    create_configured_model,
    decompose_category,
    generate_commercial_proposal_documents,
    generate_proposal_documents,
    load_source_documents,
    review_quote,
    revise_draft,
    synthesize_commercial_proposal,
)
from quotation_agents.attachments import SourceDocument
from quotation_agents.inference import infer_requirements

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

def _phase_intake(
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
) -> QuotationDraft:
    """Phase 1 — Gather client info and infer requirements with the LLM."""
    _header("Phase 1 — Project intake")

    client = _ask("Client / company name")
    if not client:
        print("Client name is required.")
        sys.exit(1)

    print(
        f"\n{Fore.YELLOW}Describe the project in as much detail as you have.\n"
        f"Press Enter twice when done.{Style.RESET_ALL}"
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

    if source_documents:
        print("\nAttached requirement documents:")
        for document in source_documents:
            _bullet(document.name)

    print(f"\n{Fore.CYAN}Running requirement inference...{Style.RESET_ALL}")
    inference = infer_requirements(
        client,
        request,
        source_documents=source_documents,
        model=model,
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


def _phase_review_draft(draft: QuotationDraft) -> QuotationDraft:
    """Phase 2 — Show inferred scope and ask for approval or edits."""
    _header("Phase 2 — Review inferred scope")

    _info("Client", draft.client_company)
    req_preview = draft.original_request[:120]
    if len(draft.original_request) > 120:
        req_preview += "…"
    _info("Request", req_preview)

    print(f"\n{Fore.CYAN}Inferred scope:{Style.RESET_ALL}")
    for item in draft.inferred_scope:
        _bullet(item)

    if draft.assumptions:
        print(f"\n{Fore.YELLOW}Assumptions:{Style.RESET_ALL}")
        for item in draft.assumptions:
            _bullet(item)

    if draft.questions:
        print(f"\n{Fore.YELLOW}Questions pending confirmation:{Style.RESET_ALL}")
        for item in draft.questions:
            _bullet(item)

    if draft.risks:
        print(f"\n{Fore.YELLOW}Risks:{Style.RESET_ALL}")
        for item in draft.risks:
            _bullet(item)

    if not _ask_yn("\nApprove this scope to continue to task decomposition?"):
        print("Scope rejected. Exiting — re-run to restart with a refined description.")
        sys.exit(0)

    return approve_draft(draft)


def _phase_decompose(
    draft: QuotationDraft,
    model: Any,
    source_documents: tuple[SourceDocument, ...] = (),
) -> QuotationDraft:
    """Phase 3 — Decompose into technical tasks per work category."""
    _header("Phase 3 — Technical task decomposition")

    all_tasks: list[QuotationTask] = []
    for category in WorkCategory:
        print(f"\n{Fore.CYAN}Decomposing category: {category.value}...{Style.RESET_ALL}")
        decomposition = decompose_category(
            draft,
            category,
            source_documents=source_documents,
            model=model,
        )
        for task in decomposition.tasks:
            hours_text = str(task.estimated_hours) if task.estimated_hours else "?"
            _bullet(f"[{category.value}] {task.description} — {hours_text}h")
        all_tasks.extend(decomposition.tasks)

    print(f"\n{Fore.CYAN}Total tasks decomposed:{Style.RESET_ALL} {len(all_tasks)}")

    if not _ask_yn("\nApprove these tasks to proceed to pricing?"):
        print("Tasks rejected. Exiting — re-run to restart.")
        sys.exit(0)

    draft = revise_draft(draft, tasks=all_tasks)
    return approve_draft(draft)


def _phase_pricing(draft: QuotationDraft) -> tuple[Any, list[Any] | None]:
    """Phase 4 — Show pricing summary and optionally configure modules."""
    _header("Phase 4 — Pricing")

    quote = calculate_quote(draft)
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

    if not _ask_yn("\nAccept this quote to generate the proposal?"):
        print("Quote rejected. Exiting.")
        sys.exit(0)

    return quote, None


def _phase_generate(
    draft: QuotationDraft,
    quote: Any,
    output_dir: Path,
    language: str,
    model: Any,
    project_name: str,
    provider_name: str,
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
    print(f"\n{Fore.CYAN}Synthesizing client-facing commercial proposal...{Style.RESET_ALL}")
    commercial = synthesize_commercial_proposal(
        draft,
        quote,
        project_name=project_name,
        provider_name=provider_name,
        model=model,
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive software quotation workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./proposals"),
        metavar="DIR",
        help="Output directory for generated DOCX files (default: ./proposals)",
    )
    parser.add_argument(
        "--language",
        choices=["en", "es"],
        default="es",
        help="Language for the internal proposal document (default: es)",
    )
    parser.add_argument(
        "--project-name",
        type=str,
        default=None,
        metavar="NAME",
        help="Override the project name in the commercial proposal",
    )
    parser.add_argument(
        "--provider-name",
        type=str,
        default="Daniel Calcina",
        metavar="NAME",
        help="Provider name shown in commercial proposals (default: Daniel Calcina)",
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to a .env file with QUOTATION_* variables",
    )
    parser.add_argument(
        "--attachment",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "Requirement document to include as source context; repeat for multiple files "
            "(PDF, DOCX, MD, or TXT)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        source_documents = load_source_documents(args.attachment)
    except AttachmentError as exc:
        print(f"\n{Fore.RED}Attachment error: {exc}{Style.RESET_ALL}")
        sys.exit(1)

    _header("Software Quotation Workflow")
    print(f"  Output: {args.output}")
    print(f"  Language: {args.language}")
    if source_documents:
        print(f"  Attachments: {len(source_documents)}")

    print(f"\n{Fore.CYAN}Loading model configuration...{Style.RESET_ALL}")
    try:
        model = create_configured_model(dotenv_path=args.dotenv)
    except Exception as exc:
        print(f"\n{Fore.RED}Configuration error: {exc}{Style.RESET_ALL}")
        print(
            "\nMake sure you have a .env file or environment variables set:\n"
            "  QUOTATION_PROVIDER=openai\n"
            "  QUOTATION_MODEL=gpt-4o-mini\n"
            "  QUOTATION_API_KEY=sk-...\n"
        )
        sys.exit(1)

    # Phase 1: Intake
    draft = _phase_intake(model, source_documents)

    # Phase 2: Scope review
    draft = _phase_review_draft(draft)

    # Phase 3: Technical decomposition
    draft = _phase_decompose(draft, model, source_documents)

    # Phase 4: Pricing
    quote, modules = _phase_pricing(draft)

    # Resolve project name
    project_name = args.project_name or (
        draft.inferred_scope[0] if draft.inferred_scope else draft.original_request[:50]
    )

    # Phase 5: Generate documents
    args.output.mkdir(parents=True, exist_ok=True)
    _phase_generate(
        draft,
        quote,
        args.output,
        args.language,
        model,
        project_name,
        args.provider_name,
    )


if __name__ == "__main__":
    main()
