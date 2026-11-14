"""Progress reporting for agent steps."""

from __future__ import annotations

import io
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from quotation_agents.progress import ProgressReporter, track


class FakeClock:
    def __init__(self, *values: float) -> None:
        self.values = list(values)

    def __call__(self) -> float:
        return self.values.pop(0)


def _reporter(*clock_values: float) -> tuple[ProgressReporter, io.StringIO]:
    stream = io.StringIO()
    return ProgressReporter(stream=stream, clock=FakeClock(*clock_values)), stream


def _llm_result(input_tokens: int, output_tokens: int) -> LLMResult:
    message = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_step_prints_start_and_elapsed_completion():
    reporter, stream = _reporter(10.0, 13.25)

    with reporter.step("Requirement inference agent"):
        pass

    output = stream.getvalue()
    assert "▸ Requirement inference agent" in output
    assert "✔ Requirement inference agent · 3.2s" in output


def test_step_reports_failure_and_reraises():
    reporter, stream = _reporter(0.0, 2.0)

    with pytest.raises(RuntimeError, match="boom"):
        with reporter.step("Decomposition agent · Backend"):
            raise RuntimeError("boom")

    assert "✖ Decomposition agent · Backend · failed after 2.0s" in stream.getvalue()


def test_callback_reports_model_wait_tools_and_token_usage():
    reporter, stream = _reporter(0.0, 5.0)

    with reporter.step("Commercial synthesis agent"):
        reporter.callback.on_chat_model_start({}, [[]], run_id=uuid4())
        reporter.callback.on_llm_end(_llm_result(1200, 300), run_id=uuid4())
        reporter.callback.on_tool_start({"name": "lookup_client"}, "", run_id=uuid4())
        reporter.callback.on_chat_model_start({}, [[]], run_id=uuid4())
        reporter.callback.on_llm_end(_llm_result(1500, 200), run_id=uuid4())

    output = stream.getvalue()
    assert "waiting for model (call 1)" in output
    assert "running tool: lookup_client" in output
    assert "waiting for model (call 2)" in output
    assert (
        "✔ Commercial synthesis agent · 5.0s · 2 model calls · 2,700 in / 500 out tokens"
        in output
    )


def test_step_falls_back_to_ascii_when_stream_cannot_encode_symbols():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    reporter = ProgressReporter(stream=stream, clock=FakeClock(0.0, 1.0))

    with reporter.step("Requirement inference agent"):
        reporter.callback.on_chat_model_start({}, [[]], run_id=uuid4())

    stream.flush()
    output = raw.getvalue().decode("cp1252")
    assert "> Requirement inference agent" in output
    assert "- waiting for model (call 1)" in output
    assert "OK Requirement inference agent | 1.0s | 1 model call" in output


def test_track_runs_agent_inside_a_step_with_progress_callbacks():
    reporter, stream = _reporter(0.0, 1.0)
    calls: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    class Agent:
        def invoke(self, request: dict[str, Any], config: dict[str, Any] | None = None) -> str:
            calls.append((request, config))
            return "result"

    run = track(Agent(), reporter, "Requirement inference agent")

    assert run({"messages": []}) == "result"
    assert calls == [({"messages": []}, {"callbacks": [reporter.callback]})]
    assert "✔ Requirement inference agent · 1.0s" in stream.getvalue()
