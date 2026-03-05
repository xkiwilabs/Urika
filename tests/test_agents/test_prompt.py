"""Tests for prompt loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.prompt import load_prompt


class TestLoadPrompt:
    def test_load_simple_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("You are a helpful assistant.")
        result = load_prompt(prompt_file)
        assert result == "You are a helpful assistant."

    def test_load_with_variables(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Working in {project_dir} on {experiment_id}.")
        result = load_prompt(
            prompt_file,
            variables={"project_dir": "/tmp/proj", "experiment_id": "exp-001"},
        )
        assert result == "Working in /tmp/proj on exp-001."

    def test_load_with_no_variables_leaves_placeholders(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Working in {project_dir}.")
        result = load_prompt(prompt_file)
        assert result == "Working in {project_dir}."

    def test_load_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_prompt(tmp_path / "nonexistent.md")

    def test_load_multiline_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("# Title\n\nParagraph one.\n\nParagraph two.\n")
        result = load_prompt(prompt_file)
        assert "# Title" in result
        assert "Paragraph two." in result

    def test_partial_variable_substitution(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Project: {project_dir}, Mode: {mode}.")
        result = load_prompt(prompt_file, variables={"project_dir": "/tmp/proj"})
        assert result == "Project: /tmp/proj, Mode: {mode}."
