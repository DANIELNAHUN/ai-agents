"""Small isolated SQLite repository for CV application snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import GapAnalysis, JobRequirements


@dataclass(frozen=True)
class ApplicationRecord:
    """Application data reconstructed from one durable SQLite record."""

    application_id: str
    source: str
    job_text: str
    requirements: JobRequirements
    profile_snapshot: str
    gap_analysis: GapAnalysis
    status: str
    created_at: str
    updated_at: str

    @property
    def job_description(self) -> str:
        """Compatibility alias for the stored job text."""

        return self.job_text

    @property
    def job_requirements(self) -> JobRequirements:
        """Compatibility alias for the structured requirements snapshot."""

        return self.requirements

    @property
    def profile_markdown(self) -> str:
        """Compatibility alias for the profile snapshot."""

        return self.profile_snapshot


class SQLiteApplicationRepository:
    """Persist application records in a database isolated by its file path."""

    def __init__(self, database_path: str | Path = "applications.sqlite3") -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    application_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    job_text TEXT NOT NULL,
                    requirements_json TEXT NOT NULL,
                    profile_snapshot TEXT NOT NULL,
                    gap_analysis_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_application(
        self,
        source: str,
        *,
        job_text: str | None = None,
        requirements: JobRequirements | Mapping[str, Any] | None = None,
        profile_snapshot: str | None = None,
        gap_analysis: GapAnalysis | Mapping[str, Any] | None = None,
        status: str = "analyzed",
        application_id: str | None = None,
        job_description: str | None = None,
        job_requirements: JobRequirements | Mapping[str, Any] | None = None,
        profile_markdown: str | None = None,
    ) -> ApplicationRecord:
        """Atomically insert or replace one application snapshot.

        The alternate parameter names preserve a clear API for callers that use
        the domain terms ``job_description`` and ``profile_markdown``.
        """

        if not source.strip():
            raise ValueError("Application source cannot be empty")
        resolved_job_text = job_text if job_text is not None else job_description
        resolved_requirements = requirements if requirements is not None else job_requirements
        resolved_profile = profile_snapshot if profile_snapshot is not None else profile_markdown
        if not resolved_job_text or not resolved_job_text.strip():
            raise ValueError("Job text cannot be empty")
        if resolved_requirements is None:
            raise ValueError("Structured job requirements are required")
        if resolved_profile is None or not resolved_profile.strip():
            raise ValueError("Profile snapshot cannot be empty")
        if gap_analysis is None:
            raise ValueError("Gap analysis is required")
        if not status.strip():
            raise ValueError("Application status cannot be empty")

        validated_requirements = JobRequirements.model_validate(resolved_requirements)
        validated_gap_analysis = GapAnalysis.model_validate(gap_analysis)
        resolved_id = application_id or deterministic_application_id(
            source=source,
            job_text=resolved_job_text,
            requirements=validated_requirements,
        )
        if not resolved_id.strip():
            raise ValueError("Application ID cannot be empty")

        now = _utc_timestamp()
        requirements_json = _canonical_json(validated_requirements.model_dump(mode="json"))
        gap_analysis_json = _canonical_json(validated_gap_analysis.model_dump(mode="json"))
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO applications (
                    application_id, source, job_text, requirements_json,
                    profile_snapshot, gap_analysis_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(application_id) DO UPDATE SET
                    source = excluded.source,
                    job_text = excluded.job_text,
                    requirements_json = excluded.requirements_json,
                    profile_snapshot = excluded.profile_snapshot,
                    gap_analysis_json = excluded.gap_analysis_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_id,
                    source,
                    resolved_job_text,
                    requirements_json,
                    resolved_profile,
                    gap_analysis_json,
                    status,
                    now,
                    now,
                ),
            )
        return self.get_application(resolved_id)  # type: ignore[return-value]

    def get_application(self, application_id: str) -> ApplicationRecord | None:
        """Return one application or ``None`` when it is not in this database."""

        row = self._connection.execute(
            "SELECT * FROM applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if row is None:
            return None
        return ApplicationRecord(
            application_id=row["application_id"],
            source=row["source"],
            job_text=row["job_text"],
            requirements=JobRequirements.model_validate(json.loads(row["requirements_json"])),
            profile_snapshot=row["profile_snapshot"],
            gap_analysis=GapAnalysis.model_validate(json.loads(row["gap_analysis_json"])),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def close(self) -> None:
        """Close the repository connection."""

        self._connection.close()

    def __enter__(self) -> "SQLiteApplicationRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


ApplicationRepository = SQLiteApplicationRepository


def deterministic_application_id(
    *,
    source: str,
    job_text: str,
    requirements: JobRequirements | Mapping[str, Any],
) -> str:
    """Build a stable non-secret identifier from application source snapshots."""

    validated_requirements = JobRequirements.model_validate(requirements)
    payload = {
        "source": source.strip(),
        "job_text": job_text,
        "requirements": validated_requirements.model_dump(mode="json"),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"app-{digest[:24]}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
