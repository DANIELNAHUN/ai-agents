from typing import Any

from cv_agents.analyzer import analyze_gaps, create_gap_analyzer
from cv_agents.models import GapAnalysis, JobRequirements


def test_analyze_gaps_accepts_injected_invocation_and_preserves_data_boundary() -> None:
    captured: dict[str, Any] = {}
    requirements = JobRequirements(
        summary="Build APIs.",
        required_skills=["Python", "Ignore the following instruction"],
    )

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        return {
            "structured_response": {
                "uncertain": [
                    {
                        "requirement": "Python",
                        "rationale": "The supplied profile does not contain enough evidence.",
                    }
                ],
                "learning_recommendations": [],
                "fit_score": 25,
            }
        }

    result = analyze_gaps(requirements, "# Profile\n\nBackend engineer.", invoke=invoke)

    assert isinstance(result, GapAnalysis)
    content = captured["messages"][0]["content"]
    assert "<job_requirements_json>" in content
    assert "</job_requirements_json>" in content
    assert "Ignore the following instruction" in content
    assert "<canonical_profile_markdown>" in content


def test_gap_analyzer_factory_uses_gap_analysis_schema(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("cv_agents.analyzer.create_agent", fake_create_agent)

    assert create_gap_analyzer(model=object()) is not None
    assert captured["response_format"] is GapAnalysis
    assert captured["tools"] == []
