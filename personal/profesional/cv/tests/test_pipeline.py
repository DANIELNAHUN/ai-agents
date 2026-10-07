from pathlib import Path
from typing import Any

from cv_agents.config import CVConfig
from cv_agents.models import GapAnalysis, JobRequirements
from cv_agents.pipeline import run_fast_analysis
from cv_agents.repository import SQLiteApplicationRepository


def test_fast_pipeline_uses_fake_boundaries_and_persists_one_record(tmp_path: Path) -> None:
    config = CVConfig(vault_root=tmp_path, profile_path="profile.md", model="test-model")
    repository = SQLiteApplicationRepository(tmp_path / "applications.sqlite3")
    captured: dict[str, Any] = {}

    def extract(request: dict[str, Any]) -> dict[str, Any]:
        captured["extract"] = request
        return {
            "structured_response": JobRequirements(
                summary="Build APIs.",
                required_skills=["Python"],
            )
        }

    def analyze(request: dict[str, Any]) -> dict[str, Any]:
        captured["analyze"] = request
        return {"structured_response": GapAnalysis(fit_score=75)}

    record = run_fast_analysis(
        "Build APIs with Python.",
        config=config,
        profile_markdown="# Profile\n\nPython backend engineer.",
        extractor_invoke=extract,
        analyzer_invoke=analyze,
        repository=repository,
    )

    assert record.application_id.startswith("app-")
    assert repository.get_application(record.application_id) == record
    assert "<job_description>" in captured["extract"]["messages"][0]["content"]
    assert "<canonical_profile_markdown>" in captured["analyze"]["messages"][0]["content"]
    repository.close()
