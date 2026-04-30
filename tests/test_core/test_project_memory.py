"""Tests for ``urika.core.project_memory`` (v0.4 Track 2 Phase 1)."""

from __future__ import annotations

from pathlib import Path


def _empty_project(tmp_path: Path) -> Path:
    p = tmp_path / "alpha"
    p.mkdir()
    (p / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n',
        encoding="utf-8",
    )
    return p


def test_load_project_memory_empty_returns_empty_string(tmp_path):
    from urika.core.project_memory import load_project_memory

    proj = _empty_project(tmp_path)
    assert load_project_memory(proj) == ""


def test_save_entry_creates_file_and_index(tmp_path):
    from urika.core.project_memory import (
        index_path,
        list_entries,
        memory_dir,
        save_entry,
    )

    proj = _empty_project(tmp_path)
    save_entry(
        proj,
        mem_type="feedback",
        body="Prefer tree-based models over deep nets",
        description="Method preference",
        slug="methods",
    )
    assert (memory_dir(proj) / "feedback_methods.md").exists()
    assert index_path(proj).exists()
    rows = list_entries(proj)
    assert len(rows) == 1
    assert rows[0]["type"] == "feedback"
    assert "tree-based" in rows[0]["body_preview"]


def test_load_project_memory_renders_block(tmp_path):
    from urika.core.project_memory import load_project_memory, save_entry

    proj = _empty_project(tmp_path)
    save_entry(
        proj,
        mem_type="instruction",
        body="Always cross-validate by subject",
        description="CV strategy",
        slug="cv",
    )
    blob = load_project_memory(proj)
    assert "Project Memory" in blob
    assert "instruction: instruction_cv" in blob
    assert "cross-validate by subject" in blob


def test_parse_marker_persists_and_strips(tmp_path):
    from urika.core.project_memory import (
        list_entries,
        parse_and_persist_memory_markers,
    )

    proj = _empty_project(tmp_path)
    text = (
        "Here's my analysis.\n"
        "<memory type=\"feedback\">User prefers XGBoost over neural nets</memory>\n"
        "Now let's plan the next experiment."
    )
    stripped, written = parse_and_persist_memory_markers(proj, text)
    assert "<memory" not in stripped
    assert "Here's my analysis" in stripped
    assert "Now let's plan" in stripped
    assert len(written) == 1
    rows = list_entries(proj)
    assert rows[0]["type"] == "feedback"


def test_parse_marker_skips_unknown_type(tmp_path):
    from urika.core.project_memory import (
        list_entries,
        parse_and_persist_memory_markers,
    )

    proj = _empty_project(tmp_path)
    text = '<memory type="bogus">should not persist</memory>'
    stripped, written = parse_and_persist_memory_markers(proj, text)
    assert stripped == ""
    assert written == []
    assert list_entries(proj) == []


def test_auto_capture_disabled_strips_but_does_not_persist(tmp_path):
    from urika.core.project_memory import (
        list_entries,
        parse_and_persist_memory_markers,
    )

    proj = _empty_project(tmp_path)
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n'
        "\n[memory]\nauto_capture = false\n",
        encoding="utf-8",
    )
    text = '<memory type="feedback">should be stripped but not saved</memory>'
    stripped, written = parse_and_persist_memory_markers(proj, text)
    assert "<memory" not in stripped
    assert written == []
    assert list_entries(proj) == []


def test_delete_entry_trashes(tmp_path):
    from urika.core.project_memory import delete_entry, save_entry

    proj = _empty_project(tmp_path)
    save_entry(
        proj,
        mem_type="decision",
        body="Excluded subject S012",
        slug="exclude_s012",
    )
    fname = "decision_exclude_s012.md"
    assert delete_entry(proj, fname) is True
    assert not (proj / "memory" / fname).exists()
    assert (proj / "memory" / ".trash" / fname).exists()


def test_save_entry_rejects_unknown_type(tmp_path):
    import pytest

    from urika.core.project_memory import save_entry

    proj = _empty_project(tmp_path)
    with pytest.raises(ValueError):
        save_entry(proj, mem_type="bogus", body="x")


def test_load_memory_includes_multiple_entries_grouped_by_type(tmp_path):
    from urika.core.project_memory import load_project_memory, save_entry

    proj = _empty_project(tmp_path)
    save_entry(proj, mem_type="user", body="Senior researcher", slug="role")
    save_entry(proj, mem_type="feedback", body="Prefers XGBoost", slug="methods")
    save_entry(
        proj,
        mem_type="instruction",
        body="Always cross-validate by subject",
        slug="cv",
    )
    blob = load_project_memory(proj)
    assert "user: user_role" in blob
    assert "feedback: feedback_methods" in blob
    assert "instruction: instruction_cv" in blob
