from typing import Any

from cv_agents.generator import generate_tailored_cv_content
from cv_agents.models import GapAnalysis, JobRequirements, TailoredCVContent


def test_tailored_content_generator_uses_injected_invoke_boundary() -> None:
    captured: dict[str, Any] = {}
    requirements = JobRequirements(summary="Build backend APIs", required_skills=["Python"])
    gap_analysis = GapAnalysis(fit_score=80)

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        return {
            "structured_response": {
                "experience_fractalia": {
                    "summary": "Built Python automations.",
                    "bullets": ["Created API integrations."],
                    "tools": ["Python"],
                },
                "experience_cableclub": {
                    "summary": "Led internal systems development.",
                    "bullets": [],
                    "tools": ["Docker"],
                },
            }
        }

    result = generate_tailored_cv_content(
        "# Profile\n\nPython and Docker experience.",
        requirements,
        gap_analysis,
        invoke=invoke,
    )

    assert isinstance(result, TailoredCVContent)
    assert result.experience_fractalia.tools == ["Python"]
    assert "<canonical_profile_markdown>" in captured["messages"][0]["content"]
    assert "<gap_analysis_json>" in captured["messages"][0]["content"]
