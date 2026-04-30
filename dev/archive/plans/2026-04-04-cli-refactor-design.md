# CLI Refactor Design — Split cli.py and repl_commands.py

**Date:** 2026-04-04
**Status:** Approved

## Goal

Split `cli.py` (5363 lines) and `repl_commands.py` (1669 lines) into focused modules by command group.

## Architecture

### cli.py split → src/urika/cli/ package

Convert `cli.py` from a single file to a package:

```
src/urika/cli/
  __init__.py         — Click group, entry point, re-exports for backward compat
  _helpers.py         — Shared helpers: _resolve_project, _ensure_project,
                        _sanitize_project_name, _record_agent_usage,
                        _make_on_message, _prompt_numbered, _projects_dir
  project.py          — new, list, status, update, inspect (~600 lines)
  run.py              — run command (~800 lines, biggest single command)
  agents.py           — advisor, evaluate, plan, report, present,
                        finalize, build-tool (~1200 lines)
  config.py           — config, notifications, setup, dashboard (~800 lines)
  knowledge.py        — knowledge subcommands (~200 lines)
  usage.py            — usage, tools, experiment, criteria commands (~400 lines)
```

### repl_commands.py split → src/urika/repl/ package

Convert to a package:

```
src/urika/repl/
  __init__.py         — Re-exports, command registration table
  commands.py         — Simple commands: help, list, project, status, quit, etc.
  cmd_run.py          — cmd_run, cmd_resume, _parse_remote_run_args (~250 lines)
  cmd_agents.py       — cmd_advisor, cmd_evaluate, cmd_plan, cmd_report,
                        cmd_present, cmd_finalize, cmd_build_tool (~400 lines)
  helpers.py          — _pick_experiment, _run_single_agent, _save_presentation,
                        _get_audience, _file_link, get_global_stats (~400 lines)
  session.py          — ReplSession (move from repl_session.py)
```

### Backward compatibility

The entry point in `pyproject.toml` is `urika = "urika.cli:cli"`. After refactor:
- `src/urika/cli/__init__.py` exports the `cli` Click group
- All `from urika.cli import X` statements throughout the codebase continue to work via re-exports in `__init__.py`
- `from urika.repl_commands import X` statements work via re-exports

### Import strategy

- `__init__.py` files re-export everything that external code imports
- Internal cross-references use the new paths
- No circular imports: helpers → (no deps on commands), commands → helpers

### Risk mitigation

- Move one file at a time, run full test suite after each
- Keep old files as thin re-export shims initially, remove once stable
- The @command decorator registration needs to work across files — commands register into a shared dict imported from the package __init__
