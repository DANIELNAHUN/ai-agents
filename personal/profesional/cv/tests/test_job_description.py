from dataclasses import dataclass

import httpx
import pytest

from cv_agents.job_description import (
    extract_job_description,
    fetch_job_description,
    html_to_text,
)


@dataclass
class FakeClient:
    response: httpx.Response
    last_url: str | None = None
    last_timeout: float | None = None
    last_headers: dict[str, str] | None = None

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> httpx.Response:
        self.last_url = url
        self.last_timeout = timeout
        self.last_headers = headers
        return self.response


def test_html_to_text_omits_non_visible_content() -> None:
    html = "<h1>Senior Python Engineer</h1><script>ignore me()</script><p>Build APIs</p>"

    assert html_to_text(html) == "Senior Python Engineer\nBuild APIs"


def test_fetch_job_description_uses_timeout_user_agent_and_checks_status() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        text="<main><h1>Role</h1><p>Python</p></main>",
        request=httpx.Request("GET", "https://example.com/jobs/1"),
    )
    client = FakeClient(response)

    result = fetch_job_description(
        "https://example.com/jobs/1",
        timeout_seconds=7,
        user_agent="test-agent",
        client=client,
    )

    assert result == "Role\nPython"
    assert client.last_url == "https://example.com/jobs/1"
    assert client.last_timeout == 7
    assert client.last_headers == {"User-Agent": "test-agent"}


def test_fetch_job_description_raises_for_http_error() -> None:
    response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.com/missing"),
    )
    client = FakeClient(response)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_job_description("https://example.com/missing", client=client)


def test_extract_job_description_accepts_manual_text_fallback() -> None:
    assert extract_job_description("  Build reliable Python services.  ") == (
        "Build reliable Python services."
    )


def test_extract_job_description_does_not_treat_malformed_url_as_fallback() -> None:
    with pytest.raises(ValueError, match="must use http"):
        extract_job_description("https://")
