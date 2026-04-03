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
    _determine_next_experiment,
    # Command functions imported by repl_commands.py
    run,
    report,
    logs,
    finalize,
    config_command,
    notifications_command,
    present,
    dashboard,
)

# Project commands now live in project.py
import urika.cli.project  # noqa: F401
from urika.cli.project import (  # noqa: F401
    new,
    status,
    update_project,
    inspect,
    list_cmd,
    _run_builder_agent_loop,
    _ingest_knowledge,
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
