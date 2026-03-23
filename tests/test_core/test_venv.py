"""Tests for project virtual environment management."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from urika.core.venv import create_project_venv, get_venv_env, is_venv_enabled


class TestCreateProjectVenv:
    def test_creates_venv_directory(self, tmp_path: Path) -> None:
        venv_path = create_project_venv(tmp_path)
        assert venv_path == tmp_path / ".venv"
        assert venv_path.exists()
        assert (venv_path / "bin").exists()

    def test_returns_existing_venv_without_recreating(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "marker").write_text("existing")
        result = create_project_venv(tmp_path)
        assert result == venv_dir
        assert (venv_dir / "marker").exists()

    def test_venv_has_system_site_packages(self, tmp_path: Path) -> None:
        venv_path = create_project_venv(tmp_path)
        cfg = venv_path / "pyvenv.cfg"
        assert cfg.exists()
        content = cfg.read_text()
        assert "include-system-site-packages = true" in content


class TestGetVenvEnv:
    def _write_toml(self, project_dir: Path, venv_enabled: bool) -> None:
        """Write a urika.toml with environment.venv setting."""
        from urika.core.workspace import _write_toml

        data: dict = {"project": {"name": "test"}}
        if venv_enabled:
            data["environment"] = {"venv": True}
        _write_toml(project_dir / "urika.toml", data)

    def test_returns_none_when_no_toml(self, tmp_path: Path) -> None:
        assert get_venv_env(tmp_path) is None

    def test_returns_none_when_venv_not_enabled(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, venv_enabled=False)
        assert get_venv_env(tmp_path) is None

    def test_returns_none_when_venv_enabled_but_no_venv_dir(
        self, tmp_path: Path
    ) -> None:
        self._write_toml(tmp_path, venv_enabled=True)
        assert get_venv_env(tmp_path) is None

    def test_returns_env_dict_when_venv_exists(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, venv_enabled=True)
        venv_dir = tmp_path / ".venv"
        venv_bin = venv_dir / "bin"
        venv_bin.mkdir(parents=True)

        env = get_venv_env(tmp_path)
        assert env is not None
        assert env["VIRTUAL_ENV"] == str(venv_dir)
        assert str(venv_bin) in env["PATH"]
        # venv bin should be first in PATH
        assert env["PATH"].startswith(str(venv_bin))

    def test_removes_pythonhome(self, tmp_path: Path) -> None:
        self._write_toml(tmp_path, venv_enabled=True)
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)

        with patch.dict(os.environ, {"PYTHONHOME": "/some/path"}):
            env = get_venv_env(tmp_path)
            assert env is not None
            assert "PYTHONHOME" not in env

    def test_returns_none_on_malformed_toml(self, tmp_path: Path) -> None:
        (tmp_path / "urika.toml").write_text("this is not valid toml {{{{")
        assert get_venv_env(tmp_path) is None


class TestIsVenvEnabled:
    def test_false_when_no_toml(self, tmp_path: Path) -> None:
        assert is_venv_enabled(tmp_path) is False

    def test_false_when_not_configured(self, tmp_path: Path) -> None:
        from urika.core.workspace import _write_toml

        _write_toml(tmp_path / "urika.toml", {"project": {"name": "test"}})
        assert is_venv_enabled(tmp_path) is False

    def test_true_when_enabled(self, tmp_path: Path) -> None:
        from urika.core.workspace import _write_toml

        _write_toml(
            tmp_path / "urika.toml",
            {"project": {"name": "test"}, "environment": {"venv": True}},
        )
        assert is_venv_enabled(tmp_path) is True

    def test_false_on_malformed_toml(self, tmp_path: Path) -> None:
        (tmp_path / "urika.toml").write_text("bad toml {{")
        assert is_venv_enabled(tmp_path) is False
