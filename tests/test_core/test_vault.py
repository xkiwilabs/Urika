"""Tests for the tiered secrets vault.

Covers three-tier resolution (process env -> project -> global), backend
selection, sidecar metadata, deletion semantics, the known-secrets
registry, and file permissions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def vault_module():
    """Import urika.core.vault fresh; clears the cached _global_backend."""
    from urika.core import vault as vault_mod

    # Reset the lru_cache on the global backend selector so tests that
    # monkeypatch _keyring_available get a clean view.
    vault_mod._global_backend.cache_clear()
    yield vault_mod
    vault_mod._global_backend.cache_clear()


@pytest.fixture
def SecretsVault(vault_module):
    return vault_module.SecretsVault


@pytest.fixture
def FileBackend(vault_module):
    return vault_module.FileBackend


def _new_vault(SecretsVault, tmp_path: Path, **kwargs):
    """Create a SecretsVault wired to a tmp global path + meta path."""
    global_path = kwargs.pop("global_path", tmp_path / "global.env")
    meta_path = kwargs.pop("meta_path", tmp_path / "secrets-meta.toml")
    vault = SecretsVault(global_path=global_path, **kwargs)
    vault._meta_path = meta_path
    return vault


class TestProcessEnvWins:
    def test_returns_value_from_os_environ(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.setenv("MY_KEY", "from-env")
        vault = _new_vault(SecretsVault, tmp_path)
        # Even with global set, process env wins.
        # Bypass set_global so we don't overwrite os.environ.
        vault._global_backend.set("MY_KEY", "from-global")
        assert vault.get("MY_KEY") == "from-env"


class TestProjectOverridesGlobal:
    def test_project_wins_over_global(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        proj = tmp_path / "proj"
        proj.mkdir()
        vault = _new_vault(SecretsVault, tmp_path, project_path=proj)
        vault.set_global("MY_KEY", "global-value")
        # set_project also pokes os.environ; clear so we test resolution
        # through tiers rather than tier 1.
        monkeypatch.delenv("MY_KEY", raising=False)
        vault.set_project("MY_KEY", "project-value", project_path=proj)
        monkeypatch.delenv("MY_KEY", raising=False)
        assert vault.get("MY_KEY") == "project-value"


class TestGlobalFallback:
    def test_returns_global_when_no_process_or_project(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault.set_global("MY_KEY", "global-value")
        # set_global pokes os.environ; clear so tier 3 is the source.
        monkeypatch.delenv("MY_KEY", raising=False)
        assert vault.get("MY_KEY") == "global-value"


class TestNotFound:
    def test_returns_none_when_unset_everywhere(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        assert vault.get("MY_KEY") is None


class TestListWithOrigins:
    def test_origin_badges_per_secret(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.setenv("FROM_ENV", "x")
        monkeypatch.delenv("FROM_GLOBAL", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault._global_backend.set("FROM_GLOBAL", "y")
        # Make sure FROM_GLOBAL isn't accidentally in process env.
        monkeypatch.delenv("FROM_GLOBAL", raising=False)
        items = vault.list_with_origins()
        origins = {i["name"]: i["origin"] for i in items}
        assert origins["FROM_ENV"] == "process"
        assert origins["FROM_GLOBAL"] == "global"

    def test_project_origin_for_project_secret(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("PROJ_KEY", raising=False)
        proj = tmp_path / "proj"
        proj.mkdir()
        vault = _new_vault(SecretsVault, tmp_path, project_path=proj)
        vault.set_project("PROJ_KEY", "v", project_path=proj)
        monkeypatch.delenv("PROJ_KEY", raising=False)
        items = vault.list_with_origins()
        origins = {i["name"]: i["origin"] for i in items}
        assert origins["PROJ_KEY"] == "project"

    def test_masked_preview_present_for_set_keys(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("LONG_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault._global_backend.set("LONG_KEY", "abcdefghijklmnop")
        monkeypatch.delenv("LONG_KEY", raising=False)
        items = vault.list_with_origins()
        entry = next(i for i in items if i["name"] == "LONG_KEY")
        assert entry["set"] is True
        assert "***" in entry["masked_preview"]
        assert "abcdefghijklmnop" not in entry["masked_preview"]


class TestKeyringBackendSelection:
    def test_falls_back_to_file_when_keyring_unavailable(
        self, monkeypatch, vault_module
    ) -> None:
        monkeypatch.setattr(vault_module, "_keyring_available", lambda: False)
        vault_module._global_backend.cache_clear()
        backend = vault_module._global_backend()
        assert isinstance(backend, vault_module.FileBackend)


class TestPermissions:
    def test_file_backend_chmods_to_0600(self, tmp_path, FileBackend) -> None:
        path = tmp_path / "global.env"
        backend = FileBackend(path=path)
        backend.set("X", "y")
        mode = path.stat().st_mode & 0o777
        assert oct(mode) == "0o600"


class TestKnownSecretsRegistry:
    def test_unset_known_secrets_appear_in_list_with_origin_unset(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HUGGINGFACE_HUB_TOKEN"]:
            monkeypatch.delenv(k, raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        items = vault.list_with_origins()
        names = {i["name"]: i for i in items}
        assert names["ANTHROPIC_API_KEY"]["origin"] == "unset"
        assert names["ANTHROPIC_API_KEY"]["set"] is False
        # Has description from registry
        assert names["ANTHROPIC_API_KEY"]["description"]


class TestMetadataSidecar:
    def test_set_global_records_description_and_timestamp(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault.set_global("MY_KEY", "value", description="for testing")
        meta = vault.get_metadata("MY_KEY")
        assert meta["description"] == "for testing"
        assert "T" in meta["last_modified"]  # ISO 8601

    def test_set_global_with_empty_description_preserves_existing(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault.set_global("MY_KEY", "v1", description="initial")
        vault.set_global("MY_KEY", "v2", description="")  # don't blank
        assert vault.get_metadata("MY_KEY")["description"] == "initial"

    def test_delete_global_removes_metadata(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault.set_global("MY_KEY", "v", description="d")
        vault.delete_global("MY_KEY")
        meta = vault.get_metadata("MY_KEY")
        # After delete, no metadata remains for the key.
        assert meta == {} or meta.get("description", "") == ""


class TestDeleteOSEnvironBehavior:
    def test_delete_unsets_environ_for_vault_set_keys(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = _new_vault(SecretsVault, tmp_path)
        vault.set_global("MY_KEY", "value")
        assert os.environ.get("MY_KEY") == "value"
        vault.delete_global("MY_KEY")
        assert "MY_KEY" not in os.environ

    def test_delete_raises_for_process_env_set_keys(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.setenv("MY_KEY", "from-shell")
        vault = _new_vault(SecretsVault, tmp_path)
        # Key is in process env, not in vault.
        with pytest.raises(RuntimeError, match="shell environment"):
            vault.delete_global("MY_KEY")

    def test_delete_unsets_vault_value_when_both_set(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        # Process env wins for get(), but if user explicitly deletes-global,
        # the vault value goes away while process env stays.
        monkeypatch.setenv("MY_KEY", "from-shell")
        vault = _new_vault(SecretsVault, tmp_path)
        # Bypass set_global to avoid os.environ sync; we want
        # "vault has value AND process has value" state.
        vault._global_backend.set("MY_KEY", "vault-value")
        assert vault.get("MY_KEY") == "from-shell"  # process wins
        vault.delete_global("MY_KEY")
        # Vault entry gone, process env still set.
        assert vault.get("MY_KEY") == "from-shell"


class TestMaskValue:
    def test_short_value_fully_masked(self, vault_module) -> None:
        assert vault_module.mask_value("abc") == "***"

    def test_long_value_shows_first6_last4(self, vault_module) -> None:
        result = vault_module.mask_value("sk-ant-1234567890ABCD")
        assert result.startswith("sk-ant")
        assert result.endswith("ABCD")
        assert "***" in result

    def test_empty_value(self, vault_module) -> None:
        assert vault_module.mask_value("") == ""


class TestProjectAutoDiscovery:
    def test_project_secrets_file_picked_up_when_present(
        self, monkeypatch, tmp_path, SecretsVault
    ) -> None:
        monkeypatch.delenv("PROJ_KEY", raising=False)
        proj = tmp_path / "proj"
        (proj / ".urika").mkdir(parents=True)
        # Pre-write a project secrets file directly.
        (proj / ".urika" / "secrets.env").write_text("PROJ_KEY=hello\n")
        vault = _new_vault(SecretsVault, tmp_path, project_path=proj)
        assert vault.get("PROJ_KEY") == "hello"
