"""Shared error classification for agent SDK adapters.

Extracted verbatim from ``urika.agents.adapters.claude_sdk`` in v0.7.1
so all adapters (Claude, OpenAI, Google) classify errors identically.
"""

from __future__ import annotations

import re

# Patterns to detect actionable API errors from stderr / error messages.
_RATE_LIMIT_PATTERNS = [
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"429", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"overloaded", re.IGNORECASE),
    re.compile(r"capacity", re.IGNORECASE),
]
_AUTH_PATTERNS = [
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"401", re.IGNORECASE),
    re.compile(r"api.?key", re.IGNORECASE),
    re.compile(r"not.?logged.?in", re.IGNORECASE),
    re.compile(r"login", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"invalid.*key", re.IGNORECASE),
]
_BILLING_PATTERNS = [
    re.compile(r"billing", re.IGNORECASE),
    re.compile(r"credit", re.IGNORECASE),
    re.compile(r"payment", re.IGNORECASE),
    re.compile(r"subscription", re.IGNORECASE),
    re.compile(r"quota", re.IGNORECASE),
]
# Transient network/server errors that should pause-and-resume rather
# than fail the experiment outright. Pre-v0.3.2 a 5xx or a connection
# blip mid-loop killed a multi-hour autonomous run.
_TRANSIENT_PATTERNS = [
    re.compile(r"\b5\d\d\b"),
    re.compile(r"connection.{0,3}reset", re.IGNORECASE),
    re.compile(r"connection.{0,3}refused", re.IGNORECASE),
    re.compile(r"connection.{0,3}aborted", re.IGNORECASE),
    re.compile(r"timeout", re.IGNORECASE),
    re.compile(r"timed.?out", re.IGNORECASE),
    re.compile(r"temporarily.{0,3}unavailable", re.IGNORECASE),
    re.compile(r"service.{0,3}unavailable", re.IGNORECASE),
    re.compile(r"bad.?gateway", re.IGNORECASE),
    re.compile(r"gateway.{0,3}timeout", re.IGNORECASE),
    # SDK message-relay weirdness seen against local endpoints: the
    # transport surfaces ``Exception("Claude Code returned an error in
    # error result: success")`` — a ResultMessage flagged is_error with
    # a bogus error string. Not a real API error; pause-and-resume.
    re.compile(r"returned an error in error result", re.IGNORECASE),
    re.compile(r"fatal error in message reader", re.IGNORECASE),
]
# Configuration errors that need user action to fix but shouldn't
# look like generic failures in the dashboard. Treated as a separate
# category so the UI can render an actionable hint.
_CONFIG_PATTERNS = [
    re.compile(r"MissingPrivateEndpointError", re.IGNORECASE),
    re.compile(r"APIKeyRequiredError", re.IGNORECASE),
    re.compile(r"private.{0,3}endpoint.{0,30}configured", re.IGNORECASE),
]


def classify_error(error_text: str) -> str:
    """Classify an SDK error into a user-friendly category.

    Returns one of: ``"rate_limit"``, ``"auth"``, ``"billing"``,
    ``"transient"``, ``"config"``, ``"unknown"``.

    The ``"transient"`` and ``"config"`` categories were added in
    v0.3.2 — pre-v0.3.2 a 5xx mid-loop or a missing-endpoint config
    error fell into ``"unknown"`` and silently failed the experiment.
    The orchestrator loop's pause path treats both as pausable.
    """
    for pat in _CONFIG_PATTERNS:
        if pat.search(error_text):
            return "config"
    for pat in _RATE_LIMIT_PATTERNS:
        if pat.search(error_text):
            return "rate_limit"
    for pat in _AUTH_PATTERNS:
        if pat.search(error_text):
            return "auth"
    for pat in _BILLING_PATTERNS:
        if pat.search(error_text):
            return "billing"
    for pat in _TRANSIENT_PATTERNS:
        if pat.search(error_text):
            return "transient"
    return "unknown"
