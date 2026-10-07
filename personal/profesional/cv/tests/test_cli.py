from pathlib import Path
from types import SimpleNamespace

from cv_agents.cli import main
from cv_agents.models import GapAnalysis, JobRequirements
from cv_agents.repository import ApplicationRecord


def _record() -> ApplicationRecord:
    return ApplicationRecord(
        application_id="app-test",
        source="manual job text",
        job_text="Build APIs.",
        requirements=JobRequirements(summary="Build APIs.", required_skills=["Python"]),
        profile_snapshot="# Profile",
        gap_analysis=GapAnalysis(fit_score=60),
        status="analyzed",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_cli_accepts_text_fallback_and_prints_json(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "cv_agents.cli.load_config",
        lambda: SimpleNamespace(model="test-model"),
    )
    monkeypatch.setattr("cv_agents.cli.run_fast_analysis", lambda *args, **kwargs: _record())

    result = main(["--text", "Build APIs.", "--db-path", str(tmp_path / "apps.sqlite3")])

    captured = capsys.readouterr()
    assert result == 0
    assert '"application_id": "app-test"' in captured.out
    assert captured.err == ""


def test_cli_returns_non_zero_for_pipeline_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "cv_agents.cli.load_config",
        lambda: SimpleNamespace(model="test-model"),
    )

    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("cv_agents.cli.run_fast_analysis", fail)

    result = main(["--text", "Build APIs."])

    assert result == 1
    assert "provider unavailable" in capsys.readouterr().err
