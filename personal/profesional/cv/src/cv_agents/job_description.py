"""Retrieve job descriptions and convert untrusted HTML into plain text."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = "cv-agents/0.1 (+job-description-fetcher)"


class JobDescriptionError(RuntimeError):
    """Raised when a job description cannot be safely obtained."""


class HTTPClient(Protocol):
    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> httpx.Response:
        """Retrieve a URL without executing any response content."""


def html_to_text(html: str) -> str:
    """Extract visible text from HTML without executing embedded content."""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_job_description(
    url: str,
    *,
    timeout_seconds: float = 15.0,
    user_agent: str = DEFAULT_USER_AGENT,
    client: HTTPClient | None = None,
) -> str:
    """Fetch a URL and return HTML-derived or plain response text.

    The response is treated only as untrusted input data. No scripts, links, or
    instructions in the response are executed or acted upon.
    """

    _validate_url(url)
    if timeout_seconds <= 0 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be greater than 0 and no greater than 120")

    request_headers = {"User-Agent": user_agent}
    try:
        if client is not None:
            response = client.get(url, timeout=timeout_seconds, headers=request_headers)
        else:
            with httpx.Client(follow_redirects=True) as http_client:
                response = http_client.get(url, timeout=timeout_seconds, headers=request_headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        message = f"Job-description URL returned HTTP {status_code}: {url}"
        raise JobDescriptionError(message) from exc
    except httpx.HTTPError as exc:
        raise JobDescriptionError(f"Unable to retrieve job-description URL {url}: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "xhtml" in content_type or not content_type:
        return html_to_text(response.text)
    return response.text


def extract_job_description(
    source: str,
    *,
    timeout_seconds: float = 15.0,
    user_agent: str = DEFAULT_USER_AGENT,
    client: HTTPClient | None = None,
) -> str:
    """Use an HTTP URL or a non-empty manually supplied text fallback.

    A value that looks like an HTTP(S) URL must be fetched; it is not silently
    reinterpreted as fallback text when the URL is malformed or unavailable.
    """

    candidate = source.strip()
    if not candidate:
        raise ValueError("Job-description source cannot be empty")
    if candidate.lower().startswith(("http://", "https://")):
        return fetch_job_description(
            candidate,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            client=client,
        )
    return candidate


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Job-description URL must use http:// or https:// and include a host")
