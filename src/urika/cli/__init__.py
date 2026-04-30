"""Urika CLI — Click command group and all commands."""

# The Click group definition lives in _base.py
from urika.cli._base import cli, _UrikaCLI  # noqa: F401

# Project commands
import urika.cli.project  # noqa: F401
from urika.cli.project import (  # noqa: F401
    new,
    status,
    update_project,
    inspect,
    list_cmd,
    delete,
    _run_builder_agent_loop,
    _ingest_knowledge,
)

# Run command
import urika.cli.run  # noqa: F401
from urika.cli.run import (  # noqa: F401
    run,
    _determine_next_experiment,
    _offer_to_run_advisor_suggestions,
)

# Agent commands
import urika.cli.agents  # noqa: F401
from urika.cli.agents import (  # noqa: F401
    advisor,
    evaluate,
    plan,
    report,
    present,
    finalize,
    build_tool,
    criteria,
    summarize,
    _run_report_agent,
)

# Config commands
import urika.cli.config  # noqa: F401
from urika.cli.config import (  # noqa: F401
    config_command,
    notifications_command,
    setup_command,
    dashboard,
)

# Data/results commands (includes experiment and venv subgroups)
import urika.cli.data  # noqa: F401
from urika.cli.data import (  # noqa: F401
    results,
    methods,
    tools,
    logs,
    usage,
    experiment,
    experiment_create,
    experiment_list,
    venv_group,
    venv_create,
    venv_status,
)

# TUI command
import urika.cli.tui  # noqa: F401
from urika.cli.tui import tui  # noqa: F401

# Shell completion (bash / zsh / fish)
import urika.cli.completion  # noqa: F401

# Sessions list / export
import urika.cli.sessions  # noqa: F401

# Project memory (v0.4 Track 2)
import urika.cli.memory  # noqa: F401

# Helpers — re-export for backward compatibility
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
