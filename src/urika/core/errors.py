"""Typed errors used across the Urika codebase.

Every user-facing error derives from :class:`UrikaError` so the CLI can
render them uniformly (error line + optional hint line) without leaking
tracebacks. Subclasses exist for pattern-matching in except-blocks; they
carry no extra behavior beyond their type.

Usage:
    raise ConfigError(
        "urika.toml not found",
        hint="Run `urika new <name>` to create a project.",
    )

The CLI's top-level handler inspects ``hint`` to show actionable advice
alongside the error message. If no hint is set, only the message is shown.
"""

from __future__ import annotations


class UrikaError(Exception):
    """Base class for Urika's user-facing errors.

    The optional ``hint`` is displayed by the CLI's error renderer on a
    separate line below the message. Keep hints short and actionable —
    one sentence, imperative voice.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ConfigError(UrikaError):
    """Project or runtime configuration is missing, malformed, or invalid."""


class AgentError(UrikaError):
    """An agent invocation failed for a reason worth surfacing to the user.

    Typical causes: rate limits, auth failures, billing issues, the agent
    returning malformed output when structured output was required.
    """


class ValidationError(UrikaError):
    """User or LLM-produced input failed a structural or semantic check."""
