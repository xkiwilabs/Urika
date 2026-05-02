"""Tiered secrets vault.

Three-tier resolution:

1. **Process env** (``os.environ``) — wins; preserves existing exports
   and standard CI / ``export`` patterns.
2. **Project-local** ``<project>/.urika/secrets.env`` (chmod 0600) —
   for project-specific credentials. Discovery is automatic: the file's
   existence IS the opt-in.
3. **Global** — OS keyring (preferred when ``keyring`` is installed and
   a probe call works) with ``~/.urika/secrets.env`` (chmod 0600)
   fallback.

Per-secret metadata (description, last_modified, created_via) lives in
sidecar TOML files: ``~/.urika/secrets-meta.toml`` (global) and
``<project>/.urika/secrets-meta.toml`` (project). Plain text;
descriptions are not secrets.

The vault tracks which keys it WROTE during this process's lifetime so
:meth:`SecretsVault.delete_global` only unsets vault-written keys from
``os.environ`` — process-env values (Tier 1) are never touched.
"""

from __future__ import annotations

import os
import re
import tomllib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def mask_value(value: str) -> str:
    """Mask a secret value for display.

    Returns ``"sk-ant-***...***ABCD"`` (first 6, last 4) when the value
    is at least 12 chars; ``"***"`` for shorter non-empty values; empty
    string for empty input.
    """
    if not value:
        return ""
    if len(value) < 12:
        return "***"
    return f"{value[:6]}***...***{value[-4:]}"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file. Skips comments and blank lines.

    Returns an empty dict if the file is missing or unreadable.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            out[key] = value
    except Exception as exc:
        # Unreadable — fall through to "no values" so the caller
        # doesn't crash. But emit at error level: pre-v0.4 this
        # silenced everything (bad permissions, encoding, partial
        # writes), so users with a corrupted secrets.env got "no
        # secrets" with zero diagnostic and their API calls
        # mysteriously failed auth.
        import logging as _logging

        _logging.getLogger(__name__).error(
            "Vault env-file read failed at %s: %s: %s",
            path,
            type(exc).__name__,
            exc,
        )
    return out


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    """Atomically write a KEY=VALUE file with mode 0o600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in values.items()]
    body = "\n".join(lines)
    if body:
        body += "\n"
    path.write_text(body)
    try:
        path.chmod(0o600)
    except Exception:
        # On Windows / unusual filesystems chmod may fail — tolerate.
        pass


def _upsert_env_file(path: Path, key: str, value: str) -> None:
    """Set or update a single key in a KEY=VALUE file, preserving order
    and any comments. Creates the file if missing. chmods to 0o600.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    new_lines: list[str] = []
    found = False
    if path.exists():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                existing_key = stripped.partition("=")[0].strip()
                if existing_key == key:
                    new_lines.append(f"{key}={value}")
                    found = True
                    continue
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _remove_env_key(path: Path, key: str) -> bool:
    """Remove a single key from a KEY=VALUE file. Returns True if a
    matching line was removed, False otherwise.
    """
    if not path.exists():
        return False
    new_lines: list[str] = []
    removed = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.partition("=")[0].strip()
            if existing_key == key:
                removed = True
                continue
        new_lines.append(line)
    path.write_text("\n".join(new_lines) + "\n")
    try:
        path.chmod(0o600)
    except Exception:
        pass
    return removed


# ---------------------------------------------------------------------------
# Sidecar metadata (TOML)
# ---------------------------------------------------------------------------


_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_quote_string(value: str) -> str:
    """Encode a string as a TOML basic string."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _format_toml_value(value) -> str:
    if isinstance(value, str):
        return _toml_quote_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(v) for v in value) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")


def _toml_table_header(name: str) -> str:
    if _TOML_BARE_KEY.match(name):
        return f"[{name}]"
    return f"[{_toml_quote_string(name)}]"


def _toml_key(name: str) -> str:
    if _TOML_BARE_KEY.match(name):
        return name
    return _toml_quote_string(name)


def _read_meta(path: Path) -> dict[str, dict]:
    """Read sidecar metadata TOML. Empty dict if missing/unreadable."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        # Pre-v0.4 this silently dropped to ``return {}`` so a
        # corrupted secrets-meta.toml left the dashboard with no
        # diagnostic about why metadata (descriptions, last_modified,
        # required_by_tools) had vanished. Log so the failure mode is
        # at least observable.
        import logging as _logging

        _logging.getLogger(__name__).error(
            "Vault meta-file read failed at %s: %s: %s",
            path,
            type(exc).__name__,
            exc,
        )
        return {}
    # Top-level keys are secret names; values are tables (dicts).
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _write_meta(path: Path, meta: dict[str, dict]) -> None:
    """Write sidecar metadata TOML. chmods to 0o600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    for name, fields in meta.items():
        chunks.append(_toml_table_header(name))
        for k, v in fields.items():
            chunks.append(f"{_toml_key(k)} = {_format_toml_value(v)}")
        chunks.append("")  # trailing blank line per table
    body = "\n".join(chunks).rstrip() + "\n" if chunks else ""
    path.write_text(body)
    try:
        path.chmod(0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class SecretsBackend(Protocol):
    """Minimal interface every global-tier backend implements."""

    def get(self, name: str) -> Optional[str]: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...
    def list_keys(self) -> list[str]: ...


# Default location for the global file backend.
_DEFAULT_GLOBAL_PATH = Path.home() / ".urika" / "secrets.env"


class FileBackend:
    """KEY=VALUE file backend at ``~/.urika/secrets.env`` (chmod 0600).

    Reuses the existing layout from the v0.3 ``urika.core.secrets``
    module so existing files are picked up without migration.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT_GLOBAL_PATH

    def get(self, name: str) -> Optional[str]:
        return _read_env_file(self.path).get(name)

    def set(self, name: str, value: str) -> None:
        _upsert_env_file(self.path, name, value)

    def delete(self, name: str) -> bool:
        return _remove_env_key(self.path, name)

    def list_keys(self) -> list[str]:
        return list(_read_env_file(self.path).keys())


# Sidecar index file for the keyring backend (which can't enumerate).
_KEYRING_INDEX_PATH = Path.home() / ".urika" / "secrets-index.txt"


def _keyring_available() -> bool:
    """Probe the OS keyring. ``True`` if importable AND a no-op call
    works (some Linux setups have ``keyring`` installed but no dbus).
    """
    try:
        import keyring  # type: ignore[import-not-found]
        import keyring.errors  # type: ignore[import-not-found]  # noqa: F401
    except Exception:
        return False
    try:
        keyring.get_password("urika", "__probe__")
        return True
    except Exception:
        return False


class KeyringBackend:
    """OS keyring backend.

    Maps to macOS Keychain / Linux Secret Service / Windows Credential
    Manager via the ``keyring`` package. The keyring API doesn't natively
    list passwords, so this backend maintains a sidecar index file at
    ``~/.urika/secrets-index.txt`` (one name per line).
    """

    SERVICE_NAME = "urika"

    def __init__(self, index_path: Optional[Path] = None) -> None:
        self.index_path = Path(index_path) if index_path else _KEYRING_INDEX_PATH

    def get(self, name: str) -> Optional[str]:
        import keyring  # type: ignore[import-not-found]

        return keyring.get_password(self.SERVICE_NAME, name)

    def set(self, name: str, value: str) -> None:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(self.SERVICE_NAME, name, value)
        self._index_add(name)

    def delete(self, name: str) -> bool:
        import keyring  # type: ignore[import-not-found]
        import keyring.errors  # type: ignore[import-not-found]

        try:
            keyring.delete_password(self.SERVICE_NAME, name)
            self._index_remove(name)
            return True
        except keyring.errors.PasswordDeleteError:
            self._index_remove(name)
            return False
        except Exception:
            return False

    def list_keys(self) -> list[str]:
        if not self.index_path.exists():
            return []
        try:
            return [
                line.strip()
                for line in self.index_path.read_text().splitlines()
                if line.strip()
            ]
        except Exception:
            return []

    # ----- sidecar index helpers --------------------------------------------

    def _index_add(self, name: str) -> None:
        names = set(self.list_keys())
        names.add(name)
        self._index_write(sorted(names))

    def _index_remove(self, name: str) -> None:
        names = set(self.list_keys())
        names.discard(name)
        self._index_write(sorted(names))

    def _index_write(self, names: list[str]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text("\n".join(names) + ("\n" if names else ""))
        try:
            self.index_path.chmod(0o600)
        except Exception:
            pass


@lru_cache(maxsize=1)
def _global_backend() -> SecretsBackend:
    """Pick the best available global backend.

    Order: OS keyring (when ``keyring`` is installed AND a probe call
    succeeds) -> file fallback at ``~/.urika/secrets.env``.

    Cached per-process; tests can call ``_global_backend.cache_clear()``.
    """
    if _keyring_available():
        return KeyringBackend()
    return FileBackend()


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------


_DEFAULT_META_PATH = Path.home() / ".urika" / "secrets-meta.toml"


class SecretsVault:
    """Tiered secrets resolver: process env -> project .env -> global store.

    Process env always wins so existing exports / CI patterns keep
    working unchanged. Project-local overrides global. Global uses OS
    keyring when ``keyring`` is installed, else a chmod-0600 file at
    ``~/.urika/secrets.env``.

    Per design decision #4, the vault tracks which keys it WROTE during
    this process's lifetime (in :attr:`_our_writes`) so
    :meth:`delete_global` only unsets vault-written keys from
    ``os.environ`` — process-env values (Tier 1) are never touched.
    """

    def __init__(
        self,
        project_path: Optional[Path] = None,
        global_path: Optional[Path] = None,
    ) -> None:
        self.project_path = Path(project_path) if project_path else None
        # If the caller supplied a custom global_path, force the file
        # backend rooted at that path (test isolation). Otherwise pick
        # the best available backend.
        if global_path is not None:
            self._global_backend: SecretsBackend = FileBackend(path=Path(global_path))
        else:
            self._global_backend = _global_backend()
        # Sidecar metadata path. Tests override this via ``vault._meta_path``.
        self._meta_path = _DEFAULT_META_PATH
        # In-process record of keys this vault wrote to os.environ.
        self._our_writes: set[str] = set()

    # ----- resolution -------------------------------------------------------

    def get(self, name: str) -> Optional[str]:
        """Resolve a secret by name. Returns None if unset in all tiers."""
        # Tier 1: process env (always wins).
        val = os.environ.get(name)
        if val:
            return val
        # Tier 2: project (if project path configured + file exists).
        if self.project_path is not None:
            proj_path = self.project_path / ".urika" / "secrets.env"
            if proj_path.exists():
                pval = _read_env_file(proj_path).get(name)
                if pval:
                    return pval
        # Tier 3: global.
        gval = self._global_backend.get(name)
        return gval if gval else None

    # ----- listing ----------------------------------------------------------

    def list_keys(self) -> list[str]:
        """Return all secret names known to the vault (union across tiers).

        Values are not returned — names only, for discovery.
        """
        names: set[str] = set()
        # Tier 1: process env — only names that look like env-var keys.
        # We can't tell which env vars are "secrets" so we only include
        # names that are also configured somewhere or in the known-secrets
        # registry. To stay simple, list_keys returns the union of project
        # + global; consumers that want process-env data use
        # list_with_origins.
        if self.project_path is not None:
            proj_path = self.project_path / ".urika" / "secrets.env"
            if proj_path.exists():
                names.update(_read_env_file(proj_path).keys())
        names.update(self._global_backend.list_keys())
        return sorted(names)

    def list_with_origins(
        self,
        referenced_names: Optional[set[str]] = None,
    ) -> list[dict]:
        """Return per-secret rows with origin badges for the dashboard.

        Each row is::

            {
                "name": "ANTHROPIC_API_KEY",
                "origin": "process" | "project" | "global" | "unset",
                "set": True/False,
                "description": "...",
                "last_modified": "...",  # ISO 8601 or ""
                "masked_preview": "sk-ant-***...***WXYZ",  # only when set
            }

        Candidate set rule (no shell-env leak):

        * A name is included IFF it is stored in the vault (file or
          keyring backend), stored in the project tier (project
          ``secrets.env``), OR explicitly listed in ``referenced_names``.
        * ``os.environ`` is no longer a candidate source. Random shell
          exports never appear unless they are also vault-stored or
          explicitly referenced. (Process env still wins resolution —
          its origin is reported as ``"process"`` for candidate names
          that happen to be exported — but it cannot introduce new
          candidates.)
        * ``referenced_names`` is the set of env-var names the caller
          discovered from configured surfaces (privacy endpoints,
          notifications channels). These appear with ``origin="unset"``
          when not stored anywhere, so the dashboard's "Used by your
          config" section surfaces names users still need to fill in.
        """
        global_keys = set(self._global_backend.list_keys())
        proj_values: dict[str, str] = {}
        if self.project_path is not None:
            proj_path = self.project_path / ".urika" / "secrets.env"
            if proj_path.exists():
                proj_values = _read_env_file(proj_path)

        ref = set(referenced_names) if referenced_names else set()

        # Candidates: vault-stored (project + global) ∪ explicitly
        # referenced. Pointedly NOT including os.environ or KNOWN_SECRETS.
        names: set[str] = set()
        names.update(global_keys)
        names.update(proj_values.keys())
        names.update(ref)

        global_meta = _read_meta(self._meta_path)

        rows: list[dict] = []
        for name in sorted(names):
            proc_val = os.environ.get(name)
            we_poked = name in self._our_writes
            in_proj = name in proj_values
            in_global = name in global_keys

            # Origin precedence for display:
            #   1. process env (only when NOT vault-poked — those are
            #      real shell exports the user controls externally)
            #   2. project store
            #   3. global store
            #   4. unset (known-secrets registry only)
            if proc_val and not we_poked:
                origin = "process"
                value = proc_val
            elif in_proj:
                origin = "project"
                value = proj_values[name]
            elif in_global:
                origin = "global"
                value = self._global_backend.get(name) or ""
            else:
                origin = "unset"
                value = ""

            description = ""
            last_modified = ""
            if name in global_meta:
                description = global_meta[name].get("description", "") or ""
                last_modified = global_meta[name].get("last_modified", "") or ""
            if not description:
                # Fall back to the known-secrets registry blurb when we
                # have no per-secret metadata.
                from urika.core.known_secrets import KNOWN_SECRETS

                if name in KNOWN_SECRETS:
                    description = KNOWN_SECRETS[name]

            rows.append(
                {
                    "name": name,
                    "origin": origin,
                    "set": origin != "unset",
                    "description": description,
                    "last_modified": last_modified,
                    "masked_preview": mask_value(value) if value else "",
                }
            )
        return rows

    # ----- mutation ---------------------------------------------------------

    def set_global(self, name: str, value: str, description: str = "") -> None:
        """Write a secret to the global store + sidecar metadata.

        Also pokes ``os.environ[name] = value`` so an in-process check
        sees the new value immediately. Tracks the write in
        :attr:`_our_writes` so :meth:`delete_global` knows it owns the
        ``os.environ`` entry.

        If ``description`` is empty, preserves any existing description.
        """
        self._global_backend.set(name, value)
        os.environ[name] = value
        self._our_writes.add(name)

        meta = _read_meta(self._meta_path)
        existing = meta.get(name, {})
        new_entry = dict(existing)
        if description:
            new_entry["description"] = description
        elif "description" not in new_entry:
            new_entry["description"] = ""
        new_entry["last_modified"] = _utcnow_iso()
        if "created_via" not in new_entry:
            new_entry["created_via"] = "vault"
        if "required_by_tools" not in new_entry:
            new_entry["required_by_tools"] = []
        meta[name] = new_entry
        _write_meta(self._meta_path, meta)

    def set_project(
        self,
        name: str,
        value: str,
        project_path: Path,
        description: str = "",
    ) -> None:
        """Write a secret to ``<project>/.urika/secrets.env``.

        Updates ``os.environ`` so in-process consumers see it
        immediately. Project metadata lives in
        ``<project>/.urika/secrets-meta.toml``.
        """
        proj_dir = Path(project_path) / ".urika"
        proj_dir.mkdir(parents=True, exist_ok=True)
        proj_secrets = proj_dir / "secrets.env"
        _upsert_env_file(proj_secrets, name, value)
        os.environ[name] = value
        self._our_writes.add(name)

        proj_meta_path = proj_dir / "secrets-meta.toml"
        meta = _read_meta(proj_meta_path)
        existing = meta.get(name, {})
        new_entry = dict(existing)
        if description:
            new_entry["description"] = description
        elif "description" not in new_entry:
            new_entry["description"] = ""
        new_entry["last_modified"] = _utcnow_iso()
        if "created_via" not in new_entry:
            new_entry["created_via"] = "vault"
        if "required_by_tools" not in new_entry:
            new_entry["required_by_tools"] = []
        meta[name] = new_entry
        _write_meta(proj_meta_path, meta)

    def delete_global(self, name: str) -> bool:
        """Remove a secret from the global store + metadata.

        Returns ``True`` if the global entry existed.

        ``os.environ`` semantics (decision #4):

        * If the vault wrote the key during this process (it's in
          :attr:`_our_writes`), unset it from ``os.environ`` after
          deletion.
        * If the key is in process env, never written by the vault,
          AND the vault has no entry for it, raise
          :class:`RuntimeError` — the user set it in the shell and
          must clear via ``unset KEY`` themselves.
        * If the key has both a vault entry AND a process-env value
          set independently of the vault, remove the vault value but
          leave ``os.environ`` alone so the shell value continues to
          win on subsequent ``get()`` calls.
        """
        in_proc = name in os.environ
        we_wrote = name in self._our_writes
        vault_has = self._global_backend.get(name) is not None

        if in_proc and not we_wrote and not vault_has:
            # Pure process-env-only — the vault doesn't own this key.
            raise RuntimeError(
                f"Cannot delete process-env-set secret — clear via "
                f"`unset {name}` in your shell environment, then refresh."
            )

        existed = self._global_backend.delete(name)

        # Strip metadata sidecar entry.
        meta = _read_meta(self._meta_path)
        if name in meta:
            meta.pop(name, None)
            _write_meta(self._meta_path, meta)

        # Unset os.environ ONLY for vault-written keys. If the shell ALSO
        # set it independently of the vault, leave os.environ alone.
        if we_wrote:
            try:
                del os.environ[name]
            except KeyError:
                pass
            self._our_writes.discard(name)

        return existed

    def delete_project(self, name: str, project_path: Path) -> bool:
        """Remove a secret from the project store.

        Returns ``True`` if the project entry existed.
        """
        proj_dir = Path(project_path) / ".urika"
        proj_secrets = proj_dir / "secrets.env"
        existed = _remove_env_key(proj_secrets, name)
        proj_meta_path = proj_dir / "secrets-meta.toml"
        meta = _read_meta(proj_meta_path)
        if name in meta:
            meta.pop(name, None)
            _write_meta(proj_meta_path, meta)
        if name in self._our_writes:
            try:
                del os.environ[name]
            except KeyError:
                pass
            self._our_writes.discard(name)
        return existed

    # ----- metadata ---------------------------------------------------------

    def get_metadata(self, name: str) -> dict:
        """Return sidecar metadata for ``name`` ({} if none)."""
        meta = _read_meta(self._meta_path)
        return dict(meta.get(name, {}))


__all__ = [
    "SecretsVault",
    "FileBackend",
    "KeyringBackend",
    "mask_value",
    "_global_backend",
    "_keyring_available",
]
