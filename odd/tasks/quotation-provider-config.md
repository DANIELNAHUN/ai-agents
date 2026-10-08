# Quotation Provider Configuration

## Objective

Allow the quotation agent to construct a LangChain chat model from dotenv or
process environment settings for OpenAI-compatible self-hosted providers,
including Ollama, OmniRoute, and FreeLLM, while preserving injected offline
boundaries for tests.

## Problem

The quotation package currently accepts only an injected model or invocation.
Its configuration stores a model name and timeout, but it has no provider
selection, base URL, API key loading, or live model factory.

## Why

The user needs to run the quotation agent locally against self-hosted or
OpenAI-compatible endpoints during manual testing without hard-coding a
provider in the workflow.

## Scope

- Add provider, model, base URL, and API key configuration for the quotation package.
- Support `openai`, `ollama`, `omniroute`, and `freellm` through the OpenAI-compatible LangChain adapter.
- Keep `.env` ignored and provide a documented local `.env.example` with placeholders.
- Add a lazy model factory that never performs a network call during construction.
- Preserve callable/model injection and all offline tests.
- Document manual invocation and provider-specific endpoint requirements.

## Constraints

- API keys may be stored in the local `.env` for this user-requested development setup, but must never be committed or printed.
- Ollama defaults to its local OpenAI-compatible endpoint; OmniRoute and FreeLLM require an explicitly configured base URL unless their endpoint is supplied by the user.
- No provider-specific package beyond the existing `langchain-openai` adapter is required.
- No live provider call is part of the automated test suite.
- Technical artifacts remain in English.

## Authorized scope and route

- Repository: `ai-agents`.
- Package: `personal/profesional/quotations/`.
- Route: delegated direct implementation with one writer for the multi-file behavior.
- Delivery strategy: `ask-on-risk`; chain strategy: `stacked-to-main`.
- Work-unit commit must include code, tests, and documentation.

## Checklist

- [x] PC-001 — Add validated provider configuration and dotenv variables.
- [x] PC-002 — Add lazy OpenAI-compatible model factory and exports.
- [x] PC-003 — Add tests, `.env.example`, and manual usage documentation.

## Acceptance criteria

- `load_config` resolves provider aliases, model, timeout, base URL, and API key from dotenv/process environment with process values taking precedence.
- Supported providers include `openai`, `ollama`, `omniroute`, and `freellm`.
- Ollama has a safe local default base URL; other self-hosted providers can be configured without code changes.
- API keys are represented safely and are not exposed by configuration reprs or error messages.
- The model factory lazily imports `ChatOpenAI`, creates no network connection, and passes the configured base URL, model, timeout, and key.
- Tests remain offline and verify provider-specific configuration and factory arguments.
- The README and `.env.example` explain how to run a manual live smoke test.

## Applicable checks

- `uv run pytest`
- `python -m compileall src tests`
- `uv run ruff check src tests`
- Manual factory smoke test with a monkeypatched adapter; no real credential or endpoint required.

## Progress

| Task | Status | Verification | Commit |
| --- | --- | --- | --- |
| PC-001 | verified | `uv run pytest` (108 passed); `python -m compileall src tests` (passed); `uv run ruff check src tests` (passed) | pending |
| PC-002 | verified | Factory kwargs/no-network tests passed; parent spot-check `uv run pytest` (108 passed) | pending |
| PC-003 | verified | README and `.env.example` reviewed; `git diff --check` passed | pending |

## Next step

Implementation and verification are complete. Record the work-unit commit
identity here and in the Engram mirror after committing the focused provider
configuration change.
