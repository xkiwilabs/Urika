"""Backward-compatible thin wrapper over :mod:`urika.core.vault`.

The v0.3 module exposed four module-level functions backed by a
``KEY=VALUE`` file at ``~/.urika/secrets.env``. v0.4 reframes that as
the FileBackend tier of the new :class:`SecretsVault`, with optional
OS-keyring support behind the ``pip install urika[keyring]`` extra.

This module preserves the v0.3 public API (``save_secret``,
``get_secret``, ``load_secrets``, ``list_secrets``) so existing
callers — CLI commands, dashboard endpoints, notifications — keep
working unchanged. Tests that monkeypatch
``urika.core.secrets.save_secret`` or ``urika.core.secrets.load_secrets``
also continue to pass.
"""

from __future__ import annotations

import os
from pathlib import Path

from urika.core.vault import SecretsVault, _DEFAULT_GLOBAL_PATH

# Public path for compatibility with v0.3 callers that referenced
# ``_SECRETS_PATH`` directly (and the tests that monkeypatch it).
# Only honored as a backend override when it has been monkeypatched
# away from the default — otherwise we'd force FileBackend even on
# systems where the keyring tier is preferred.
_SECRETS_PATH = Path.home() / ".urika" / "secrets.env"


def _vault() -> SecretsVault:
    """Return a fresh vault on each call.

    If a test (or other caller) has monkeypatched ``_SECRETS_PATH``
    away from the default home location, force a FileBackend rooted
    there so the redirection actually takes effect. Otherwise let
    :class:`SecretsVault` pick the best available global backend
    (OS keyring when ``keyring`` is installed and probes successfully,
    file fallback otherwise) — matching the path that
    ``urika config secret`` uses to write.
    """
    if _SECRETS_PATH != _DEFAULT_GLOBAL_PATH:
        return SecretsVault(global_path=_SECRETS_PATH)
    return SecretsVault()


def load_secrets() -> None:
    """Load global vault entries into ``os.environ``.

    Existing process-env values are preserved (Tier 1 always wins).
    Silently no-ops if the global store is empty or unreadable.
    """
    vault = _vault()
    for name in vault.list_keys():
        if name in os.environ:
            continue
        value = vault.get(name)
        if value:
            os.environ[name] = value


def save_secret(key: str, value: str) -> None:
    """Save or update a secret in the global vault store.

    Mirrors v0.3 semantics: also updates ``os.environ[key]`` so the
    value is immediately available in-process.
    """
    _vault().set_global(key, value)


def get_secret(key: str) -> str:
    """Resolve a secret by name. Returns empty string if unset."""
    val = os.environ.get(key, "")
    if val:
        return val
    # Re-resolve through the vault so users who edited the file by
    # hand still see the value (matches v0.3 "force reload" behavior).
    resolved = _vault().get(key)
    if resolved:
        os.environ[key] = resolved
        return resolved
    return ""


def list_secrets() -> dict[str, str]:
    """Return ``{name: '****'}`` for all global vault entries.

    Values are masked to preserve the v0.3 contract — no caller has
    ever expected real values from this function.
    """
    return {name: "****" for name in _vault().list_keys()}
