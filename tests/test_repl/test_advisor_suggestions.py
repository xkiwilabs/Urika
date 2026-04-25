"""Tests for advisor suggestion parsing, storage, and run integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click

from urika.repl_session import ReplSession


# ── CLI advisor offer-to-run ──────────────────────────────────────────


class TestCliOfferToRunAdvisorSuggestions:
    """Tests for _offer_to_run_advisor_suggestions in cli.py."""

    def test_no_suggestions_does_nothing(self) -> None:
        from urika.cli import _offer_to_run_advisor_suggestions

        # Plain text with no JSON — should return without prompting
        _offer_to_run_advisor_suggestions(
            "Just a plain response.", "proj", Path("/tmp")
        )

    def test_decline_does_not_run(self, tmp_path: Path) -> None:
        from urika.cli import _offer_to_run_advisor_suggestions

        advisor_output = (
            '```json\n{"suggestions": [{"name": "exp-1", "method": "test"}]}\n```'
        )
        with patch(
            "urika.cli.run_advisor._prompt_numbered",
            return_value="No \u2014 I'll run later with urika run",
        ):
            # Should not call run or create_experiment
            _offer_to_run_advisor_suggestions(
                advisor_output, "proj", tmp_path
            )

    def test_accept_creates_experiment_and_runs(self, tmp_path: Path) -> None:
        from urika.cli import _offer_to_run_advisor_suggestions

        advisor_output = (
            '```json\n{"suggestions": [{"name": "exp-007", "method": "do stuff"}]}\n```'
        )

        mock_exp = MagicMock()
        mock_exp.experiment_id = "exp-007"

        with (
            patch(
                "urika.cli.run_advisor._prompt_numbered",
                return_value="Yes \u2014 start running now",
            ),
            patch(
                "urika.core.experiment.create_experiment",
                return_value=mock_exp,
            ) as mock_create,
            patch("urika.cli.run_advisor.click.Context") as mock_ctx_cls,
        ):
            mock_ctx = MagicMock()
            invoked_kwargs = {}

            def fake_invoke(func, **kwargs):
                invoked_kwargs.update(kwargs)

            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx

            _offer_to_run_advisor_suggestions(
                advisor_output, "my-project", tmp_path
            )

        mock_create.assert_called_once()
        assert invoked_kwargs["experiment_id"] == "exp-007"
        assert invoked_kwargs["project"] == "my-project"

    def test_cancel_does_not_crash(self, tmp_path: Path) -> None:
        from urika.cli import _offer_to_run_advisor_suggestions

        advisor_output = (
            '```json\n{"suggestions": [{"name": "exp-1"}]}\n```'
        )
        with patch("urika.cli.run_advisor._prompt_numbered", side_effect=click.Abort):
            # Should not raise
            _offer_to_run_advisor_suggestions(
                advisor_output, "proj", tmp_path
            )


# ── REPL session ──────────────────────────────────────────────────────


class TestPendingSuggestions:
    """Tests for storing and clearing advisor suggestions in the session."""

    def test_pending_suggestions_empty_by_default(self) -> None:
        session = ReplSession()
        assert session.pending_suggestions == []

    def test_pending_suggestions_cleared_on_load_project(
        self, tmp_path: Path
    ) -> None:
        session = ReplSession()
        session.pending_suggestions = [{"name": "exp-007"}]
        session.load_project(tmp_path, "new-project")
        assert session.pending_suggestions == []

    def test_pending_suggestions_stored(self) -> None:
        session = ReplSession()
        suggestions = [
            {"name": "exp-007-switch-policy", "method": "Build switch detector"},
            {"name": "exp-008-teammate", "method": "Infer teammate intentions"},
        ]
        session.pending_suggestions = suggestions
        assert len(session.pending_suggestions) == 2
        assert session.pending_suggestions[0]["name"] == "exp-007-switch-policy"


class TestOfferToRunSuggestions:
    """Tests for _offer_to_run_suggestions in repl.py."""

    def test_no_suggestions_does_nothing(self) -> None:
        from urika.repl import _offer_to_run_suggestions

        session = ReplSession()
        # Text with no JSON suggestions block
        _offer_to_run_suggestions(session, "Just a plain text response.")
        assert session.pending_suggestions == []

    def test_parses_and_stores_suggestions(self) -> None:
        from urika.repl import _offer_to_run_suggestions

        session = ReplSession()
        session.load_project(Path("/tmp/test"), "test-project")
        advisor_output = """Here's my analysis.

```json
{
  "suggestions": [
    {"name": "exp-007-switch", "method": "Build switch detector"},
    {"name": "exp-008-teammate", "method": "Infer teammates"}
  ]
}
```
"""
        # Decline to run so we just test storage
        with patch(
            "urika.repl_commands._prompt_numbered",
            return_value="No \u2014 I'll run later with /run",
        ):
            _offer_to_run_suggestions(session, advisor_output)

        assert len(session.pending_suggestions) == 2
        assert session.pending_suggestions[0]["name"] == "exp-007-switch"
        assert session.pending_suggestions[1]["name"] == "exp-008-teammate"

    def test_cancel_does_not_crash(self) -> None:
        from urika.repl import _offer_to_run_suggestions

        session = ReplSession()
        session.load_project(Path("/tmp/test"), "test-project")
        advisor_output = '```json\n{"suggestions": [{"name": "exp-1"}]}\n```'

        with patch(
            "urika.repl_commands._prompt_numbered", side_effect=click.Abort
        ):
            # Should not raise
            _offer_to_run_suggestions(session, advisor_output)

        # Suggestions should still be stored even if user cancelled the prompt
        assert len(session.pending_suggestions) == 1

    def test_yes_triggers_cmd_run(self) -> None:
        from urika.repl import _offer_to_run_suggestions

        session = ReplSession()
        session.load_project(Path("/tmp/test"), "test-project")
        advisor_output = '```json\n{"suggestions": [{"name": "exp-1", "method": "test"}]}\n```'

        with (
            patch(
                "urika.repl_commands._prompt_numbered",
                return_value="Yes \u2014 start running now",
            ),
            patch("urika.repl_commands.cmd_run") as mock_run,
        ):
            _offer_to_run_suggestions(session, advisor_output)
            mock_run.assert_called_once_with(session, "")


class TestCmdRunWithPendingSuggestions:
    """Tests that /run uses pending suggestions instead of re-calling advisor."""

    def test_creates_experiment_from_suggestion(self, tmp_path: Path) -> None:
        from urika.repl_commands import cmd_run

        session = ReplSession()
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / "experiments").mkdir()
        session.load_project(project_dir, "test-project")
        session.pending_suggestions = [
            {"name": "exp-007-switch", "method": "Build a switch detector"},
            {"name": "exp-008-teammate", "method": "Infer teammates"},
        ]

        created_exp_id = "exp-007-switch"
        mock_exp = MagicMock()
        mock_exp.experiment_id = created_exp_id

        invoked_kwargs = {}

        def fake_invoke(func, **kwargs):
            invoked_kwargs.update(kwargs)

        with (
            patch("urika.repl.commands_run._prompt_numbered", return_value="Run with defaults"),
            patch("urika.repl.commands_run._load_run_defaults", return_value={
                "max_turns": 5, "auto_mode": "checkpoint"
            }),
            patch("urika.core.experiment.create_experiment", return_value=mock_exp) as mock_create,
            patch("urika.repl.commands_run.click.Context") as mock_ctx_cls,
            patch("urika.core.experiment.list_experiments", return_value=[]),
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx

            cmd_run(session, "")

        # Should have created experiment from first suggestion
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        # Check positional or keyword args for name
        name_val = call_kwargs.kwargs.get("name", "")
        assert "exp-007-switch" in name_val

        # Should pass that experiment_id to cli_run
        assert invoked_kwargs["experiment_id"] == created_exp_id

        # Should have consumed first suggestion, kept second
        assert len(session.pending_suggestions) == 1
        assert session.pending_suggestions[0]["name"] == "exp-008-teammate"

    def test_no_suggestions_passes_none_experiment_id(self, tmp_path: Path) -> None:
        from urika.repl_commands import cmd_run

        session = ReplSession()
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / "experiments").mkdir()
        session.load_project(project_dir, "test-project")
        # No pending suggestions
        session.pending_suggestions = []

        invoked_kwargs = {}

        def fake_invoke(func, **kwargs):
            invoked_kwargs.update(kwargs)

        with (
            patch("urika.repl.commands_run._prompt_numbered", return_value="Run with defaults"),
            patch("urika.repl.commands_run._load_run_defaults", return_value={
                "max_turns": 5, "auto_mode": "checkpoint"
            }),
            patch("urika.repl.commands_run.click.Context") as mock_ctx_cls,
            patch("urika.core.experiment.list_experiments", return_value=[]),
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx

            cmd_run(session, "")

        # Without suggestions, experiment_id should be None (normal flow)
        assert invoked_kwargs["experiment_id"] is None
