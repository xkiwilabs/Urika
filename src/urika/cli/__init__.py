"""Urika CLI — Click command group and all commands."""

# Import everything from the legacy module to maintain backward compatibility.
# All external imports (from urika.cli import X) continue to work.
from urika.cli._legacy import *  # noqa: F401,F403
from urika.cli._legacy import (
    # The Click group
    cli,
    # Internal helpers (underscore-prefixed, not covered by star import)
    _offer_to_run_advisor_suggestions,
    _UrikaCLI,
    _run_builder_agent_loop,
    _ingest_knowledge,
    _determine_next_experiment,
    # Command functions imported by repl_commands.py
    new,
    status,
    run,
    report,
    inspect,
    logs,
    finalize,
    config_command,
    notifications_command,
    update_project,
    present,
    dashboard,
)

# Helpers now live in _helpers.py — re-export for backward compatibility
from urika.cli._helpers import (  # noqa: F401
    _make_on_message,
    _record_agent_usage,
    _sanitize_project_name,
    _projects_dir,
    _resolve_project,
    _ensure_project,
    _test_endpoint,
    _prompt_numbered,
    _prompt_path,
)
