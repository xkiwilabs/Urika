"""Tests for urika.core.git.scan_for_secrets."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _init_with_identity(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    return work


def _stage(work: Path, name: str, content: str) -> None:
    (work / name).write_text(content)
    subprocess.run(["git", "-C", str(work), "add", name], check=True)


def test_clean_files_return_no_matches(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(work, "main.py", "def hello():\n    print('hi')\n")
    _stage(work, "data.csv", "col1,col2\n1,2\n3,4\n")
    assert scan_for_secrets(work) == []


def test_anthropic_key_detected(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(
        work,
        "config.py",
        "API_KEY = 'sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx'\n",
    )
    matches = scan_for_secrets(work)
    assert len(matches) == 1
    assert matches[0].file == "config.py"
    assert matches[0].line == 1
    assert matches[0].pattern_name == "anthropic_api_key"
    # Preview is masked - first 8 + last 4
    assert "sk-ant-a" in matches[0].preview
    assert "uvwx" in matches[0].preview


def test_openai_key_detected(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(
        work,
        "openai_config.py",
        "key='sk-1234567890abcdefghijklmnopqrstuvwxyz1234567890'\n",
    )
    matches = scan_for_secrets(work)
    assert any(m.pattern_name == "openai_api_key" for m in matches)


def test_github_pat_detected(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(work, "deploy.sh", "TOKEN=ghp_1234567890abcdefghij1234567890abcd1A\n")
    matches = scan_for_secrets(work)
    assert any(m.pattern_name == "github_pat" for m in matches)


def test_aws_access_key_detected(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(work, "aws.yml", "access_key: AKIAIOSFODNN7EXAMPLE\n")
    matches = scan_for_secrets(work)
    assert any(m.pattern_name == "aws_access_key_id" for m in matches)


def test_only_staged_files_scanned(tmp_path):
    """Files on disk but not git-add'd are skipped - we scan ``git show :<path>``."""
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    (work / "leaked.py").write_text(
        "key='sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx'\n"
    )
    # Not staged.
    assert scan_for_secrets(work) == []
    # Now stage it.
    subprocess.run(["git", "-C", str(work), "add", "leaked.py"], check=True)
    matches = scan_for_secrets(work)
    assert len(matches) == 1


def test_binary_files_skipped(tmp_path):
    """Binary files (PNGs, etc.) are skipped - we don't want false positives
    on random bytes that happen to match a pattern, and reading large binaries
    is wasteful."""
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    # PNG header + random bytes
    (work / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    subprocess.run(["git", "-C", str(work), "add", "img.png"], check=True)
    assert scan_for_secrets(work) == []


def test_multiple_matches_in_one_file(tmp_path):
    from urika.core.git import scan_for_secrets

    work = _init_with_identity(tmp_path)
    _stage(
        work,
        "secrets.env",
        "ANTHROPIC=sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx\n"
        "GITHUB=ghp_1234567890abcdefghij1234567890abcd1A\n",
    )
    matches = scan_for_secrets(work)
    pattern_names = {m.pattern_name for m in matches}
    assert "anthropic_api_key" in pattern_names
    assert "github_pat" in pattern_names
