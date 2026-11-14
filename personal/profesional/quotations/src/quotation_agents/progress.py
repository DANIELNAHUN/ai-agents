"""Compact, step-by-step progress output for agent calls.

Each agent call runs inside a named step. The step prints one start line, live
status while it runs (model calls, tool calls, elapsed time), and one summary
line with duration and token usage. On a terminal the live status is a single
spinner line updated in place; on other streams each status change is printed
once so logs stay readable.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TextIO

from langchain_core.callbacks import BaseCallbackHandler

SPINNER_INTERVAL_SECONDS = 0.1


class _Symbols:
    def __init__(
        self, start: str, done: str, failed: str, status: str, sep: str, spinner: str
    ) -> None:
        self.start = start
        self.done = done
        self.failed = failed
        self.status = status
        self.sep = sep
        self.spinner = spinner


UNICODE_SYMBOLS = _Symbols("▸", "✔", "✖", "·", "·", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
ASCII_SYMBOLS = _Symbols(">", "OK", "FAIL", "-", "|", "|/-\\")


class _StepState:
    def __init__(self) -> None:
        self.status = "starting"
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0


class ProgressCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that feeds agent events to a reporter."""

    def __init__(self, reporter: ProgressReporter) -> None:
        self._reporter = reporter

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self._reporter._model_started()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        input_tokens, output_tokens = _token_usage(response)
        self._reporter._model_finished(input_tokens, output_tokens)

    def on_tool_start(self, serialized: Any, input_str: str, **kwargs: Any) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self._reporter._set_status(f"running tool: {name}")


class ProgressReporter:
    """Print compact progress for named agent steps."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._clock = clock
        self._lock = threading.Lock()
        self._state: _StepState | None = None
        self._live = _is_terminal(self._stream)
        self._encoding = getattr(self._stream, "encoding", None) or "utf-8"
        self._symbols = _pick_symbols(self._encoding)
        self.callback = ProgressCallbackHandler(self)

    @property
    def separator(self) -> str:
        """Field separator that the output stream can encode."""

        return self._symbols.sep

    @contextmanager
    def step(self, label: str) -> Iterator[None]:
        """Report one agent step: start line, live status, and summary line."""

        self._state = _StepState()
        sym = self._symbols
        self._write_line(f"  {sym.start} {label}")
        started = self._clock()
        stop = threading.Event()
        spinner = None
        if self._live:
            spinner = threading.Thread(target=self._spin, args=(stop,), daemon=True)
            spinner.start()
        try:
            yield
        except BaseException:
            self._finish(stop, spinner)
            elapsed = self._clock() - started
            self._write_line(f"  {sym.failed} {label} {sym.sep} failed after {elapsed:.1f}s")
            raise
        else:
            self._finish(stop, spinner)
            elapsed = self._clock() - started
            summary = self._usage_summary()
            self._write_line(f"  {sym.done} {label} {sym.sep} {elapsed:.1f}s{summary}")
        finally:
            self._state = None

    def _usage_summary(self) -> str:
        state = self._state
        if state is None or state.model_calls == 0:
            return ""
        calls = "1 model call" if state.model_calls == 1 else f"{state.model_calls} model calls"
        sep = self._symbols.sep
        summary = f" {sep} {calls}"
        if state.input_tokens or state.output_tokens:
            summary += f" {sep} {state.input_tokens:,} in / {state.output_tokens:,} out tokens"
        return summary

    def _model_started(self) -> None:
        state = self._state
        if state is None:
            return
        state.model_calls += 1
        self._set_status(f"waiting for model (call {state.model_calls})")

    def _model_finished(self, input_tokens: int, output_tokens: int) -> None:
        state = self._state
        if state is None:
            return
        state.input_tokens += input_tokens
        state.output_tokens += output_tokens
        self._set_status("processing model response")

    def _set_status(self, status: str) -> None:
        state = self._state
        if state is None or state.status == status:
            return
        state.status = status
        if not self._live:
            self._write_line(f"    {self._symbols.status} {status}")

    def _spin(self, stop: threading.Event) -> None:
        started = time.monotonic()
        frame = 0
        while not stop.wait(SPINNER_INTERVAL_SECONDS):
            state = self._state
            status = state.status if state is not None else ""
            elapsed = time.monotonic() - started
            frames = self._symbols.spinner
            symbol = frames[frame % len(frames)]
            line = f"\r\033[K    {symbol} {status}... {elapsed:.0f}s"
            with self._lock:
                self._stream.write(self._safe(line))
                self._stream.flush()
            frame += 1

    def _finish(self, stop: threading.Event, spinner: threading.Thread | None) -> None:
        stop.set()
        if spinner is not None:
            spinner.join()
            with self._lock:
                self._stream.write("\r\033[K")
                self._stream.flush()

    def _write_line(self, text: str) -> None:
        with self._lock:
            self._stream.write(self._safe(f"{text}\n"))
            self._stream.flush()

    def _safe(self, text: str) -> str:
        """Replace characters the stream encoding cannot represent."""

        try:
            return text.encode(self._encoding, "replace").decode(self._encoding)
        except LookupError:
            return text


def track(agent: Any, reporter: ProgressReporter, label: str) -> Callable[[Any], Any]:
    """Wrap an agent so each invocation runs as a reported step."""

    def run(request: Any) -> Any:
        with reporter.step(label):
            return agent.invoke(request, config={"callbacks": [reporter.callback]})

    return run


def _token_usage(response: Any) -> tuple[int, int]:
    """Return (input, output) tokens from an LLMResult, or zeros when absent."""

    input_tokens = output_tokens = 0
    found = False
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if usage:
                found = True
                input_tokens += int(usage.get("input_tokens", 0))
                output_tokens += int(usage.get("output_tokens", 0))
    if found:
        return input_tokens, output_tokens
    token_usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
    return int(token_usage.get("prompt_tokens", 0)), int(token_usage.get("completion_tokens", 0))


def _pick_symbols(encoding: str) -> _Symbols:
    sample = "".join(
        (
            UNICODE_SYMBOLS.start,
            UNICODE_SYMBOLS.done,
            UNICODE_SYMBOLS.failed,
            UNICODE_SYMBOLS.status,
            UNICODE_SYMBOLS.sep,
            UNICODE_SYMBOLS.spinner,
        )
    )
    try:
        sample.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return ASCII_SYMBOLS
    return UNICODE_SYMBOLS


def _is_terminal(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except (OSError, ValueError):
        return False
