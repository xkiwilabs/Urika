"""Tests for urika.core.git.gh_create_repo (the ``gh`` wrapper)."""

from __future__ import annotations

from unittest.mock import patch


def test_gh_create_returns_install_hint_when_gh_missing(tmp_path):
    """When `gh` binary is not on PATH, return install_hint without raising."""
    from urika.core.git import gh_create_repo

    with patch("urika.core.git.shutil.which", return_value=None):
        result = gh_create_repo(tmp_path, name="my-proj", public=False)
    assert result.ok is False
    assert result.install_hint is not None
    assert "gh auth login" in result.install_hint or "brew" in result.install_hint
    assert result.error == "gh CLI not found"


def test_gh_create_returns_auth_error_when_gh_unauthed(tmp_path):
    """When `gh auth status` reports not-authed, surface the message."""
    from urika.core.git import gh_create_repo

    with (
        patch("urika.core.git.shutil.which", return_value="/usr/bin/gh"),
        patch("urika.core.git._gh_check_auth", return_value=False),
    ):
        result = gh_create_repo(tmp_path, name="my-proj", public=False)
    assert result.ok is False
    assert "gh auth login" in (result.install_hint or "")


def test_gh_create_invokes_correct_command(tmp_path):
    """Happy-path: gh repo create with the right args (private by default)."""
    from urika.core.git import gh_create_repo

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        import subprocess as sp

        return sp.CompletedProcess(
            args=cmd, returncode=0, stdout="https://github.com/u/p", stderr=""
        )

    with (
        patch("urika.core.git.shutil.which", return_value="/usr/bin/gh"),
        patch("urika.core.git._gh_check_auth", return_value=True),
        patch("urika.core.git.subprocess.run", side_effect=fake_run),
    ):
        result = gh_create_repo(tmp_path, name="my-proj", public=False)
    assert result.ok is True
    cmd = captured["cmd"]
    assert cmd[0:3] == ["gh", "repo", "create"]
    assert "my-proj" in cmd
    assert "--private" in cmd
    assert "--public" not in cmd
    assert "--source" in cmd
    assert "--push" in cmd


def test_gh_create_public_flag(tmp_path):
    from urika.core.git import gh_create_repo

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        import subprocess as sp

        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with (
        patch("urika.core.git.shutil.which", return_value="/usr/bin/gh"),
        patch("urika.core.git._gh_check_auth", return_value=True),
        patch("urika.core.git.subprocess.run", side_effect=fake_run),
    ):
        gh_create_repo(tmp_path, name="my-proj", public=True)
    assert "--public" in captured["cmd"]
    assert "--private" not in captured["cmd"]


def test_gh_create_propagates_gh_error(tmp_path):
    """When `gh repo create` returns non-zero, surface stderr verbatim."""
    from urika.core.git import gh_create_repo

    def fake_run(cmd, **kw):
        import subprocess as sp

        return sp.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="HTTP 422: repo already exists",
        )

    with (
        patch("urika.core.git.shutil.which", return_value="/usr/bin/gh"),
        patch("urika.core.git._gh_check_auth", return_value=True),
        patch("urika.core.git.subprocess.run", side_effect=fake_run),
    ):
        result = gh_create_repo(tmp_path, name="my-proj", public=False)
    assert result.ok is False
    assert "already exists" in (result.error or "")
