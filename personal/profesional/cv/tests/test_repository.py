from pathlib import Path

from cv_agents.models import GapAnalysis, JobRequirements
from cv_agents.repository import (
    SQLiteApplicationRepository,
    deterministic_application_id,
)


def _snapshots() -> tuple[JobRequirements, GapAnalysis]:
    return (
        JobRequirements(summary="Build services.", required_skills=["Python"]),
        GapAnalysis(fit_score=80),
    )


def test_repository_round_trip_isolated_by_database_path(tmp_path: Path) -> None:
    requirements, gap_analysis = _snapshots()
    first_path = tmp_path / "first.sqlite3"
    second_path = tmp_path / "second.sqlite3"

    first = SQLiteApplicationRepository(first_path)
    saved = first.save_application(
        "https://example.com/jobs/1",
        job_text="Build services with Python.",
        requirements=requirements,
        profile_snapshot="# Profile\nPython",
        gap_analysis=gap_analysis,
    )
    loaded = first.get_application(saved.application_id)
    first.close()

    second = SQLiteApplicationRepository(second_path)
    assert loaded is not None
    assert loaded.requirements == requirements
    assert loaded.gap_analysis == gap_analysis
    assert loaded.profile_snapshot == "# Profile\nPython"
    assert second.get_application(saved.application_id) is None
    second.close()


def test_deterministic_application_ids_are_stable_and_change_with_source() -> None:
    requirements, _ = _snapshots()

    first = deterministic_application_id(
        source="manual-source",
        job_text="Build services.",
        requirements=requirements,
    )
    same = deterministic_application_id(
        source="manual-source",
        job_text="Build services.",
        requirements=requirements,
    )
    changed = deterministic_application_id(
        source="another-source",
        job_text="Build services.",
        requirements=requirements,
    )

    assert first == same
    assert first.startswith("app-")
    assert first != changed
