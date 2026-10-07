"""Command-line entry point for the fast CV analysis path."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import ConfigurationError, load_config
from .pipeline import run_fast_analysis
from .provider import ProviderError, create_openai_model
from .repository import ApplicationRecord


def main(
    argv: list[str] | None = None,
    *,
    model_factory: Any | None = None,
    http_client: Any | None = None,
    repository: Any | None = None,
) -> int:
    """Run the fast path and return a process-style exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    source = _resolve_source(args, parser)

    try:
        config = load_config()
        factory = model_factory or create_openai_model
        record = run_fast_analysis(
            source,
            config=config,
            model_factory=factory,
            model_name=args.model or config.model,
            http_client=http_client,
            repository=repository,
            database_path=args.db_path,
            application_id=args.application_id,
            status=args.status,
        )
    except (ConfigurationError, ProviderError, OSError, RuntimeError, ValueError) as exc:
        print(f"cv-analyze: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Provider SDKs may expose errors outside a common base class.
        print(f"cv-analyze: provider or pipeline error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_record_payload(record), ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a job against the canonical CV profile")
    parser.add_argument("source", nargs="?", help="Job URL or non-empty job-description text")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--url", help="Job URL")
    source_group.add_argument("--text", help="Job-description text fallback")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(os.getenv("CV_DATABASE_PATH", "applications.sqlite3")),
    )
    parser.add_argument("--application-id", help="Optional stable application identifier")
    parser.add_argument("--status", default="analyzed", help="Initial application status")
    parser.add_argument("--model", help="Override CV_MODEL for this invocation")
    return parser


def _resolve_source(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    supplied = [value for value in (args.source, args.url, args.text) if value is not None]
    if len(supplied) != 1:
        parser.error("provide exactly one positional source, --url, or --text")
    return supplied[0]


def _record_payload(record: ApplicationRecord) -> dict[str, Any]:
    return {
        "application_id": record.application_id,
        "source": record.source,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "job_requirements": record.requirements.model_dump(mode="json"),
        "gap_analysis": record.gap_analysis.model_dump(mode="json"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
