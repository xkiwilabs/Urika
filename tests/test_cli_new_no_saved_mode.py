"""Tests that ``urika new`` no longer pre-fills the privacy mode prompt.

Phase 12: there is no system-wide default privacy mode any more.
``urika new`` always asks the user fresh.  In ``--json`` mode (no
interactive prompts), the implicit fallback is ``open``.
"""

from __future__ import annotations

import inspect

from urika.cli import project_new


def test_project_new_module_does_not_use_saved_mode_pre_fill():
    """The module source should no longer mention the legacy
    ``_saved_mode`` / ``_saved_hint`` variables — those came from the
    old "default privacy mode" pre-fill which is gone."""
    src = inspect.getsource(project_new)
    assert "_saved_mode" not in src
    assert "_saved_hint" not in src
    # The privacy-mode prompt should ask fresh — no "(saved default: …)"
    # hint in the prompt label.
    assert "(saved default:" not in src


def test_get_default_privacy_does_not_carry_mode_into_project_new():
    """get_default_privacy() returns no ``mode`` key, so any code in
    project_new that reads ``_saved_privacy.get("mode", ...)`` would
    just get the default — and the source no longer does so."""
    src = inspect.getsource(project_new)
    assert '_saved_privacy.get("mode"' not in src
