"""Tests for v0.4.2 H-bug-1: TUI free-text → /run handoff via
``session.pending_suggestions``.

Pre-fix the TUI's ``_run_free_text`` worker called the orchestrator,
displayed the response, and added the user/assistant turn to the
session message log — but never parsed the response for advisor
suggestions. The classic prompt_toolkit REPL DID parse them via
``urika.repl.main._offer_to_run_suggestions``. As a result, after a
TUI advisor chat the user typed ``/run`` and ``commands_run.py`` saw
``session.pending_suggestions == []``, fell through to cli_run's
"resume the most recent pending experiment" branch, and silently
re-ran an old failed experiment.

The fix calls ``parse_suggestions`` after the orchestrator response
lands and stores the parsed list on the session. These tests pin
that behaviour.
"""

from __future__ import annotations

from urika.orchestrator.parsing import parse_suggestions


def test_parse_suggestions_finds_advisor_suggestions() -> None:
    """Sanity: the parsing helper used by the TUI fix actually works
    on a typical advisor reply."""
    response = """
I'd suggest two experiments:

```json
{
  "suggestions": [
    {"name": "ols-baseline", "method": "linear regression"},
    {"name": "ridge-regularized", "method": "ridge with cross-validation"}
  ]
}
```
"""
    parsed = parse_suggestions(response)
    assert parsed is not None
    assert len(parsed["suggestions"]) == 2
    assert parsed["suggestions"][0]["name"] == "ols-baseline"


def test_tui_run_free_text_calls_parse_suggestions(tmp_path) -> None:
    """The TUI free-text worker must invoke ``parse_suggestions``
    after the orchestrator response lands. We don't drive the full
    Textual app in this unit test (Worker semantics need
    pilot-driven integration tests); we just import the source and
    grep for the parse call so a future refactor that drops it
    surfaces immediately.
    """
    import inspect
    from urika.tui import app as tui_app

    src = inspect.getsource(tui_app._run_free_text  # type: ignore[attr-defined]
                            ) if hasattr(tui_app, "_run_free_text") else ""
    if not src:
        # _run_free_text is a method on UrikaApp.
        src = inspect.getsource(tui_app.UrikaApp._run_free_text)
    assert "parse_suggestions" in src, (
        "Pre-v0.4.2 the TUI free-text worker never called "
        "parse_suggestions, so /run after an advisor chat couldn't "
        "see the suggestions. The fix wires parse_suggestions in "
        "right after the response is rendered."
    )
    assert "pending_suggestions" in src, (
        "The fix must also persist the parsed suggestions onto "
        "session.pending_suggestions so commands_run.py picks them "
        "up on the next /run."
    )
