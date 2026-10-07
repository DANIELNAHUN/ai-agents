from typing import Any

from cv_agents.extractor import (
    create_job_requirements_extractor,
    extract_job_requirements,
)
from cv_agents.models import JobRequirements


def test_extract_job_requirements_accepts_injected_invocation() -> None:
    captured: dict[str, Any] = {}

    def invoke(request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        return {
            "structured_response": {
                "summary": "Build APIs.",
                "required_skills": ["Python"],
            }
        }

    result = extract_job_requirements("Build APIs with Python.", invoke=invoke)

    assert isinstance(result, JobRequirements)
    assert result.required_skills == ["Python"]
    assert "<job_description>" in captured["messages"][0]["content"]


def test_factory_passes_pydantic_schema_to_langchain(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("cv_agents.extractor.create_agent", fake_create_agent)

    agent = create_job_requirements_extractor(model=object())

    assert agent is not None
    assert captured["response_format"] is JobRequirements
    assert captured["tools"] == []
