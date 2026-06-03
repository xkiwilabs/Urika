"""REPL ``/new`` threads ``--github / --no-github / --public`` (v0.7 sweep).

Pre-sweep ``cmd_new`` invoked ``urika new`` with only ``name``, ``mode``,
``question``, ``data_path``, ``description`` — silently dropping the
v0.6.0 GitHub auto-create flags. A REPL/TUI user could not opt into a
GitHub repo at project-creation time without also setting the global
``[preferences] github_auto_create`` preference.

These tests pin the new flag forwarding by spying on ``click.Context.invoke``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from urika.repl.session import ReplSession


def _invoke_with_spy(session: ReplSession, args: str) -> dict:
    """Run ``cmd_new`` with ``click.Context`` mocked out and return the
    kwargs ``ctx.invoke`` would have received."""
    from urika.repl.commands import cmd_new

    captured: dict = {}

    def fake_invoke(func, **kwargs):  # noqa: ANN001
        captured.update(kwargs)

    with (
        patch("urika.repl_commands.click.Context") as mock_ctx_cls,
        patch("urika.core.registry.ProjectRegistry") as mock_reg_cls,
    ):
        mock_ctx = MagicMock()
        mock_ctx.invoke = fake_invoke
        mock_ctx_cls.return_value = mock_ctx
        mock_reg = MagicMock()
        mock_reg.list_all.return_value = {}
        mock_reg_cls.return_value = mock_reg
        cmd_new(session, args)
    return captured


def test_new_threads_github_true_flag(tmp_path: Path) -> None:
    session = ReplSession()
    kw = _invoke_with_spy(session, "my-proj --github")
    assert kw["github_flag"] is True
    assert kw["public"] is False
    assert kw["name"] == "my-proj"


def test_new_threads_no_github_flag(tmp_path: Path) -> None:
    """``--no-github`` explicitly disables the global preference."""
    session = ReplSession()
    kw = _invoke_with_spy(session, "my-proj --no-github")
    assert kw["github_flag"] is False
    assert kw["public"] is False


def test_new_threads_public_flag(tmp_path: Path) -> None:
    session = ReplSession()
    kw = _invoke_with_spy(session, "my-proj --github --public")
    assert kw["github_flag"] is True
    assert kw["public"] is True


def test_new_no_github_flags_passes_none(tmp_path: Path) -> None:
    """Without any flags, ``github_flag`` must be None so the CLI falls
    back to the global ``[preferences] github_auto_create`` setting —
    the same behaviour as ``urika new`` from a shell."""
    session = ReplSession()
    kw = _invoke_with_spy(session, "my-proj")
    assert kw["github_flag"] is None
    assert kw["public"] is False


def test_new_flag_order_does_not_matter(tmp_path: Path) -> None:
    """Flags before the name token are still recognised."""
    session = ReplSession()
    kw = _invoke_with_spy(session, "--github --public my-proj")
    assert kw["github_flag"] is True
    assert kw["public"] is True
    assert kw["name"] == "my-proj"


def test_new_public_without_github_is_still_forwarded(tmp_path: Path) -> None:
    """``--public`` alone forwards public=True; the CLI then consults
    the global preference for github_flag (matches CLI shell behaviour)."""
    session = ReplSession()
    kw = _invoke_with_spy(session, "my-proj --public")
    assert kw["github_flag"] is None
    assert kw["public"] is True
